# 台本レビュー共通化の設計（2026-11-26）

## 目的

台本を受け取り、ChatGPT と `www.google.com/ai` にレビューを依頼し、各プロジェクトの成果物を1つの一覧ページで確認できるようにする。共通部品は `ytkit` に置き、各プロジェクトは薄い入口（shim）だけを持つ。

現在、似た機能がプロジェクトごとにバラバラに存在する。

- `rekishikaisetu-honnoji/scripts/google_ai_review.py` — Playwright、CDP ポート 9222、`data/short_<slug>.json`、出力 `out/google_ai_review_<slug>_<mode>.txt`
- `rakuten-shorts-affiliate/scripts/script_review.py` — 生CDP（自作 `cdp_client.py`）、ポート 9223、`shorts/<slug>/result.json`、出力 `review_chatgpt.md` / `review_gemini.md`
- `rakuten-shorts-affiliate/scripts/google_ai_review.py` — 生CDP、ポート 9223、完成動画を添付
- `rekishikaisetu-detour-lab` — 台本は `SAMPLE_SCRIPT.md`、レビュー自動化は無し

これらを共通化し、入力形式と出力先の違いを adapter に閉じ込める。

## 範囲

含めるもの:

- 台本を共通形に変換する adapter
- ChatGPT と Google AI への依頼文を組み立てるプロンプト生成
- Playwright による送信と返答取得
- 各プロジェクトのレビュー結果を走査する HTML 一覧ページの生成
- 3プロジェクトへの薄い shim 追加

含めないもの:

- 完成動画の添付と映像レビュー（別作業）
- 返答内容の自動判定・自動採用（人が読んで採用する）
- プロジェクト固有の規約・承認フロー（各プロジェクトに残す）

## アーキテクチャ

4層に分ける。各層は1つの責任を持ち、独立してテストできる。

### 1. `ytkit.review.script` — 入力変換

各プロジェクトの台本を共通形に変換する。共通形は次の辞書とする。

```python
{
    'project': str,      # 'rekishikaisetu-honnoji' など
    'slug': str,
    'title': str,
    'scenes': [{'text': str, 'big': str, 'caption': str, 'source': str}],
    'claims': [{'id': str, 'statement': str, 'source_url': str, 'evidence_note': str}],
    'needs_research': [str],
}
```

adapter は `load(path, project, slug)` の形で実装し、プロジェクトごとに `REGISTRY` に登録する。既存形式は次の3つ。

- `honnoji_json`: `data/short_<slug>.json` を読む。`scenes` の `text` / `big` / `src`、`claims`、`needs_research` を写す。
- `rakuten_result`: `shorts/<slug>/result.json` を読む。`scenes` の `narration` / `caption` / `visual`、`claims` を写す。
- `markdown`: `SAMPLE_SCRIPT.md` のような生テキストを、区切り（`##` 見出し）ごとに `scenes` へ分割する。`claims` は空。

adapter が見つからない形式は `ValueError` で明示的に失敗させる。

### 2. `ytkit.review.prompt` — 依頼文生成

共通形から2つの依頼文を組み立てる。

- `build_chatgpt_prompt(script)` — 既存 `rakuten/scripts/script_review.py:59-116` のプロンプトをベースにする。事実の正確さ、出典対応、読みやすさ、構成、抜けている文脈の5観点。出力形式は「総評／指摘一覧／問題ない点／自信の低い判断」。表は使わない。
- `build_google_prompt(script)` — 既存 `honnoji/scripts/google_ai_review.py:29-72` の依頼文をベースにする。字幕と音声の一致、表記の違和感、文字の重なり、事実関係、公開可か修正必要か。

両者に共通する末尾の区切り `===ここまでが台本です===` は定数にする。台本を書き直させない指示も共通化する。

### 3. `ytkit.review.browser` — 送信と返答取得

Playwright の `connect_over_cdp` を使う。設定は環境変数で受ける。

- `REVIEW_CDP_PORT` — 既定 `9222`
- `CHROME_PATH` — 既定 `C:\Program Files\Google\Chrome\Application\chrome.exe`
- `REVIEW_PROFILE` — 既定 `C:\Users\neoen\.chrome-automation`

