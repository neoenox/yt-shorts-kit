"""音量の測定と、loudnorm フィルタの組み立て。"""
import json
import re
import subprocess

TARGET_LUFS = -14.0
TARGET_TP = -1.5


def measure_ebur128(path, ffmpeg='ffmpeg'):
    """(integrated LUFS, true peak dBFS)。測れなければ None。

    ebur128 は解析中も経過を出すので、`I:` は最初の -70.0（無音）に当たる。
    最後に出るサマリの値を使う。
    """
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-i', str(path),
                        '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf8', errors='replace')
    i = re.findall(r'I:\s*(-?[\d.]+)\s*LUFS', r.stderr)
    p = re.findall(r'Peak:\s*(-?[\d.]+)\s*dBFS', r.stderr)
    return (float(i[-1]) if i else None, float(p[-1]) if p else None)


def measure_loudnorm(path, ffmpeg='ffmpeg', i=TARGET_LUFS, tp=TARGET_TP, lra=7):
    """loudnorm の1パス目。input_i / input_tp / input_lra / input_thresh / target_offset を含む dict。"""
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-i', str(path), '-af',
                        'loudnorm=I=%s:TP=%s:LRA=%s:print_format=json' % (_n(i), _n(tp), _n(lra)),
                        '-f', 'null', '-'],
                       capture_output=True, text=True, errors='replace')
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def loudnorm_filter(measured=None, i=TARGET_LUFS, tp=TARGET_TP, lra=7, limiter=None):
    """loudnorm の -af 文字列。

    measured があれば2パス目（linear=true。全体に一定のゲインをかけるので、
    BGM とナレーションの相対レベルが保たれる）。無ければ1パスの動的 loudnorm。
    limiter は末尾へ足すフィルタ（例: 'alimiter=limit=0.79:level=disabled'）。
    """
    head = 'loudnorm=I=%s:TP=%s:LRA=%s' % (_n(i), _n(tp), _n(lra))
    if measured:
        head += (':measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true'
                 % (measured['input_i'], measured['input_tp'], measured['input_lra'],
                    measured['input_thresh'], measured['target_offset']))
    return head + (',' + limiter if limiter else '')


def _n(x):
    """-14.0 → '-14'、-1.5 → '-1.5'（フィルタ文字列を整数のときは整数で書く）。"""
    return '%g' % float(x)
