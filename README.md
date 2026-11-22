# yt-shorts-kit

複数のYouTube動画制作リポジトリで共有する**部品**。描画・台本形式・規約ゲートは入れていません（チャンネルごとに違うため）。

| モジュール | 中身 | 使っているリポジトリ |
|---|---|---|
| `ytkit.ffmpeg_tools` | `find_ffmpeg` / `find_ffprobe` / `probe_duration` | rekishikaisetu、rakuten-shorts-affiliate |
| `ytkit.loudness` | `measure_ebur128` / `measure_loudnorm` / `loudnorm_filter` | 同上 |
| `ytkit.qa` | `black_spans` | rekishikaisetu |
| `ytkit.voicevox` | `speaker_id` / `apply_pron` / `synth` | 同上 |
| `ytkit.freevideo` | ComfyUI(FreeVideo)の HTTP API | rakuten-shorts-affiliate |
| `ytkit.project` | `project_root`(環境変数 `YT_PROJECT_ROOT` 優先)・`load_config`(`channel.toml`)・`require`(足りないキーを名指しして止める) | rekishikaisetu(`make_short.py`・`make_short2.py`) |

## ytcore（動画制作のコア。2026-11-22 に取り込み）
`ytkit` が土台の部品なのに対し、`ytcore` は動画の描画そのもの。履歴は `git filter-repo` で保って取り込んだ(`git log -- ytcore/make_short2.py` で元の履歴が辿れる)。

| モジュール | 中身 |
|---|---|
| `ytcore.make_short` / `ytcore.make_short2` | 縦型 Short の描画(終了カード・字幕・概要欄・BGMミックス)。`python scripts/make_short2.py <slug>` |
| `ytcore.first_frame_preview` | Short の冒頭を縮小して並べる(全編レンダの前の確認) |
| `ytcore.hn_text` / `ytcore.thin_commas` / `ytcore.rich_text` | 日本語の数字表記・読点の整理・強調語の描画 |
| `ytcore.vp_lock` | 長尺ビルドの二重起動防止 |
| `ytcore.vp` / `ytcore.vp_check` / `ytcore.vp_preview` / `ytcore.script_lint` | 長尺(解説動画)のパイプライン。story→kana→audio→bgm→build→qa→desc→thumb と、描画前の検査・場面の一覧・台本の検査。`python scripts/vp.py <slug> <コマンド>` |

**使い方**: プロジェクトの `scripts/<名前>.py` を薄い入口(shim)にする。shim が `YT_PROJECT_ROOT` を設定して `ytcore.<名前>` を呼ぶので、`import make_short` も `python scripts/make_short2.py` も従来どおり動く。
チャンネル固有の値は、プロジェクト直下の `channel.toml`(`ytkit.project` が読む)に置く。

**プロジェクトに求める約束事(vp)**: ①`channel.toml` の `[project] plugin_dir`(既定 `scripts`)に、プラグイン(動画ごとの動く図 `vp_anim*.py`、`make_upload_pack.py`、`ffmpeg_skill_check.py`)を置く。コアはこの場所を `sys.path` に足して import する。②`data/<slug>_spec.json`・`data/<slug>_*.json`・`out/`・`cache/`・`docs/themes/<theme>/09_script_v2.md`・`assets/` の配置。③部品は `python -m ytcore.vp` のサブプロセスで動く(自分のファイルのパスには頼らない)。描画コードの指紋は、`vp.py` 本体・`plugin_dir` の `vp_anim*.py`・text helpers の中身を、行末を除いて名前順に読む。

**まだ移していないもの**: プロジェクト固有の部品(`vp_anim*.py` など)・手順書と確認の仕組み・`yt_api.py`。

## 入れ方（手元の Windows。編集すると全リポジトリに反映される）

```powershell
python -m pip install -e E:\yt-shorts-kit
```

使うリポジトリごとの環境（`.venv` など）に入れる。

## GitHub から入れる（新しい環境・他のパソコン）
公開リポジトリ: https://github.com/neoenox/yt-shorts-kit

```powershell
uv pip install "yt-shorts-kit @ git+https://github.com/neoenox/yt-shorts-kit@master"
```

版を固定したいときは、`@master` を、タグかコミットのハッシュにする(例: `@v0.2.0`、`@6328386`)。
プロジェクト側の `scripts/setup.ps1` は、隣のフォルダーに `yt-shorts-kit` があれば編集可能で、無ければここから入れる。

## 運用
- **コアを直すのは、このリポジトリだけ**。プロジェクト側の `scripts/<名前>.py` は薄い入口(shim)なので、直さない。
- 編集可能インストールでは、ここを直すと、使っているプロジェクトにすぐ反映される。動画を作っている最中に、未コミットの編集を置いたままにしない。
- 直したら、`pytest` を、ここと使っているプロジェクトの両方で回す。両方に変更が要るときは、**ここを先にコミット・push** してから、プロジェクト側をコミットする。
- 履歴を書き換えない(公開済みのため)。メールアドレスは GitHub の noreply アドレスにしてある。

## 環境変数
`FFMPEG` / `FFPROBE`（実行ファイルの場所）、`VOICEVOX_URL`（既定 `http://127.0.0.1:50021`）、`YT_PROJECT_ROOT`（プロジェクトのルート。`channel.toml` を探す場所）。

## 今後の方針
最終的に、動画制作のコア(長尺 `vp`、Short 描画 `make_short`/`make_short2`、`hn_text`、`rich_text` など)もここへ移す。
各プロジェクトはチャンネル固有の値を `channel.toml` に置き、コアはそれを読む。モジュール名は変えない(`import vp` のまま使える)。
手順書・確認の仕組み・`yt_api.py` のようにチャンネル固有のものは、各プロジェクトに残す。

## 変えるときの決まり
- 全リポジトリに効く。変更したら両方の `pytest` を回す（`tests/test_kit.py` は移行前の出力文字列と一致することを確かめている）。
- チャンネル固有の値（話者、パス、規約）はここに書かず、呼ぶ側から渡す。
- 規約ゲート・承認・公開の処理はここに入れない。
