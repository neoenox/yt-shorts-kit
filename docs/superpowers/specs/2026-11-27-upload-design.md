# 動画アップロード共通化の設計（2026-11-27）

## 目的

`ytkit.upload` に、YouTube Studio へ動画をアップロードして**非公開**で保存する共通部品を置く。公開は明示オプション（`--publish` / `publish=True`）のときだけ行う。アップロード先チャンネルは明示的な ID で指定し、既定値は持たない（`README.md` の「動画アップロード」節）。

台本レビューの共通化については `docs/superpowers/specs/2026-11-26-script-review-design.md` を参照。

## 範囲

含めるもの:

- アップロード用パックの検証と読み込み（`ytkit/upload/pack.py`）
- YouTube Studio のブラウザ操作（`ytkit/upload/studio.py`）
- `python -m ytkit.upload` の CLI（`ytkit/upload/__main__.py`、`ytkit/upload/__init__.py`）
- ブラウザを触らない回帰テスト（`tests/test_upload.py`）
- `README.md` の「動画アップロード」節、`pyproject.toml` の `browser` extra（`playwright>=1.40`）

含めないもの:

- README に記載された既存のアップロード手順の削除・置き換え
- Playwright / Chrome の自動インストール（セットアップは README の手順に任せる）
- ログイン・認証の自動化（既存の Chrome プロファイルのセッションを使う）
- 既定チャンネルや複数チャンネルへの同時アップロード（ID は毎回明示）
- 動画・字幕・サムネイルの生成（パックに揃ったファイルを添付するだけ）
- 公開後の集計・分析

## アーキテクチャ

3層に分け、各層を独立してテストできるようにする。

### 1. `ytkit.upload.pack` — パックの読み込み

`FILES` にファイル名と必須/任意を定義し、`load_pack(path)` がパック 1 フォルダを読む。戻り値は各ファイルの `Path` と、本文を読み込んだ `title_text` / `description_text` を持つ辞書。`ytkit/upload/__init__.py` から `load_pack` を公開する。

### 2. `ytkit.upload.studio` — Studio 操作

`upload(pack, slug='video', publish=False, dry_run=False, timeout=600, channel_id=None)` を公開する。`ytkit/upload/__init__.py` から `upload` を公開する。内部で `upload_url` / `_ensure_chrome` / `_stop_owned_chrome` / `_cdp` / `_upload_captions` などを呼ぶ。`dry_run=True` ならブラウザに触れず、`slug` / `title` / `video` / `publish` の辞書を返す。

### 3. `ytkit.upload.__main__` — CLI

`main(argv)` が `run` / `check` のサブコマンドを解析し、`load_pack` と `upload` をつなぐ。結果は JSON で標準出力に出す（通常の `run` では `tail` キーを除外）。

## パック契約

1 フォルダに次を揃える（`ytkit/upload/pack.py` の `FILES`）。

| ファイル | 必須 | 用途 |
|---|---|---|
| `video.mp4` | 必須 | アップロードする動画 |
| `title.txt` | 必須 | タイトル（前後空白を除去） |
| `description.txt` | 必須 | 概要欄（前後空白を除去。ハッシュタグはここに含める、`README.md`） |
| `thumbnail.jpg` | 任意 | サムネイル |
| `subtitles.srt` | 任意 | 保存後に添付する日本語字幕 |

検証は次の順で行い、失敗時は明示的に例外を出す。

- パック フォルダが無い / 必須ファイルが無い → `FileNotFoundError`
- `title.txt` が空 → `ValueError`
- `description_text` が 20 文字未満 → `ValueError`

`check` サブコマンドはこの読み込みだけを行い、タイトル、概要の文字数、動画パス、サムネイル/字幕の有無を JSON で返す。

## コマンド

```powershell
python -m ytkit.upload check <pack_dir>                              # パック検証のみ
python -m ytkit.upload run <pack_dir> --slug my_video --dry-run      # ブラウザを触らず確認
python -m ytkit.upload run <pack_dir> --slug my_video                # 非公開で保存
python -m ytkit.upload run <pack_dir> --slug my_video --publish      # 明示時のみ公開
```

`run` の引数は `pack`（位置）、`--slug`、`--publish`、`--dry-run`、`--timeout`（既定 600）、`--channel-id`。`--slug` を省略した場合はパック フォルダ名を使う。通常の保存結果は `slug` / `saved` / `video_id` / `publish` と、字幕を添付した場合の `subtitles` を含む。

## 環境変数

