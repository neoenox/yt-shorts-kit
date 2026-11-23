"""ffmpeg / ffprobe の探索と、動画の尺の取得。"""
import os
import shutil
import subprocess
from pathlib import Path


class FFmpegNotFound(RuntimeError):
    pass


def _exists(c):
    return bool(c) and Path(c).is_file()


def find_ffmpeg(prefer=(), fallback=()):
    """ffmpeg の実行ファイルを探す。

    順序: 環境変数 FFMPEG → prefer → PATH → fallback。
    prefer はリポジトリ同梱の ffmpeg など「PATH より優先したい場所」、
    fallback は「他に無いときだけ使う場所」。見つからなければ FFmpegNotFound。
    """
    for c in (os.environ.get('FFMPEG'), *prefer, shutil.which('ffmpeg'), *fallback):
        if _exists(c):
            return str(c)
    raise FFmpegNotFound('ffmpeg が見つからない。PATH か環境変数 FFMPEG で指定する')


def find_ffprobe(ffmpeg=None, prefer=(), default=None):
    """ffprobe を探す。

    順序: 環境変数 FFPROBE → ffmpeg と同じフォルダ → prefer → PATH → default。
    見つからないとき default をそのまま返す（None なら None）。
    """
    cands = [os.environ.get('FFPROBE')]
    if ffmpeg:
        p = Path(ffmpeg)
        cands.append(p.with_name('ffprobe' + p.suffix))
    cands.extend(prefer)
    cands.append(shutil.which('ffprobe'))
    for c in cands:
        if _exists(c):
            return str(c)
    return default


def probe_duration(path, ffprobe='ffprobe'):
    """動画・音声の長さ（秒）。測れなければ None。"""
    if not ffprobe:
        return None
    try:
        r = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'csv=p=0', str(path)], capture_output=True, text=True)
    except OSError:
        return None
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None
