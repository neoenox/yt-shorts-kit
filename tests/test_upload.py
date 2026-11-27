"""ytkit.upload の回帰テスト。ブラウザは触らない。"""
import json
import sys
from types import SimpleNamespace

import pytest

from ytkit.upload import load_pack
from ytkit.upload import __main__ as cli
from ytkit.upload import studio


def _pack(tmp_path, *, title='タイトル', description='説明文' * 10, video=True, thumb=False, subs=False):
    d = tmp_path / 'pack'
    d.mkdir(exist_ok=True)
    if video:
        (d / 'video.mp4').write_bytes(b'fake video')
    (d / 'title.txt').write_text(title, encoding='utf8')
    (d / 'description.txt').write_text(description, encoding='utf8')
    if thumb:
        (d / 'thumbnail.jpg').write_bytes(b'fake image')
    if subs:
        (d / 'subtitles.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n文\n', encoding='utf8')
    return d


def _fake_playwright(connect):
    class PW:
        chromium = SimpleNamespace(connect_over_cdp=connect)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return SimpleNamespace(sync_playwright=lambda: PW())


def test_load_pack(tmp_path):
    d = _pack(tmp_path, thumb=True, subs=True)
    got = load_pack(d)
    assert got['title_text'] == 'タイトル'
    assert len(got['description_text']) >= 20
    assert got['video'].name == 'video.mp4'
    assert got['thumbnail'].name == 'thumbnail.jpg'
    assert got['subtitles'].name == 'subtitles.srt'


def test_load_pack_missing_required(tmp_path):
    d = _pack(tmp_path)
    (d / 'title.txt').unlink()
    with pytest.raises(FileNotFoundError, match='title.txt'):
        load_pack(d)


def test_load_pack_empty_title(tmp_path):
    d = _pack(tmp_path, title='')
    with pytest.raises(ValueError, match='title.txt'):
        load_pack(d)


def test_dry_run_does_not_open_browser(tmp_path, capsys):
    d = _pack(tmp_path)
    rc = cli.main(['run', str(d), '--slug', 'x', '--dry-run'])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data['title'] == 'タイトル'
    assert data['publish'] is False


def test_check_command(tmp_path, capsys):
    d = _pack(tmp_path, thumb=True)
    rc = cli.main(['check', str(d)])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data['thumbnail'] is True
    assert data['subtitles'] is False


def test_upload_url_includes_channel_id():
    url = studio.upload_url('UC123')
    assert 'channel/UC123/videos/upload' in url


def test_upload_port_auto_assigned(monkeypatch):
    monkeypatch.delenv('UPLOAD_CDP_PORT', raising=False)
    monkeypatch.setattr(studio, '_port_cache', None)
    port = studio._port()
    assert 1024 < port < 65536
    assert studio._port() == port


def test_upload_port_explicit(monkeypatch):
    monkeypatch.setenv('UPLOAD_CDP_PORT', '9444')
    monkeypatch.setattr(studio, '_port_cache', None)
    assert studio._port() == 9444


def test_upload_url_requires_channel_id(monkeypatch):
    monkeypatch.delenv('UPLOAD_CHANNEL_ID', raising=False)
    with pytest.raises(ValueError, match='UPLOAD_CHANNEL_ID'):
        studio.upload_url()


def test_upload_url_from_env(monkeypatch):
    monkeypatch.setenv('UPLOAD_CHANNEL_ID', 'UCenv')
    assert 'channel/UCenv/videos/upload' in studio.upload_url()


def test_video_id_from_url():
    assert studio._video_id_from_url(
        'https://studio.youtube.com/video/abc12345678/edit') == 'abc12345678'
    assert studio._video_id_from_url('https://studio.youtube.com/videos') is None


def test_upload_captions_attaches_and_publishes_srt(tmp_path):
    calls = []

    class Button:
        def __init__(self, name):
            self.name = name

        def click(self, **kwargs):
            calls.append(('click', self.name))

    class Chooser:
        value = type('Value', (), {'set_files': lambda self, p: calls.append(('file', p))})()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Page:
        url = 'https://studio.youtube.com/videos'

        def goto(self, url, **kwargs):
            calls.append(('goto', url))

        def wait_for_timeout(self, ms):
            pass

        def get_by_role(self, role, name, **kwargs):
            assert role == 'button'
            return Button(name)

        def expect_file_chooser(self, **kwargs):
            return Chooser()

    srt = tmp_path / 'subtitles.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n文\n', encoding='utf8')
    studio._upload_captions(Page(), 'abc12345678', srt)
    assert ('goto', 'https://studio.youtube.com/video/abc12345678/translations') in calls
    assert ('file', str(srt)) in calls
    names = [c[1] for c in calls if c[0] == 'click']
    assert names == ['手動でアップロード', '続行', '字幕を編集', '公開']


def test_stop_owned_chrome_targets_only_own_pid(monkeypatch):
    calls = []
    monkeypatch.setattr(studio, '_chrome_proc', SimpleNamespace(pid=4242))
    monkeypatch.setattr(studio, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(studio, 'subprocess',
                        SimpleNamespace(run=lambda args, **kw: calls.append(args)))

    assert studio._stop_owned_chrome() is True
    assert calls == [['taskkill', '/F', '/T', '/PID', '4242']]
    assert studio._chrome_proc is None


def test_cdp_failure_without_owned_chrome_keeps_existing_browser(monkeypatch, tmp_path):
    started = []

    def connect(*args, **kwargs):
        raise ConnectionError('no cdp')

    monkeypatch.setattr(studio, '_chrome_proc', None)
    monkeypatch.setattr(studio, '_ensure_chrome', lambda: started.append('chrome'))
    monkeypatch.setitem(sys.modules, 'playwright', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', _fake_playwright(connect))

    with pytest.raises(RuntimeError, match='既存の Chrome は停止しません'):
        studio.upload(_pack(tmp_path), channel_id='UC123')
    assert started == ['chrome']  # 最初の起動のみ。既存 Chrome は再起動しない


def test_cdp_failure_restarts_only_owned_chrome(monkeypatch, tmp_path):
    attempts = []
    started = []
    stopped = []

    class StopTest(Exception):
        pass

    def connect(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError('no cdp')
        raise StopTest

    monkeypatch.setattr(studio, '_chrome_proc', object())
    monkeypatch.setattr(studio, '_stop_owned_chrome',
                        lambda: stopped.append('stop') or True)
    monkeypatch.setattr(studio, '_ensure_chrome', lambda: started.append('chrome'))
    monkeypatch.setattr(studio.time, 'sleep', lambda _: None)
    monkeypatch.setitem(sys.modules, 'playwright', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', _fake_playwright(connect))

    with pytest.raises(StopTest):
        studio.upload(_pack(tmp_path), channel_id='UC123')
    assert len(attempts) == 2
    assert len(started) == 2
    assert stopped == ['stop']