| 変数 | 既定値 | 読み込み箇所と意味 |
|---|---|---|
| `UPLOAD_CHANNEL_ID` | なし | `studio.upload_url` が参照。`channel_id` 引数が優先。未指定なら `ValueError` |
| `UPLOAD_CDP_PORT` | なし | `studio._port` が参照。未指定なら `_free_port()` で空きポートを取得し、`_port_cache` に保持 |
| `UPLOAD_PROFILE` | `C:\Users\neoen\.chrome-gemienox` | `_ensure_chrome` の `--user-data-dir` |
| `UPLOAD_PROFILE_DIR` | `Profile 3` | `_ensure_chrome` の `--profile-directory`。空文字ならフラグを付けない |
| `CHROME_PATH` | `C:\Program Files\Google\Chrome\Application\chrome.exe` | `_ensure_chrome` が起動する Chrome。存在しなければ `FileNotFoundError` |

Ask Studio と同じプロファイルを使う。既存 Chrome に接続する場合は `UPLOAD_CDP_PORT` / `UPLOAD_PROFILE` を明示する（`README.md`）。`_cdp()` は `http://127.0.0.1:<port>` を返す。

## 非公開既定と明示的なチャンネル ID

`upload_url(channel_id)` は `https://studio.youtube.com/channel/<id>/videos/upload` を組み立てる。ID 無しの `/videos/upload` は「エラーが発生しました」になることがあるため、引数か `UPLOAD_CHANNEL_ID` のどちらかを必須とする。

`upload` の `publish` は既定 `False`。公開設定画面で選ぶラベルは `publish=True` のとき `公開`、それ以外は `非公開`。CLI では `--publish` を付けたときだけ `True` になる。1 日のアップロード上限を示す `LIMIT_MARKERS` を画面本文から検出したら `RuntimeError` で中断する。

## 字幕の添付と公開

`subtitles.srt` がある場合、動画保存後に `upload` が `_video_id(pg)` で video ID を取得し、`_upload_captions(pg, video_id, srt)` を呼ぶ。ID が取れなければ `RuntimeError` とする。

`_upload_captions` は `https://studio.youtube.com/video/<video_id>/translations` を開き、「手動でアップロード」→「続行」→ファイル選択（`set_files`）→「字幕を編集」→「公開」の順で操作する。字幕トラックの公開は動画の `publish` 設定とは独立して行い、成功すると結果辞書に `subtitles='published'` を入れる。

## Chrome の所有権と CDP 障害

`_ensure_chrome()` はまず `127.0.0.1:_port()` への接続を試み、応答があれば何も起動せず戻る。応答が無い場合だけ、指定の実行ファイル・プロファイルで `--remote-debugging-port` / `--user-data-dir` / `--minimize` / `--profile-directory` を付けて起動し、`_chrome_proc` に保持する。

`_stop_owned_chrome()` が停止対象にできるのは `_chrome_proc` が保持する PID だけである。Windows では `taskkill /F /T /PID <pid>`、それ以外では `terminate()` 後に必要なら `kill()` を使う。所有していなければ `False` を返し、何も停止しない。名前やポートで全 Chrome を殺す処理は入れない。

CDP 接続の失敗は 1 回の接続試行（15 秒）を単位とする。

1. `connect_over_cdp` が失敗したら `_stop_owned_chrome()` を呼ぶ。
2. 自プロセスが起動した Chrome が無ければ、`RuntimeError`（CDP アドレスと `UPLOAD_CDP_PORT` / `UPLOAD_PROFILE` の確認を促すメッセージ。既存 Chrome は停止しない）を出す。
3. 所有していれば停止し、4 秒待って `_ensure_chrome()` で起動し直し、2 回目の `connect_over_cdp`（30 秒）を行う。再試行はこの 1 回のみ。

接続後は `browser.contexts[0]` の `studio.youtube.com` の既存ページを閉じてから新規ページを開き、処理の `finally` でそのページを閉じる。

## 検証

- `tests/test_upload.py`（ブラウザを触らない回帰テスト）:
  - `load_pack` の必須ファイル・空タイトル
  - `dry_run` がブラウザを開かないこと、`check` の JSON
  - `upload_url` のチャンネル ID（引数 / 環境変数 / 未指定時のエラー）
  - `_port` の自動取得と明示指定
  - `_video_id_from_url`、`_upload_captions` の添付・公開手順
  - `_stop_owned_chrome` が自分の PID だけを対象にすること
  - CDP 失敗時に、所有 Chrome が無ければ既存ブラウザを再起動しないこと、所有していれば 1 回だけ再起動すること
- 実行コマンド（検証用 Python）:
  ```powershell
  & "C:\Users\neoen\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_upload.py
  ```
