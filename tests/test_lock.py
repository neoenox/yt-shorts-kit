import os
import subprocess
import sys

from ytcore import vp_lock


PYTHON = sys.executable


def _child(script, *args):
    return subprocess.Popen(
        [PYTHON, '-c', script, *map(str, args)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def test_unlocked_stale_metadata_is_reused_without_unlink(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    lock = cache / 'stale.lock'
    lock.write_text('99999999 build stale', encoding='utf8')
    script = """
import sys, time
from ytcore.vp_lock import acquire
p=acquire(sys.argv[1], 'stale', 'build')
print('READY', flush=True)
time.sleep(0.5)
"""
    child = _child(script, tmp_path)
    try:
        assert child.stdout.readline().strip() == 'READY'
        assert lock.exists()
        pid, cmd = vp_lock._read(lock)
        assert pid == child.pid
        assert cmd.startswith('build')
    finally:
        child.terminate()
        child.wait(timeout=3)
    assert lock.exists(), 'lock file should persist to avoid unlink/inode races'


def test_two_processes_cannot_hold_same_slug_lock(tmp_path):
    barrier = tmp_path / 'go'
    script = """
import sys, time, os
from ytcore.vp_lock import acquire
while not os.path.exists(sys.argv[2]): time.sleep(0.005)
try:
 acquire(sys.argv[1], 'same', 'build')
 print('OK', flush=True)
 time.sleep(0.5)
except SystemExit:
 print('NO', flush=True)
"""
    a = _child(script, tmp_path, barrier)
    b = _child(script, tmp_path, barrier)
    try:
        barrier.touch()
        out_a = a.stdout.readline().strip()
        out_b = b.stdout.readline().strip()
        assert sorted([out_a, out_b]) == ['NO', 'OK']
    finally:
        for proc in (a, b):
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=3)


def test_others_counts_active_build_audio_prep(tmp_path):
    script = """
import sys, time
from ytcore.vp_lock import acquire
root=sys.argv[1]
for slug,cmd in [('one','build'),('two','audio'),('three','prep')]: acquire(root,slug,cmd)
print('READY', flush=True)
time.sleep(1.5)
"""
    child = _child(script, tmp_path)
    try:
        assert child.stdout.readline().strip() == 'READY'
        assert vp_lock.others(tmp_path, 'self') == 3
        assert vp_lock.share_maxpar(tmp_path, 'self', base=8) == 2
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_others_ignores_unlocked_stale_file(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'stale.lock').write_text('99999999 build stale', encoding='utf8')
    assert vp_lock.others(tmp_path, 'self') == 0
    assert (cache / 'stale.lock').exists()
