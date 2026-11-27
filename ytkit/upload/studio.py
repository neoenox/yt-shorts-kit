"""YouTube Studio に動画をアップロードして非公開で保存する。

公開は publish=True のときだけ。既定は非公開。
"""
import os
import re
import socket
import subprocess
import time
from pathlib import Path

STUDIO_URL = 'https://studio.youtube.com/'


def upload_url(channel_id=None):
    """channel ID を入れたアップロード URL を返す。

    ID 無しの /videos/upload は「エラーが発生しました」になることがあるため、
    チャンネル固有の ID は引数か UPLOAD_CHANNEL_ID で必ず渡す。
    """
    cid = channel_id or os.environ.get('UPLOAD_CHANNEL_ID')
    if not cid:
        raise ValueError('--channel-id か UPLOAD_CHANNEL_ID を指定してください')
    return f'{STUDIO_URL}channel/{cid}/videos/upload'

LIMIT_MARKERS = ('1 日のアップロード数の上限', 'アップロード数の上限に達しました')

_port_cache = None
_chrome_proc = None


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _port():
    global _port_cache
    if _port_cache is None:
        explicit = os.environ.get('UPLOAD_CDP_PORT')
        _port_cache = int(explicit) if explicit else _free_port()
    return _port_cache


def _cdp():
    return f'http://127.0.0.1:{_port()}'


def _ensure_chrome():
    global _chrome_proc
    try:
        socket.create_connection(('127.0.0.1', _port()), 1).close()
        return
    except OSError:
        pass
    exe = os.environ.get('CHROME_PATH',
                         r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    profile = os.environ.get('UPLOAD_PROFILE',
                             r'C:\Users\neoen\.chrome-gemienox')
    if not Path(exe).exists():
        raise FileNotFoundError(f'Chrome が無い: {exe}')
    args = [exe, f'--remote-debugging-port={_port()}',
            f'--user-data-dir={profile}', '--minimize']
    directory = os.environ.get('UPLOAD_PROFILE_DIR', 'Profile 3')
    if directory:
        args.append(f'--profile-directory={directory}')
    args.append(STUDIO_URL)
    _chrome_proc = subprocess.Popen(args)


def _stop_owned_chrome():
    """このプロセスが起動した Chrome だけを止める。既存の Chrome は触らない。"""
    global _chrome_proc
    proc = _chrome_proc
    _chrome_proc = None
    if proc is None:
        return False
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                       capture_output=True)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return True


def _body(pg):
    target = pg.locator('main').first
    if not target.count():
        target = pg.locator('body:not(browser-skill-overlay body)').first
    return target


def _click_if_ready(pg, selector, label, limit=120):
    end = time.time() + limit
    loc = pg.locator(selector)
    while time.time() < end:
        for i in range(loc.count()):
            b = loc.nth(i)
            if b.is_visible() and b.get_attribute('disabled') is None:
                b.click()
                return True
        pg.wait_for_timeout(2000)
    print(f'  {label} が押せませんでした')
    return False


def _set_field(pg, selector, value):
    """実キー入力で値を入れる（Studio の Polymer 状態に反映させるため）。"""
    field = pg.locator(selector).first
    field.click()
    pg.keyboard.press('Control+a')
    pg.keyboard.insert_text(value)
    pg.wait_for_timeout(1000)


def _video_id_from_url(url):
    m = re.search(r'/video/([\w-]{11})(?:[/?]|$)', url or '')
    return m.group(1) if m else None


def _video_id(pg):
    found = _video_id_from_url(pg.url)
    if found:
        return found
    for link in pg.locator('a[href*="/video/"], a[href*="watch?v="]').all():
        found = _video_id_from_url(link.get_attribute('href') or '')
        if found:
            return found
    return None


def _upload_captions(pg, video_id, srt):
    """保存した動画に日本語字幕を添付して公開する（既存の Studio 操作と同じ手順）。"""
    pg.goto(f'{STUDIO_URL}video/{video_id}/translations', wait_until='domcontentloaded')
    pg.wait_for_timeout(6000)
    pg.get_by_role('button', name='手動でアップロード').click(timeout=20000)
    pg.wait_for_timeout(1500)
    with pg.expect_file_chooser(timeout=20000) as chooser:
        pg.get_by_role('button', name='続行').click()
    chooser.value.set_files(str(srt))
    pg.wait_for_timeout(6000)
    pg.get_by_role('button', name='字幕を編集').click(timeout=30000)
    pg.wait_for_timeout(4000)
    pg.get_by_role('button', name='公開', exact=True).click(timeout=20000)
    pg.wait_for_timeout(4000)
    print(f'  字幕を公開しました: {srt.name}')


def _privacy_checked(pg, target):
    """公開設定ラジオの状態。見つからなければ None（保存前の必須チェックで使う）。"""
    rads = pg.locator('tp-yt-paper-radio-button')
    for i in range(rads.count()):
        r = rads.nth(i)
        if r.is_visible() and r.inner_text().strip() == target:
            return r.get_attribute('aria-checked') == 'true'
    return None


def _select_privacy(pg, target):
    """保存前に target を選ぶ。見つからない／選べなければ保存しない。"""
    checked = _privacy_checked(pg, target)
    if checked is None:
        raise RuntimeError(f'{target} のラジオが見つかりません。保存しません')
    if not checked:
        rads = pg.locator('tp-yt-paper-radio-button')
        for i in range(rads.count()):
            r = rads.nth(i)
            if r.is_visible() and r.inner_text().strip() == target:
                r.click()
                break
        pg.wait_for_timeout(3000)
    if _privacy_checked(pg, target) is not True:
        raise RuntimeError(f'{target} を選択できませんでした。保存しません')
    print(f'  公開設定: {target}')


