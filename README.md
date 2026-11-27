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

`python -m ytkit.youtube research` は `out/youtube_research.md` / `.json` に再生数・エンゲージ付きの比較表を出す。キーが無いときは `python -m ytkit.youtube feed` で `out/youtube_research_rss.md` / `.json` に RSS 由来の比較表（再生数・エンゲージは `-`）を出す。`python -m ytkit.youtube discover` はキーワードからチャンネル候補を表示する。タイトルは長さとハッシュタグの集計だけに使い、パターンの比較に留める部品です。

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

### 検証コマンドと波及チェック
`python` が Microsoft Store の shim を指す環境では pytest が起動しない。次の Python を共通の検証インタプリタとして使う。

```powershell
& 'C:\Users\neoen\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q
```

別の環境では、実際に pytest が動く Python を 1 つ決めて、このコマンドを置き換える。変更したら、次を順に確認する。

1. このリポジトリで上のコマンドを実行し、`passed` と `failed` / `skipped` の数を記録する。
2. 使っているプロジェクトでも同じコマンドを実行し、結果を記録する。実際に共通部品を import しているのは次の3つです。
   - `E:\rekishikaisetu-honnoji` — shim 経由で `ytcore` を使用。`pytest -q tests` が対象（`scripts/test_terrain.py` は `pyproj` が必要）。
   - `E:\rakuten-shorts-affiliate` — `ytkit` の部品を直接使用。`channel.toml` は無い。
   - `E:\rekishikaisetu-detour-lab` — `detour_ffmpeg.py` から `ytkit.ffmpeg_tools` を使用。音声（Kokoro / Piper）と字幕はプロジェクト側に残す。
   `E:\rekishikaisetu` には `channel.toml` はありますが、共通部品の import は見つかっていません。
3. `skipped` が出たら、ffmpeg と Noto Sans/Serif JP VF フォントの有無を確認し、スキップ理由を残す。
4. 両方に変更が要るときは、このリポジトリを先にコミット・push してから、プロジェクト側をコミットする。
5. 編集可能インストールのときは、動画制作中に未コミットの変更を置かない。実験は別ブランチか別環境で行う。

### 描画 Golden の更新
`tests/test_render_golden.py` の `GOLDEN` は、NotoSansJP-VF.ttf / NotoSerifJP-VF.ttf がある環境で 7 フレームを描いたピクセルの SHA-256 です。座標・色・描画順を変えると壊れます。

- 更新してよいのは、描画結果を意図して変えたときだけです。意図しない差分はコードを直し、ハッシュは書き換えません。
- 取り直す担当者が `GOLDEN` を更新し、コメントに日付・フォント環境・変更理由を残します。別環境の値で上書きしません。
- フォントが無い環境ではハッシュ比較がスキップされます。スキップされたら「検証できた」と書かず、上の検証コマンドの記録に理由を残します。
- 更新したら、このリポジトリと使っているプロジェクトの両方で pytest を回します（上の手順 1〜4）。

## 環境変数
`FFMPEG` / `FFPROBE`（実行ファイルの場所）、`VOICEVOX_URL`（既定 `http://127.0.0.1:50021`）、`YT_PROJECT_ROOT`（プロジェクトのルート。`channel.toml` を探す場所）、`FREEVIDEO_URL`（既定 `http://127.0.0.1:8188`）、`FREEVIDEO_OUTPUT_ROOT`（FreeVideo の出力ルート。既定 `output`）、`YOUTUBE_API_KEY`（YouTube リサーチ用）。ytcore の各パイプラインも、これらの環境変数を `ytkit` 経由で呼び出し時に読みます。

## 方針
長尺 `vp`、Short 描画 `make_short` / `make_short2`、`hn_text`、`rich_text` などの描画コアは、すでにここへ移行済みです。モジュール名は変えず、プロジェクト側の `scripts/<名前>.py` を薄い入口にして呼びます。
各プロジェクトはチャンネル固有の値を `channel.toml` に置き、コアはそれを読む。実行ファイル・サービスの場所は環境変数で渡します。
手順書・確認の仕組み・比較対象チャンネルやキーワードなどチャンネル固有のものは、各プロジェクトに残す。YouTube API の呼び出しと集計の部品だけをここで共有する。

## 変えるときの決まり
- 全リポジトリに効く。変更したら両方の `pytest` を回す（`tests/test_kit.py` は移行前の出力文字列、`tests/test_core.py` はytcore のテキスト整形・字幕境界・ロックを確かめている）。
- チャンネル固有の値（話者・BGM・パス・規約）は `channel.toml`、実行ファイルやサービスの場所は環境変数で渡し、ここに固定しない。
- 規約ゲート・承認・公開の処理はここに入れない。

## 境界違反の監査と消化（2026-11-24）
`ytkit` 側は違反なし。実行ファイル・サービスの場所はすべて環境変数経由で、規約ゲート・承認・公開処理も入っていません。依存方向も `ytcore → ytkit` の一方向が保たれています。監査で見つかった3か所は、いずれも設定キーを増やさずに消化しました。

- `ytcore/script_lint.py` — 『信長公記』『東照宮御実紀』の略称検査を削除しました。設定キーを足すと import 時の ConfigError 波及があるため、コアから外しています。ほかの WARN は残り、lint は WARN だけで止めません。`tests/test_core.py` に回帰テストを追加しました。
- `ytcore/vp_check.py` — BGM の既定値 `assets/bgm_maou` / `maou_bgm_{name}.mp3` を外しました。`channel.toml` の `[bgm] dir` / `pattern` が無いときは ERR にします。`BGM` は `vp.py:35` で既に必須なので、利用側の設定変更は不要です。
- `ytcore/make_short.py` — 概要欄の `#Shorts #雑学 #科学` を `TAGS['shorts']` に合わせました。`channel.toml` の `[hashtags] shorts` は既に必須なので、利用側の設定変更は不要です。`tests/test_core.py` に回帰テストを追加しました。

