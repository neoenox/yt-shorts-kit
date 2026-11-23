"""字幕ファイル（SRT）の共通部品。

Short / 長尺のどちらも、秒で表した開始・終了と本文から同じ形式で書き出す。
"""
from pathlib import Path


def srt_time(t):
    """秒 → SRT の時刻表記 `HH:MM:SS,mmm`。"""
    ms = max(0, round(t * 1000))
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'


def write_srt(path, cues):
    """cues の (開始秒, 終了秒, 本文) を SRT として書く。"""
    text = '\n\n'.join(
        f'{i + 1}\n{srt_time(a)} --> {srt_time(b)}\n{c}'
        for i, (a, b, c) in enumerate(cues)
    ) + '\n'
    Path(path).write_text(text, encoding='utf8')