ブラウザが起動していなければ最小化で起動する（既存 `honnoji/scripts/chrome_launch.py` 相当の処理を共通化）。

送信先は次の2つ。

| target | URL | composer | reply |
|---|---|---|---|
| `chatgpt` | `https://chatgpt.com/` | `div.ProseMirror[contenteditable="true"], #prompt-textarea` | `div[data-message-author-role="assistant"]` |
| `google` | `https://www.google.com/ai/` | `textarea, div[contenteditable="true"]` | 既存 honnoji の返答取得ロジックを流用 |

`submit(script, target, dry_run=False, timeout=180)` の形で公開する。`dry_run=True` ならプロンプトを返すだけでブラウザを触らない。

返答本文は eventually-consistent なので、送信ボタンが無効になった後、返答要素のテキストが安定するまで待つ。UI 文言（「AI モードが回答を生成しています」など）は末尾から除く（既存 rakuten の `TRAILING_UI` を利用）。

### 4. `ytkit.review.report` — 一覧ページ生成

各プロジェクトの出力先を走査する。出力ファイル名は次の規則に統一する。

```
<project_root>/out/review_<target>_<slug>.md
```

`target` は `chatgpt` または `google`。既存ファイル名（`google_ai_review_<slug>_script.txt` など）も読めるように、既存パターンを `LEGACY_PATTERNS` として残す。

各ファイルから次を抽出する。

- 判定: 「公開可」「修正必要」「作り直し」のいずれか。無ければ「判定なし」。
- 指摘件数: 「重大度: 高／中／低」の行数。
- 更新日時: ファイルの mtime。

HTML 一覧は `project` / `slug` / `target` / `判定` / `指摘件数` / `更新日時` の表と、各行から元ファイルへのリンクを持つ。単一ファイルで、外部 CSS / JS は使わない。

`python -m ytkit.review report --roots <dir1>,<dir2>,... --out <html>` で実行する。

## データフロー

```
各プロジェクトの台本
  → ytkit.review.script (adapter)
  → 共通形
  → ytkit.review.prompt (ChatGPT 用 / Google AI 用)
  → ytkit.review.browser (Playwright)
  → <project>/out/review_<target>_<slug>.md
  → ytkit.review.report
  → out/review_index.html
```

## 各プロジェクトの shim

3プロジェクトに `scripts/script_review.py` を置く。内容は共通部品を呼ぶだけの数行で、台本形式とプロジェクト名を指定する。

- honnoji: adapter `honnoji_json`、ルートは `Path(__file__).parents[1]`
- rakuten: adapter `rakuten_result`
- detour-lab: adapter `markdown`、`slug` は引数（例 `ocean_blue`）

既存の `google_ai_review.py` は消さずに残す。移行期は両方が動く状態にする。

## エラー処理

- adapter が見つからない / ファイルが無い → `FileNotFoundError` または `ValueError` を明示
- ブラウザに接続できない → 自動起動を試み、失敗したらメッセージを出して終了
- 送信ボタンが時間内に有効にならない → `TimeoutError`
- 返答が空のまま timeout → `TimeoutError`。部分的な返答は保存してから失敗を報告する
- 一覧生成時に broken link な成果物は「読めません」と表示し、スキップしない

## テスト

`tests/test_review.py` を新規作成する。

- adapter: 3形式それぞれについて、共通形の主要キーが埋まることを固定
- prompt: 共通の区切り文字と、台本本文が含まれること。表を使わない指示が入ること
- report: サンプルの `review_*_<slug>.md` を tmp_path に作り、判定・件数・リンクが HTML に入ること
- browser は実ブラウザを触らず、`dry_run=True` の経路だけをテストする

既存の 58 tests が壊れないことも確認する。

## 運用への反映

`README.md` に「台本レビュー」節を追加し、共通コマンド、環境変数、各プロジェクトの adapter 名、一覧ページの開き方を記載する。既存の `google_ai_review.py` / `script_review.py` との移行関係も一言書く。
