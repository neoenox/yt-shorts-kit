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

## 入れ方（手元の Windows。編集すると全リポジトリに反映される）

```powershell
python -m pip install -e E:\yt-shorts-kit
```

使うリポジトリごとの環境（`.venv` など）に入れる。

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