def _verify_privacy(pg, target):
    """保存後の公開範囲を #visibility-text で best-effort に確認する。"""
    loc = pg.locator('#visibility-text')
    if not loc.count():
        return 'unverified'
    try:
        text = loc.first.inner_text().strip()
    except Exception:
        return 'unverified'
    return 'verified' if target in text else 'mismatch'


def upload(pack, slug='video', publish=False, dry_run=False, timeout=600,
           channel_id=None):
    """pack を YouTube Studio にアップロードして保存する。"""
    if dry_run:
        return {'slug': slug, 'title': pack['title_text'],
                'video': str(pack['video']), 'publish': publish}
    _ensure_chrome()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(_cdp(), timeout=15000)
        except Exception as exc:
            if not _stop_owned_chrome():
                raise RuntimeError(
                    f'CDP({_cdp()}) に接続できません。既存の Chrome は停止しません。'
                    'UPLOAD_CDP_PORT / UPLOAD_PROFILE を確認してください'
                ) from exc
            time.sleep(4)
            _ensure_chrome()
            browser = p.chromium.connect_over_cdp(_cdp(), timeout=30000)
        for old in list(browser.contexts[0].pages):
            if 'studio.youtube.com' in old.url:
                old.close()
        pg = browser.contexts[0].new_page()
        try:
            pg.goto(upload_url(channel_id), wait_until='domcontentloaded')
            pg.wait_for_timeout(8000)
            pg.bring_to_front()

            if any(m in _body(pg).inner_text() for m in LIMIT_MARKERS):
                raise RuntimeError('1日のアップロード上限に達しています')

            pg.locator('#upload-button').first.click()
            pg.wait_for_timeout(3000)
            inputs = pg.locator('input[type=file]')
            video_input = None
            for i in range(inputs.count()):
                inp = inputs.nth(i)
                if 'image' not in (inp.get_attribute('accept') or ''):
                    video_input = inp
                    break
            if video_input is None:
                raise RuntimeError('動画用のファイル入力欄が見つかりません')
            video_input.set_input_files(str(pack['video']))
            print('  動画を設定しました')

            end_field = time.time() + min(timeout, 180)
            while time.time() < end_field:
                if pg.locator('#title-textarea #textbox').count():
                    break
                pg.wait_for_timeout(2000)
            else:
                raise TimeoutError('タイトル入力欄が出ませんでした')
            _set_field(pg, '#title-textarea #textbox', pack['title_text'])
            _set_field(pg, 'ytcp-video-description #textbox', pack['description_text'])
            print('  タイトルと説明を設定しました')

            if 'thumbnail' in pack:
                inputs = pg.locator('input[type=file]')
                for i in range(inputs.count()):
                    inp = inputs.nth(i)
                    if 'image' in (inp.get_attribute('accept') or ''):
                        inp.set_input_files(str(pack['thumbnail']))
                        print('  サムネイルを設定しました')
                        break


            for m in LIMIT_MARKERS:
                if m in _body(pg).inner_text():
                    raise RuntimeError('1日のアップロード上限に達しています')

            end = time.time() + timeout
            while time.time() < end:
                text = _body(pg).inner_text()
                busy = any(x in text for x in (
                    '動画をアップロードしています', 'まもなく処理が始まります',
                    '動画を処理しています', 'チェック中', '処理しています',
                ))
                ready = pg.locator('#next-button').count() and not busy
                if ready:
                    break
                pg.wait_for_timeout(3000)
            else:
                raise TimeoutError('アップロード処理が終わりませんでした')

            _click_if_ready(pg, '#next-button', '次へ(詳細)')
            pg.wait_for_timeout(5000)

            # 子ども向け: いいえ
            radios = pg.locator('tp-yt-paper-radio-button')
            for i in range(radios.count()):
                r = radios.nth(i)
                if r.is_visible() and 'いいえ、子ども向けではありません' in r.inner_text():
                    if r.get_attribute('aria-checked') != 'true':
                        r.click()
                    break

            for _ in range(5):
                if '限定公開' in _body(pg).inner_text():
                    break
                _click_if_ready(pg, '#next-button', '次へ(公開設定)', limit=30)
                pg.wait_for_timeout(4000)

            target = '公開' if publish else '非公開'
            _select_privacy(pg, target)

            if not _click_if_ready(pg, '#save-button', '保存', limit=60):
                raise RuntimeError('保存ボタン(#save-button)が押せませんでした。公開設定を変更せず中断します')
            pg.wait_for_timeout(8000)
            video_id = _video_id(pg)
            if not video_id:
                raise RuntimeError('保存後に動画 ID が取得できませんでした。saved=True を返しません')
            pg.goto(f'{STUDIO_URL}video/{video_id}/edit', wait_until='domcontentloaded')
            pg.wait_for_timeout(3000)
            privacy_check = _verify_privacy(pg, target)
            if privacy_check == 'mismatch':
                raise RuntimeError(
                    f'保存後の公開設定が {target} ではありません（video_id={video_id}）。'
                    'Studio で公開設定を確認してください'
                )
            result = {'slug': slug, 'saved': True, 'publish': publish,
                      'video_id': video_id, 'privacy_check': privacy_check}
            if 'subtitles' in pack:
                _upload_captions(pg, video_id, pack['subtitles'])
                result['subtitles'] = 'published'
            return result
        finally:
            pg.close()
