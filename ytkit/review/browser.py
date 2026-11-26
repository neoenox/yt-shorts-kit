"""Playwright で ChatGPT / Google AI に台本を送り、返答を取る。

Chrome は CDP 経由で接続する。ポートとプロファイルは環境変数で受ける。
    REVIEW_CDP_PORT  既定 9222
    REVIEW_PROFILE   既定 C:\\Users\\neoen\\.chrome-automation
    CHROME_PATH      既定 C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe
"""
import os
import socket
import subprocess
import time
from pathlib import Path

TARGETS = {
    'chatgpt': {
        'url': 'https://chatgpt.com/',
        'composer': 'div.ProseMirror[contenteditable="true"], #prompt-textarea',
        'send': 'button[data-testid="send-button"], button[aria-label*="送信"], button[aria-label*="Send"]',
        'reply': 'div[data-message-author-role="assistant"]',
        'busy': 'button[data-testid="stop-button"], button[aria-label*="停止"]',
    },
    'google': {
        'url': 'https://www.google.com/ai/',
        'composer': '[aria-label="質問する"]',
        'send': 'button[aria-label="送信"]',
        'reply': 'body',
        'busy': '',
    },
}

TRAILING_UI = (
    'AI モードが質問について考えています',
    'AI モードが回答を生成しています',
    'AI は不正確な情報を表示することがあるため',
    'パーソナライズなしで試す',
    'All items removed from input context.',
    '前のプロンプトにスキップする',
)


def _port():
    return int(os.environ.get('REVIEW_CDP_PORT', '9222'))


def _cdp():
    return f'http://127.0.0.1:{_port()}'


def _ensure_chrome(url):
    try:
        socket.create_connection(('127.0.0.1', _port()), 1).close()
        return
    except OSError:
        pass
    exe = os.environ.get(
        'CHROME_PATH',
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    )
    profile = os.environ.get(
        'REVIEW_PROFILE',
        r'C:\Users\neoen\.chrome-automation',
    )
    if not Path(exe).exists():
        raise FileNotFoundError(f'Chrome が無い: {exe}')
    subprocess.Popen([
        exe,
        f'--remote-debugging-port={_port()}',
        f'--user-data-dir={profile}',
        '--minimize',
        url,
    ])


def _wait_enabled_send(pg, selector, limit=90):
    end = time.time() + limit
    locator = pg.locator(selector)
    while time.time() < end:
        for i in range(locator.count()):
            btn = locator.nth(i)
            if btn.is_visible() and btn.get_attribute('disabled') is None:
                return btn
        pg.wait_for_timeout(2000)
    raise TimeoutError('送信ボタンが有効にならない')


def _google_answer(pg, timeout):
    """返答本文が3回連続で変わるまで待つ（既定の途中経由を拾わない）。"""
    mark = 'に対する AI モードの回答'
    last = ''
    stable = 0
    body = ''
    end = time.time() + timeout
    while time.time() < end:
        pg.wait_for_timeout(4000)
        body = pg.locator('body').first.inner_text()
        i = body.rfind(mark)
        answer = body[i + len(mark):].strip() if i >= 0 else ''
        if answer and len(answer) > 150 and not any(x in answer for x in TRAILING_UI):
            if answer == last:
                stable += 1
            else:
                stable, last = 0, answer
            if stable >= 3:
                return last
    return last or body


def _chatgpt_answer(pg, selector, timeout):
    end = time.time() + timeout
    last = ''
    stable = 0
    locator = pg.locator(selector)
    while time.time() < end:
        pg.wait_for_timeout(3000)
        n = locator.count()
        if not n:
            continue
        text = locator.nth(n - 1).inner_text().strip()
        if text and text == last:
            stable += 1
        else:
            stable, last = 0, text
        if stable >= 2 and len(last) > 80:
            return last
    return last


def submit(script, target, prompt, dry_run=False, timeout=180):
    """prompt を target に送り、返答本文を返す。dry_run なら prompt をそのまま返す。"""
    if target not in TARGETS:
        raise ValueError(f'未知の target: {target}')
    if dry_run:
        return prompt
    cfg = TARGETS[target]
    _ensure_chrome(cfg['url'])
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(_cdp())
        pg = browser.contexts[0].new_page()
        try:
            pg.goto(cfg['url'], wait_until='domcontentloaded')
            pg.wait_for_timeout(8000)
            pg.bring_to_front()
            composer = pg.locator(cfg['composer']).first
            composer.fill(prompt)
            pg.wait_for_timeout(1000)
            _wait_enabled_send(pg, cfg['send']).click()
            if target == 'google':
                return _google_answer(pg, timeout)
            return _chatgpt_answer(pg, cfg['reply'], timeout)
        finally:
            pg.close()
