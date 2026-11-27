"""YouTube Studio の Ask Studio に質問し、返答を取る。

指定したアカウントの Chrome プロファイルに CDP で接続する。
    STUDIO_CDP_PORT      既定 9222
    STUDIO_PROFILE       既定 C:\\Users\\neoen\\.chrome-gemienox
    STUDIO_PROFILE_DIR   既定 'Profile 3'
    CHROME_PATH          既定 C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe
"""
import os
import socket
import subprocess
import time
from pathlib import Path

STUDIO_URL = 'https://studio.youtube.com/'
ASK_LABEL = 'Ask Studio'
COMPOSER = '.ytcpCreatorChatPromptInputPromptBox'
SEND = 'ytcp-icon-button[aria-label="送信"]'
DISCARD = 'AI は不正確な情報を表示することがあります'


def _port():
    return int(os.environ.get('STUDIO_CDP_PORT', '9222'))


def _cdp():
    return f'http://127.0.0.1:{_port()}'


def _open_chrome():
    try:
        socket.create_connection(('127.0.0.1', _port()), 1).close()
        return
    except OSError:
        pass
    exe = os.environ.get('CHROME_PATH',
                         r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    profile = os.environ.get('STUDIO_PROFILE',
                             r'C:\Users\neoen\.chrome-gemienox')
    if not Path(exe).exists():
        raise FileNotFoundError(f'Chrome が無い: {exe}')
    args = [exe, f'--remote-debugging-port={_port()}',
            f'--user-data-dir={profile}', '--minimize']
    directory = os.environ.get('STUDIO_PROFILE_DIR', 'Profile 3')
    if directory:
        args.append(f'--profile-directory={directory}')
    args.append(STUDIO_URL)
    subprocess.Popen(args)


def _body(pg):
    target = pg.locator('main').first
    if not target.count():
        target = pg.locator('body:not(browser-skill-overlay body)').first
    return target


def _open_panel(pg):
    """Ask Studio パネルを開き、入力欄が出るまで待つ。"""
    pg.bring_to_front()
    pg.wait_for_timeout(3000)
    composer = pg.locator(COMPOSER)
    if composer.count() and composer.first.is_visible():
        return
    header = pg.get_by_text(ASK_LABEL, exact=True)
    if header.count() and header.first.is_visible():
        header.first.click()
    else:
        pg.get_by_text(ASK_LABEL, exact=True).first.click()
    end = time.time() + 60
    while time.time() < end:
        if composer.count() and composer.first.is_visible():
            pg.wait_for_timeout(2000)
            return
        pg.wait_for_timeout(1000)
    raise TimeoutError('Ask Studio の入力欄が出ない')


def _wait_answer(pg, asked, timeout):
    """質問の後ろにある p 要素を返答として取り出す。"""
    end = time.time() + timeout
    while time.time() < end:
        pg.wait_for_timeout(4000)
        ps = pg.locator('p')
        texts = []
        for i in range(ps.count()):
            try:
                texts.append(ps.nth(i).inner_text().strip())
            except Exception:
                continue
        if asked not in texts:
            continue
        idx = texts.index(asked)
        parts = []
        for s in texts[idx + 1:]:
            if not s or s.startswith(DISCARD):
                break
            if s in ('リクエストを確認しています', 'エラーが発生しました。'):
                continue
            if s == asked:
                continue
            parts.append(s)
        if parts:
            return '\n'.join(parts)
    return ''


def ask(question, timeout=180, dry_run=False):
    """Ask Studio に質問して返答本文を返す。"""
    if not question or not question.strip():
        raise ValueError('質問が空です')
    if dry_run:
        return question
    _open_chrome()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(_cdp())
        studio_pages = [page for page in browser.contexts[0].pages
                        if 'studio.youtube.com' in page.url]
        pg = studio_pages[-1] if studio_pages else None
        created = False
        if pg is None:
            pg = browser.contexts[0].new_page()
            pg.goto(STUDIO_URL, wait_until='domcontentloaded')
            pg.wait_for_timeout(12000)
            created = True
        try:
            _open_panel(pg)
            composer = pg.locator(COMPOSER).first
            composer.fill(question)
            pg.wait_for_timeout(1000)
            send = pg.locator(SEND).first
            end = time.time() + 90
            while time.time() < end:
                if send.get_attribute('disabled') is None:
                    break
                pg.wait_for_timeout(2000)
            send.click()
            return _wait_answer(pg, question, timeout)
        finally:
            if created:
                pg.close()
