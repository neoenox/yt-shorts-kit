"""ffmpeg / ffprobe の探索と、動画の尺の取得。"""
import functools
import os
import shutil
import subprocess
from pathlib import Path


class FFmpegNotFound(RuntimeError):
    pass


def _exists(c):
    return bool(c) and Path(c).is_file()


@functools.lru_cache(maxsize=64)
def _find_ffmpeg(env, path, prefer, fallback):
    for c in (env, *prefer, shutil.which('ffmpeg'), *fallback):
        if _exists(c):
            return str(c)
    return None


def find_ffmpeg(prefer=(), fallback=()):
    """ffmpeg の実行ファイルを探す。

    順序: 環境変数 FFMPEG → prefer → PATH → fallback。
    prefer はリポジトリ同梱の ffmpeg など「PATH より優先したい場所」、
    fallback は「他に無いときだけ使う場所」。見つからなければ FFmpegNotFound。
    探索結果は環境変数と引数の組み合わせでキャッシュする。
    """
    # リストが渡されてもキャッシュできるようタプルに正規化する。
    got = _find_ffmpeg(os.environ.get('FFMPEG'), os.environ.get('PATH', ''),
                       tuple(prefer), tuple(fallback))
    if got is None:
        raise FFmpegNotFound('ffmpeg が見つからない。PATH か環境変数 FFMPEG で指定する')
    return got


@functools.lru_cache(maxsize=64)
def _find_ffprobe(env, path, ffmpeg, prefer):
    cands = [env]
    if ffmpeg:
        p = Path(ffmpeg)
        cands.append(p.with_name('ffprobe' + p.suffix))
    cands.extend(prefer)
    cands.append(shutil.which('ffprobe'))
    for c in cands:
        if _exists(c):
            return str(c)
    return None


def find_ffprobe(ffmpeg=None, prefer=(), default=None):
    """ffprobe を探す。

    順序: 環境変数 FFPROBE → ffmpeg と同じフォルダ → prefer → PATH → default。
    見つからないとき default をそのまま返す（None なら None）。
    """
    return _find_ffprobe(os.environ.get('FFPROBE'), os.environ.get('PATH', ''),
                         ffmpeg, tuple(prefer)) or default


def clear_cache():
    """テストなどで PATH / FFMPEG / FFPROBE や shutil.which を差し替えた後に呼ぶ。"""
    _find_ffmpeg.cache_clear()
    _find_ffprobe.cache_clear()


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
