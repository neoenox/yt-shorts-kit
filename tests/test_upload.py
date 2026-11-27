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


class _Element:
    def __init__(self, label, calls, *, checked=False, kind=''):
        self.label = label
        self.calls = calls
        self.checked = checked
        self.kind = kind

    def is_visible(self):
        return True

    def inner_text(self):
        return self.label

    def get_attribute(self, name):
        if name == 'aria-checked':
            return 'true' if self.checked else 'false'
        if name == 'accept':
            return 'image/*' if self.kind == 'image' else 'video/*'
        return None

    def click(self, **kwargs):
        self.calls.append(('click', self.label))
        if getattr(self, 'on_click', None):
            self.on_click(self)

    def set_input_files(self, path):
        self.calls.append(('file', path))


class _Locator:
    def __init__(self, items, calls):
        self.items = items
        self.calls = calls

    def count(self):
        return len(self.items)

    def nth(self, i):
        return self.items[i]

    @property
    def first(self):
        return self.items[0]

    def all(self):
        return list(self.items)


def _upload_page(radio_specs, visibility=None, *, save_ok=True):
    """upload() の保存画面を模した page。radio_specs は (label, checked, toggles)。"""
    calls = []
    radios = []
    for label, checked, toggles in radio_specs:
        r = _Element(label, calls, checked=checked)
        if toggles:
            r.on_click = lambda e: setattr(e, 'checked', True)
        radios.append(r)
    page = SimpleNamespace(
        calls=calls,
        url='https://studio.youtube.com/channel/UC123/videos/upload',
    )
    upload_button = _Element('#upload-button', calls)
    video_input = _Element('video-input', calls, kind='video')
    title_box = _Element('#title-textarea #textbox', calls)
    desc_box = _Element('ytcp-video-description #textbox', calls)
    next_button = _Element('#next-button', calls)
    save_button = _Element('#save-button', calls)
    vis = _Element('#visibility-text', calls)

    def goto(url, **kwargs):
        calls.append(('goto', url))
        page.url = url

    def locator(selector):
        table = {
            '#upload-button': [upload_button],
            'input[type=file]': [video_input],
            '#title-textarea #textbox': [title_box],
            'ytcp-video-description #textbox': [desc_box],
            '#next-button': [next_button],
            '#save-button': [save_button],
            'tp-yt-paper-radio-button': radios,
        }
        if selector == '#visibility-text':
            if visibility is None:
                return _Locator([], calls)
            vis.label = visibility
            return _Locator([vis], calls)
        return _Locator(table.get(selector, []), calls)

    def get_by_text(label, exact=False):
        return _Locator([_Element(f'text:{label}', calls)], calls)

    page.goto = goto
    page.locator = locator
    page.get_by_text = get_by_text
    page.wait_for_timeout = lambda ms: None
    page.bring_to_front = lambda: None
    page.close = lambda: None
    return page, calls, save_ok


def _stub_upload_env(monkeypatch, page, calls, save_ok=True):
    monkeypatch.setattr(studio, '_ensure_chrome', lambda: None)
    monkeypatch.setattr(studio, '_body',
                        lambda pg: SimpleNamespace(inner_text=lambda: ''))
    monkeypatch.setattr(studio, '_set_field',
                        lambda pg, selector, value: calls.append(('set', selector)))
    monkeypatch.setattr(studio, '_video_id', lambda pg: 'abc12345678')

    def click_if_ready(pg, selector, label, limit=120):
        calls.append(('click_if_ready', selector))
        return selector != '#save-button' or save_ok

    monkeypatch.setattr(studio, '_click_if_ready', click_if_ready)
    connect = lambda *a, **k: SimpleNamespace(
        contexts=[SimpleNamespace(pages=[], new_page=lambda: page)])
    monkeypatch.setitem(sys.modules, 'playwright', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', _fake_playwright(connect))


def test_publish_false_without_private_radio_never_clicks_public(monkeypatch, tmp_path):
    page, calls, save_ok = _upload_page([('公開', False, True)], visibility='非公開')
    _stub_upload_env(monkeypatch, page, calls, save_ok)

    with pytest.raises(RuntimeError, match='非公開 のラジオが見つかりません'):
        studio.upload(load_pack(_pack(tmp_path)), channel_id='UC123')
    assert ('click', '公開') not in calls
    assert ('click_if_ready', '#save-button') not in calls


def test_unchecked_private_radio_blocks_save(monkeypatch, tmp_path):
    page, calls, save_ok = _upload_page([('非公開', False, False)], visibility='非公開')
    _stub_upload_env(monkeypatch, page, calls, save_ok)

    with pytest.raises(RuntimeError, match='非公開 を選択できませんでした'):
        studio.upload(load_pack(_pack(tmp_path)), channel_id='UC123')
    assert ('click', '非公開') in calls
    assert ('click_if_ready', '#save-button') not in calls


def test_save_failure_has_no_text_fallback(monkeypatch, tmp_path):
    page, calls, save_ok = _upload_page(
        [('非公開', True, False)], visibility='非公開', save_ok=False)
    _stub_upload_env(monkeypatch, page, calls, save_ok)

    with pytest.raises(RuntimeError, match='保存ボタン'):
        studio.upload(load_pack(_pack(tmp_path)), channel_id='UC123')
    assert not [c for c in calls if str(c[1]).startswith('text:')]


def test_verified_privacy_reports_checked_summary(monkeypatch, tmp_path):
    page, calls, save_ok = _upload_page([('非公開', True, False)], visibility='非公開')
    _stub_upload_env(monkeypatch, page, calls, save_ok)

    result = studio.upload(load_pack(_pack(tmp_path)), channel_id='UC123')
    assert result['saved'] is True
    assert result['privacy_check'] == 'verified'
    assert ('goto', 'https://studio.youtube.com/video/abc12345678/edit') in calls


def test_missing_visibility_summary_does_not_fail_save(monkeypatch, tmp_path):
    page, calls, save_ok = _upload_page([('非公開', True, False)], visibility=None)
    _stub_upload_env(monkeypatch, page, calls, save_ok)

    result = studio.upload(load_pack(_pack(tmp_path)), channel_id='UC123')
    assert result['saved'] is True
    assert result['privacy_check'] == 'unverified'


def test_visibility_mismatch_fails_with_video_id(monkeypatch, tmp_path):
    page, calls, save_ok = _upload_page([('非公開', True, False)], visibility='公開')
    _stub_upload_env(monkeypatch, page, calls, save_ok)

    with pytest.raises(RuntimeError, match=r'公開設定が 非公開 ではありません.*abc12345678'):
        studio.upload(load_pack(_pack(tmp_path)), channel_id='UC123')
