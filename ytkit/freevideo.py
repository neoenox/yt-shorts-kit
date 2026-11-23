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


# 生成コストのプロファイル。テロップの背後など、細部が見えない背景向け。
# fast / fastest は refine パスを丸ごと省き、ステップ数とアップスケールも下げる。
QUALITY = {
    'balanced': dict(two_pass=True, base_steps=8, refine_steps=1, upscale_factor='2'),
    'fast': dict(two_pass=False, base_steps=6),
    'fastest': dict(two_pass=False, base_steps=4),
}


def graph(text, width, height, seconds, seed=None, quality='balanced', **overrides):
    """FreeVideoGenerate + FreeVideoMedia の2ノード。

    quality:
      balanced … two_pass 8+1 ステップ、2倍アップスケール。
      fast     … 一パス 6 ステップ（refine とアップスケールなし）。
      fastest  … 一パス 4 ステップ。

    同じプロンプト/seed/544x960/5秒で実測したサンプリング時間:
      balanced(refine=3) 207.4s / refine=2 192.9s (-7%) / refine=1 186.8s (-10%)。
    画質は refine=3 と 1 でほぼ差が無かったため、balanced は refine=1 を採用。
    運用では balanced のみを使用。fast / fastest は一パスの実験用として残している。
    two_pass を切ると base_steps だけの一パス生成になる（ノード側の仕様）。
    overrides で base_steps など個別の値を上書きできる（例: base_steps=5）。
    """
    try:
        profile = QUALITY[quality]
    except KeyError:
        raise ValueError(f'未知の quality: {quality}（{", ".join(QUALITY)}）') from None
    opts = {**profile, **overrides}
    inputs = dict(
        text=text, width=width, height=height, seconds=float(seconds),
        seed=seed if seed is not None else random.randint(1, 2 ** 48),
        force_regenerate=False, preview=False,
        refine_from='', continue_from='', frames=0,
        first_frame_reference=False, voice_reference=False, hide_tail=False,
        step_cache='none', allow_empty_prompt=False,
        media=['2', 0],
    )
    inputs.update(opts)
    if not inputs.get('two_pass'):
        # refine パスを使わないときは、ComfyUI に余計なノード引数を渡さない。
        inputs.pop('refine_steps', None)
    return {
        '1': {'class_type': 'FreeVideoGenerate', 'inputs': inputs},
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
