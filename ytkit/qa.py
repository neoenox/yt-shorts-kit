"""完成動画の機械検査。"""
import re
import subprocess


def black_spans(path, ffmpeg='ffmpeg', dur=0.5, pix_th=0.04):
    """黒画面の区間 [(開始秒, 長さ秒), ...]。dur 秒以上続く黒だけを拾う。"""
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-i', str(path),
                        '-vf', 'blackdetect=d=%s:pix_th=%s' % (dur, pix_th), '-an', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf8', errors='replace')
    # 出力順に依存せず、キー名で値を拾う（ffmpeg のバージョンで順が変わっても動く）。
    spans = []
    for line in r.stderr.splitlines():
        m = re.search(r'black_start:([\d.]+)', line)
        if not m:
            continue
        d = re.search(r'black_duration:([\d.]+)', line)
        if d:
            spans.append((float(m.group(1)), float(d.group(1))))
    return spans
