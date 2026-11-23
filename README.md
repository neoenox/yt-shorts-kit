# yt-shorts-kit

複数のYouTube動画制作リポジトリで共有するパッケージ。`ytkit` は土台の部品、`ytcore` は描画コア。台本形式・規約ゲートはチャンネルごとに違うため入れていません。YouTube リサーチの API 部品も `ytkit` に置きます。

| モジュール | 中身 | 使っているリポジトリ |
|---|---|---|
| `ytkit.ffmpeg_tools` | `find_ffmpeg` / `find_ffprobe` / `probe_duration` | rekishikaisetu、rakuten-shorts-affiliate |
| `ytkit.loudness` | `measure_ebur128` / `measure_loudnorm` / `loudnorm_filter` | 同上 |
| `ytkit.qa` | `black_spans` | rekishikaisetu |
| `ytkit.voicevox` | `speaker_id` / `apply_pron` / `synth` | 同上 |
| `ytkit.freevideo` | ComfyUI(FreeVideo)の HTTP API | rakuten-shorts-affiliate |
| `ytkit.project` | `project_root`(環境変数 `YT_PROJECT_ROOT` 優先)・`load_config`(`channel.toml`)・`require`(足りないキーを名指しして止める) | rekishikaisetu(`make_short.py`・`make_short2.py`) |
| `ytkit.youtube` | 競合チャンネルの投稿間隔・タイトル傾向・タグを集計。`research`（API キー必須）/`feed`（公開 RSS・キー不要）/`discover` | 全プロジェクト共通の部品 |

## YouTube リサーチ

比較したいチャンネル ID はプロジェクトの `channel.toml` に置く。完全な指標（再生数・エンゲージ・尺）は `YOUTUBE_API_KEY` が必要。キーが無い場合は公開 RSS の `feed` で投稿間隔とタイトル傾向だけを集計できる。

```toml
[research]
channels = ["UC...", "UC..."]
lookback_days = 90
max_per_channel = 50
topics = ["戦国時代", "雑学"]   # discover 用。search.list は quota を多く使う
feed_limit = 15       # feed で見る直近の本数（既定 15）
```

`python -m ytkit.youtube research` は `out/youtube_research.md` / `.json` に再生数・エンゲージ付きの比較表を出す。キーが無いときは `python -m ytkit.youtube feed` で `out/youtube_research_rss.md` / `.json` に RSS 由来の比較表（再生数・エンゲージは `-`）を出す。`python -m ytkit.youtube discover` はキーワードからチャンネル候補を表示する。タイトルやサムネイルを丸写しせず、投稿のパターンを比較するための部品です。

## ytcore（動画制作のコア。2026-11-22 に取り込み）
`ytkit` が土台の部品なのに対し、`ytcore` は動画の描画そのもの。履歴は `git filter-repo` で保って取り込んだ(`git log -- ytcore/make_short2.py` で元の履歴が辿れる)。

| モジュール | 中身 |
|---|---|
| `ytcore.make_short` / `ytcore.make_short2` | 縦型 Short の描画(終了カード・字幕・概要欄・BGMミックス)。`python scripts/make_short2.py <slug>` |
| `ytcore.subtitles` | SRT の時刻変換と書き出し(Short・長尺で共有) |
| `ytcore.first_frame_preview` | Short の冒頭を縮小して並べる(全編レンダの前の確認) |
| `ytcore.hn_text` / `ytcore.thin_commas` / `ytcore.rich_text` | 日本語の数字表記・読点の整理・強調語の描画 |
| `ytcore.vp_lock` | 長尺ビルドの二重起動防止 |
| `ytcore.vp` / `ytcore.vp_check` / `ytcore.vp_preview` / `ytcore.script_lint` | 長尺(解説動画)のパイプライン。story→kana→audio→bgm→build→qa→desc→thumb と、描画前の検査・場面の一覧・台本の検査。`python scripts/vp.py <slug> <コマンド>` |

**使い方**: プロジェクトの `scripts/<名前>.py` を薄い入口(shim)にする。shim が `YT_PROJECT_ROOT` を設定して `ytcore.<名前>` を呼ぶので、`import make_short` も `python scripts/make_short2.py` も従来どおり動く。
チャンネル固有の値は、プロジェクト直下の `channel.toml`(`ytkit.project` が読む)に置く。

**プロジェクトに求める約束事(vp)**: ①`channel.toml` の `[project] plugin_dir`(既定 `scripts`)に、プラグイン(動画ごとの動く図 `vp_anim*.py`、`make_upload_pack.py`、`ffmpeg_skill_check.py`)を置く。コアはこの場所を `sys.path` に足して import する。②`data/<slug>_spec.json`・`data/<slug>_*.json`・`out/`・`cache/`・`docs/themes/<theme>/09_script_v2.md`・`assets/` の配置。③部品は `python -m ytcore.vp` のサブプロセスで動く(自分のファイルのパスには頼らない)。描画コードの指紋は、`vp.py` 本体・`plugin_dir` の `vp_anim*.py`・text helpers の中身を、行末を除いて名前順に読む。

**まだ移していないもの**: プロジェクト固有の部品(`vp_anim*.py` など)・手順書と確認の仕組み・比較対象チャンネルのリスト。YouTube API の汎用クライアントは `ytkit.youtube` に置いた。

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
`FFMPEG` / `FFPROBE`（実行ファイルの場所）、`VOICEVOX_URL`（既定 `http://127.0.0.1:50021`）、`YT_PROJECT_ROOT`（プロジェクトのルート。`channel.toml` を探す場所）、`FREEVIDEO_OUTPUT_ROOT`（FreeVideo の出力ルート。既定 `output`）、`YOUTUBE_API_KEY`（YouTube リサーチ用）。ytcore の各パイプラインもこれらの環境変数を `ytkit` 経由で読みます。

## 方針
長尺 `vp`、Short 描画 `make_short` / `make_short2`、`hn_text`、`rich_text` などの描画コアは、すでにここへ移行済みです。モジュール名は変えず、プロジェクト側の `scripts/<名前>.py` を薄い入口にして呼びます。
各プロジェクトはチャンネル固有の値を `channel.toml` に置き、コアはそれを読む。実行ファイル・サービスの場所は環境変数で渡します。
手順書・確認の仕組み・比較対象チャンネルやキーワードなどチャンネル固有のものは、各プロジェクトに残す。YouTube API の呼び出しと集計の部品だけをここで共有する。

## 変えるときの決まり
- 全リポジトリに効く。変更したら両方の `pytest` を回す（`tests/test_kit.py` は移行前の出力文字列、`tests/test_core.py` はytcore のテキスト整形・字幕境界・ロックを確かめている）。
- チャンネル固有の値（話者・BGM・パス・規約）は `channel.toml`、実行ファイルやサービスの場所は環境変数で渡し、ここに固定しない。
- 規約ゲート・承認・公開の処理はここに入れない。
