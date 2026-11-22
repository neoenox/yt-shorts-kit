"""動画制作のコア(複数のチャンネル/プロジェクトで共有する描画・テキスト整形)。

ytkit が「土台の部品」(ffmpeg・VOICEVOX など)なのに対し、ytcore は動画の描画そのもの。
チャンネル固有の値は、各プロジェクトの channel.toml(ytkit.project で読む)に置く。
プロジェクト側の scripts/<名前>.py は薄い入口(shim)で、環境変数 YT_PROJECT_ROOT を設定してここを呼ぶ。
"""
