"""FreeVideo（ローカル ComfyUI）の HTTP API。画面操作はしない。

グラフは FreeVideo アプリ自身が実行したもの（/history の prompt）と同じ2ノード構成。
サーバーはランチャーの「Launch FreeVideo」で起動しておく（既定 http://127.0.0.1:8188）。
"""
import json
import os
import random
import time
import urllib.request
from pathlib import Path

DEFAULT_BASE = 'http://127.0.0.1:8188'
DEFAULT_OUTPUT_ROOT = Path(os.environ.get('FREEVIDEO_OUTPUT_ROOT', 'output'))


def _base(base):
    return base or os.environ.get('FREEVIDEO_URL') or DEFAULT_BASE


def _output_root(output_root):
    return Path(output_root or os.environ.get('FREEVIDEO_OUTPUT_ROOT') or DEFAULT_OUTPUT_ROOT)


def get(path, base=None, timeout=30):
    return json.loads(urllib.request.urlopen(_base(base) + path, timeout=timeout).read())


def post(path, body, base=None, timeout=60):
    req = urllib.request.Request(_base(base) + path, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(raw) if raw.strip() else {}


def graph(text, width, height, seconds, seed=None):
    """FreeVideoGenerate + FreeVideoMedia の2ノード（既定は two_pass・8+3 ステップ）。"""
    return {
        '1': {'class_type': 'FreeVideoGenerate', 'inputs': dict(
            text=text, width=width, height=height, seconds=float(seconds),
            seed=seed if seed is not None else random.randint(1, 2 ** 48),
            two_pass=True, base_steps=8, refine_steps=3,
            force_regenerate=False, preview=False,
            refine_from='', continue_from='', frames=0,
            first_frame_reference=False, voice_reference=False, hide_tail=False,
            step_cache='none', upscale_factor='2', allow_empty_prompt=False,
            media=['2', 0])},
        '2': {'class_type': 'FreeVideoMedia', 'inputs': {'assets': '[]', 'audio_use': 'reference'}},
    }


def queue_state(base=None):
    """(実行中の数, 待ちの数)"""
    q = get('/queue', base)
    return len(q['queue_running']), len(q['queue_pending'])


def wait(pid, base=None, limit=3600, poll=15):
    """完了まで待つ。(history の entry, status_str)。サーバーが落ちたら (None, 'server_down')。"""
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            h = get('/history/' + pid, base)
        except Exception:
            h = {}
        if pid in h:
            return h[pid], h[pid].get('status', {}).get('status_str')
        try:
            get('/queue', base)
        except Exception:
            return None, 'server_down'
        time.sleep(poll)
    return None, 'timeout'


def video_of(entry, output_root=None):
    """完了した entry から出力 mp4 のパスを返す。無ければ None。"""
    root = _output_root(output_root)
    for node in entry.get('outputs', {}).values():
        for item in node.get('images', []):
            if str(item.get('filename', '')).endswith('.mp4'):
                return root / item.get('subfolder', '') / item['filename']
    return None
