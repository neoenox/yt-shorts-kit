"""複数のYouTube動画制作リポジトリで共有する部品。

描画・台本形式・規約ゲートは含めない（チャンネルごとに違うため）。
含めるのは、どのリポジトリでも同じ働きをする土台だけ:
  ffmpeg_tools … ffmpeg/ffprobe の探索、尺の取得
  loudness     … 音量の測定と loudnorm フィルタの組み立て
  qa           … 黒画面などの検査
  voicevox     … VOICEVOX ENGINE への問い合わせ
  freevideo    … FreeVideo(ローカル ComfyUI)の HTTP API
"""
__version__ = '0.2.0'