`ytcore/vp.py:31-45` と `ytcore/make_short.py:13-19` は import 時に `channel.toml` を読みます。設定キーを増やすと全プロジェクトの `channel.toml` にそのキーが無い限り import が落ちるので、変更時は注意してください。消化した3件はいずれも設定キーを増やしていないため、このリスクは回避しています。

## 台本レビュー
`ytkit.review` に、台本を ChatGPT と Google AI（`www.google.com/ai`）へ送る共通部品を置いています。各プロジェクトの台本形式は adapter で共通形に直すので、呼び出し側はプロジェクト名と adapter を指定するだけです。

| adapter | 対象 | 台本の場所 |
|---|---|---|
| `honnoji_json` | `rekishikaisetu-honnoji` | `data/short_<slug>.json` |
| `rakuten_result` | `rakuten-shorts-affiliate` | `shorts/<slug>/result.json` |
| `markdown` | `rekishikaisetu-detour-lab` | `SAMPLE_SCRIPT.md` など |

各プロジェクトの入口は `scripts/script_review.py`（rakuten は `script_review_common.py`、detour-lab はリポジトリ直下の `script_review.py`）です。既存の `google_ai_review.py` と `script_review.py` は残してあります。

```powershell
python scripts/script_review.py <slug>                 # 両方に送る（並列実行）
python scripts/script_review.py <slug> --target chatgpt
python scripts/script_review.py <slug> --target google
python scripts/script_review.py <slug> --dry-run       # 依頼文だけ表示
```

既定の `both` は2つの子プロセスを起こして ChatGPT と Google AI に同時に送ります。片方だけ先に見たいときは `--target` で指定します。Playwright の sync API はスレッド間で共有できないため、並列化はスレッドではなく別プロセスで行っています。

返答は `<台本のある dir>/review_<target>_<slug>.md` に保存します。ブラウザは CDP 経由で接続し、落ちていれば最小化で起動します。設定は環境変数 `REVIEW_CDP_PORT`（既定 9222）、`REVIEW_PROFILE`、`CHROME_PATH` で渡します。

実行前に、レビュー用 Chrome で ChatGPT と Google AI にログイン済みであることを確認してください。Google AI は回答の完了マーカーが出るまで待つため、1件あたり1〜3分かかります。bsk のオーバーレイが開いていても返答取得は除外するようになっています。

レビューが終わると、レビュー用 Chrome の ChatGPT と Google AI のタブをすべて閉じます。YouTube Studio など、ほかのタブは残します。

成果物の一覧は次のコマンドで作ります。判定と指摘件数を拾い、元ファイルへのリンクを付けた HTML を出力します。

```powershell
python -m ytkit.review report --roots "E:\rekishikaisetu-honnoji,E:\rakuten-shorts-affiliate,E:\rekishikaisetu-detour-lab" --out out/review_index.html
```

### 任意のテキストをレビューする

Shorts や動画以外の文章も送れる。`{{ARTICLE}}` を含むプロンプトを `--prompt-file` で渡すと、その部分を本文に置換する。

```powershell
python -m ytkit.review custom article.md --prompt-file review/prompt.md --slug article
python -m ytkit.review custom article.md --prompt-file review/prompt.md --slug article --dry-run
```

`noteaffi` の note 記事レビューは `tools/ai_review_common.py` からこの機能を使う。

### 完成動画を Google AI でレビューする

完成動画を `www.google.com/ai` に添付して、字幕・音声・文字の重なり・事実関係など8項目をレビューさせる。

```powershell
python -m ytkit.review video out/short_x.mp4 --slug x --out-dir out
python -m ytkit.review video out/short_x.mp4 --title "動画の題名" --dry-run
```

各プロジェクトの入口からも呼べます。`scripts/script_review_video.py`（honnoji）、`scripts/script_review_video_common.py`（rakuten）、`script_review_video.py`（detour-lab）です。返答は `review_google_video_<slug>.md` に保存し、一覧にも `google-video` として載ります。

動画のアップロードがあるため、台本レビューより時間がかかります。レビュー用 Chrome で Google にログイン済みであること。

### Ask Studio に質問する

YouTube Studio 右上の「Ask Studio」に質問し、返答を保存する。対象アカウントの Chrome プロファイルに CDP で接続する。

```powershell
python -m ytkit.review studio "今月の視聴回数が多い動画を教えて" --slug growth --out-dir out
python -m ytkit.review studio --question-file question.md --slug growth
```

各プロジェクトの入口は `scripts/ask_studio.py`（honnoji）、`scripts/ask_studio_common.py`（rakuten）、`ask_studio.py`（detour-lab）、`tools/ask_studio_common.py`（noteaffi）です。返答は `ask_studio_<slug>.md` に保存します。

設定は `STUDIO_CDP_PORT`（既定 9222）、`STUDIO_PROFILE`（既定 `C:\Users\neoen\.chrome-gemienox`）、`STUDIO_PROFILE_DIR`（既定 `Profile 3`）で渡します。レビュー用の `REVIEW_*` とは別です。

設計は `docs/superpowers/specs/2026-11-26-script-review-design.md` にあります。
