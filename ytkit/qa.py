"""完成動画の機械検査。"""
import re
import subprocess


def black_spans(path, ffmpeg='ffmpeg', dur=0.5, pix_th=0.04):
    """黒画面の区間 [(開始秒, 長さ秒), ...]。dur 秒以上続く黒だけを拾う。"""
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-i', str(path),
                        '-vf', 'blackdetect=d=%s:pix_th=%s' % (dur, pix_th), '-an', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf8', errors='replace')
    return [(float(a), float(d)) for a, d in
            re.findall(r'black_start:([\d.]+)\s+black_end:[\d.]+\s+black_duration:([\d.]+)', r.stderr)]
