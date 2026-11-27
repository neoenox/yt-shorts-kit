"""Playwright で ChatGPT / Google AI に台本を送り、返答を取る。

Chrome は CDP 経由で接続する。ポートとプロファイルは環境変数で受ける。
    REVIEW_CDP_PORT  既定 9223
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
    'AI モードの回答が作成されました',
)


_port_cache = None


def _free_port():
    """OS に空きポートを聞く。候補数に上限は無い。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _port():
    """明示指定があればそれを使う。なければ空きポートを OS から取得して固定する。"""
    global _port_cache
    if _port_cache is None:
        explicit = os.environ.get('REVIEW_CDP_PORT')
        _port_cache = int(explicit) if explicit else _free_port()
    return _port_cache


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


def _wait_enabled_send(pg, selector, limit=240):
    end = time.time() + limit
    locator = pg.locator(selector)
    while time.time() < end:
        for i in range(locator.count()):
            btn = locator.nth(i)
            if btn.is_visible() and btn.get_attribute('disabled') is None:
                return btn
        pg.wait_for_timeout(2000)
    raise TimeoutError('送信ボタンが有効にならない')


def _body(pg):
    """ページ本体。bsk のオーバーレイ内の body は除く。"""
    target = pg.locator('main').first
    if not target.count():
        target = pg.locator('body:not(browser-skill-overlay body)').first
    return target


def _google_answer(pg, timeout):
    """返答本文が3回連続で変わるまで待つ（既定の途中経由を拾わない）。"""
    mark = 'に対する AI モードの回答'
    target = _body(pg)
    end = time.time() + timeout
    last = ''
    while time.time() < end:
        pg.wait_for_timeout(3000)
        body = target.inner_text()
        i = body.rfind(mark)
        answer = body[i + len(mark):].strip() if i >= 0 else ''
        done = 'AI モードの回答が作成されました' in body
        if len(answer) > 20 and done:
            for ui in TRAILING_UI:
                answer = answer.replace(ui, '').strip()
            return answer
        last = answer
    return last


def _chatgpt_answer(pg, before, timeout):
    """送信前の本文との差分から返答を取り出す。

    ChatGPT の DOM は日々変わるので、特定の role 属性に依存しない。
    """
    end = time.time() + timeout
    last = ''
    stable = 0
    main = _body(pg)
    while time.time() < end:
        pg.wait_for_timeout(3000)
        text = main.inner_text()
        answer = text[len(before):].strip() if text.startswith(before) else text.strip()
        i = answer.rfind('あなたの発言:')
        if i >= 0:
            answer = answer[i + len('あなたの発言:'):].strip()
        if answer and answer == last:
            stable += 1
        else:
            stable, last = 0, answer
        if stable >= 2 and len(last) > 80:
            return last
    return last


def _attach_video(pg, path):
    """Google AI に動画を添付する。既存の honnoji 実装と同じ手順。"""
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f'動画が無い: {p}')
    pg.locator('button[aria-label="ファイルとツールを追加し、モデルを選択します"]').first.click()
    pg.wait_for_timeout(1500)
    inputs = pg.locator('input[type=file]')
    target = None
    for i in range(inputs.count()):
        inp = inputs.nth(i)
        accept = inp.get_attribute('accept') or ''
        if not accept:
            target = inp
            break
    if target is None:
        target = inputs.last
    target.set_input_files(str(p))
    pg.wait_for_timeout(10000)


def submit(script, target, prompt, dry_run=False, timeout=180, video=None):
    """prompt を target に送り、返答本文を返す。dry_run なら prompt をそのまま返す。

    video を渡すと Google AI に動画を添付してから送る。
    """
    if target not in TARGETS:
        raise ValueError(f'未知の target: {target}')
    if dry_run:
        return prompt
    if video and target != 'google':
        raise ValueError('動画添付は google のみ対応')
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
            if video:
                _attach_video(pg, video)
            composer = pg.locator(cfg['composer']).first
            composer.fill(prompt)
            pg.wait_for_timeout(1000)
            before = ''
            if target == 'chatgpt':
                before = _body(pg).inner_text()
            _wait_enabled_send(pg, cfg['send']).click()
            if target == 'google':
                return _google_answer(pg, timeout)
            return _chatgpt_answer(pg, before, timeout)
        finally:
            pg.close()


def close_review_tabs():
    """レビュー用 Chrome の ChatGPT / Google AI タブを全部閉じる。

    親プロセスが、すべてのレビューの完了後に1回だけ呼ぶ。
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(_cdp())
        _close_review_tabs(browser)


def _close_review_tabs(browser):
    """レビュー完了後に、ChatGPT / Google AI のタブを全部閉じる。

    レビュー用プロファイル内の対象タブだけを閉じ、ほかのタブは残す。
    """
    for context in browser.contexts:
        for page in list(context.pages):
            url = page.url
            if 'chatgpt.com' in url or 'google.com/ai' in url:
                try:
                    page.close()
                except Exception:
                    pass


def submit_video(video, prompt, dry_run=False, timeout=300):
    """完成動画を Google AI に送る。"""
    return submit({}, 'google', prompt, dry_run=dry_run,
                  timeout=timeout, video=video)
