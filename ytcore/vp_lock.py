"""Process-safe per-slug locks and active-render counting.

Lock files intentionally remain on disk: unlinking a lock path while another
process may acquire it creates an inode race. The OS lock, not the PID text,
controls ownership; the PID/command text is diagnostic metadata only.
"""
import atexit
import ctypes
import os
import time
from pathlib import Path

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


def alive(pid):
    """PID が生きているか。Windows は OpenProcess、それ以外は kill(pid, 0) で調べる。"""
    if pid <= 0:
        return False
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259


def _read(path):
    try:
        pid, _, cmd = Path(path).read_text(encoding='utf8').partition(' ')
        return int(pid), cmd.strip()
    except Exception:
        return 0, ''


def _try_lock(fd):
    """Try a nonblocking exclusive OS lock on byte 0; return whether acquired."""
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        if os.name == 'nt':
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_fd(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == 'nt':
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _ensure_lock_byte(fd):
    if os.name == 'nt' and os.fstat(fd).st_size == 0:
        os.write(fd, b'\\0')
        os.lseek(fd, 0, os.SEEK_SET)


def acquire(root, slug, cmd):
    """Acquire a per-slug OS lock. Lock files are not deleted on release."""
    d = Path(root) / 'cache'
    d.mkdir(exist_ok=True)
    f = d / f'{slug}.lock'
    fd = os.open(f, os.O_RDWR | os.O_CREAT, 0o644)
    _ensure_lock_byte(fd)
    if not _try_lock(fd):
        pid, c = _read(f)
        os.close(fd)
        info = f'PID {pid}: {c}' if pid else 'holder metadata unavailable'
        raise SystemExit(
            f'[lock] {slug} は、すでに動いています（{info}）。'
            '二重に起動しません。終わるのを待つか、そのプロセスを止めてください。'
        )

    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f'{os.getpid()} {cmd} {time.strftime("%H:%M:%S")}'.encode('utf8'))
    os.fsync(fd)

    def release():
        try:
            _unlock_fd(fd)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    atexit.register(release)
    return f


def others(root, slug):
    """Count other slugs whose OS locks are currently held by active jobs."""
    n = 0
    for f in (Path(root) / 'cache').glob('*.lock'):
        if f.stem == slug:
            continue
        try:
            fd = os.open(f, os.O_RDWR)
        except OSError:
            continue
        _ensure_lock_byte(fd)
        if _try_lock(fd):
            _unlock_fd(fd)
            os.close(fd)
            continue
        pid, c = _read(f)
        os.close(fd)
        if pid and c.split(' ')[0] in ('build', 'audio', 'prep'):
            n += 1
    return n


def share_maxpar(root, slug, base=8):
    """Share parallelism across active renders to limit simultaneous NVENC sessions."""
    return max(1, base // (others(root, slug) + 1))
