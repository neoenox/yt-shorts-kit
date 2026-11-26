"""ytkit.review の回帰テスト。ブラウザは触らない。"""
import json

from ytkit.review import build_report, build_prompt, build_video_prompt, load_script
from ytkit.review import browser, report

HONNOJI = {
    'title': 'テスト動画',
    'head': 'テスト',
    'hook': 'フック文',
    'scenes': [
        {'text': '本文1', 'big': '大見出し1', 'sub': 'テロップ1', 'src': '出典1'},
        {'text': '本文2', 'big': '大見出し2', 'src': '出典2'},
    ],
    'claims': [
        {'id': 'c1', 'statement': '主張1', 'source_url': 'https://example.com', 'evidence_note': '確認済み'},
    ],
    'needs_research': ['未確認項目'],
}

RAKUTEN = {
    'title': '楽天テスト',
    'hook': 'フック',
    'scenes': [
        {'narration': 'ナレーション', 'caption': ['テロップA', 'テロップB'], 'visual': '模式図'},
    ],
    'claims': [{'id': 'c2', 'statement': '主張2', 'source_url': 'https://example.org'}],
    'needs_research': [],
}


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')


def test_honnoji_adapter(tmp_path):
    p = tmp_path / 'short_x.json'
    _write_json(p, HONNOJI)
    got = load_script(p, 'honnoji_json', 'honnoji', 'x')
    assert got['project'] == 'honnoji'
    assert got['title'] == 'テスト動画'
    assert got['scenes'][0]['caption'] == 'テロップ1'
    assert got['scenes'][0]['source'] == '出典1'
    assert got['claims'][0]['id'] == 'c1'
    assert got['needs_research'] == ['未確認項目']


def test_rakuten_adapter(tmp_path):
    p = tmp_path / 'result.json'
    _write_json(p, RAKUTEN)
    got = load_script(p, 'rakuten_result', 'rakuten', 'y')
    assert got['title'] == '楽天テスト'
    assert got['scenes'][0]['text'] == 'ナレーション'
    assert got['scenes'][0]['caption'] == 'テロップA / テロップB'
    assert got['claims'][0]['source_url'] == 'https://example.org'


def test_markdown_adapter(tmp_path):
    p = tmp_path / 'SAMPLE_SCRIPT.md'
    p.write_text('# 英語版\n## Scene 1\nFirst line.\nSecond line.\n## Scene 2\nAnother line.\n', encoding='utf8')
    got = load_script(p, 'markdown', 'detour-lab', 'ocean')
    assert got['title'] == '英語版'
    assert len(got['scenes']) == 2
    assert got['scenes'][0]['text'] == 'First line.'
    assert got['claims'] == []


def test_unknown_adapter(tmp_path):
    p = tmp_path / 'x.json'
    _write_json(p, {})
    try:
        load_script(p, 'nope', 'p', 's')
    except ValueError as e:
        assert '未知の adapter' in str(e)
    else:
        raise AssertionError('ValueError が出ない')


def test_prompt_contains_script_and_marker():
    script = dict(HONNOJI, project='honnoji', slug='x')
    for target in ('chatgpt', 'google'):
        text = build_prompt(script, target)
        assert '本文1' in text
        assert '主張1' in text
        assert '===ここまでが台本です===' in text
        assert '表は使わないでください' in text
        assert '書き直さないでください' in text


def test_prompt_unknown_target():
    try:
        build_prompt({'scenes': []}, 'gemini')
    except ValueError as e:
        assert '未知の target' in str(e)
    else:
        raise AssertionError('ValueError が出ない')


def test_browser_dry_run_does_not_touch_browser():
    script = {'project': 'p', 'slug': 's', 'title': 't', 'scenes': [], 'claims': []}
    prompt = 'テスト用プロンプト'
    assert browser.submit(script, 'chatgpt', prompt, dry_run=True) == prompt


def test_report_collects_verdict_and_count(tmp_path):
    root = tmp_path / 'proj'
    out = root / 'out'
    out.mkdir(parents=True)
    (out / 'review_chatgpt_demo.md').write_text(
        '総評: 直してから公開\n重大度: 高\n重大度: 中\n', encoding='utf8')
    (out / 'review_google_demo.md').write_text(
        '総評: 公開可\n重大度: 低\n', encoding='utf8')
    html_path = tmp_path / 'index.html'
    result = report.build_report([str(root)], str(html_path))
    doc = html_path.read_text(encoding='utf8')
    assert result['rows'] == 2
    assert '修正必要' in doc
    assert '公開可' in doc
    assert 'review_chatgpt_demo.md' in doc


def test_report_marks_missing_project(tmp_path):
    root = tmp_path / 'empty'
    root.mkdir()
    out = tmp_path / 'list.html'
    result = report.build_report([str(root)], str(out))
    assert result['rows'] == 0


def test_video_prompt_has_review_items():
    text = build_video_prompt('テスト動画')
    assert 'テスト動画' in text
    assert '時刻つきで書き起こしてください' in text
    assert '字幕と音声の一致' in text
    assert '公開可' in text and '修正必要' in text


def test_video_dry_run_does_not_touch_browser(tmp_path):
    from ytkit.review import submit_video
    video = tmp_path / 'a.mp4'
    video.write_bytes(b'x')
    prompt = '動画レビュー用プロンプト'
    assert submit_video(str(video), prompt, dry_run=True) == prompt


def test_video_report_pattern(tmp_path):
    root = tmp_path / 'proj'
    out = root / 'out'
    out.mkdir(parents=True)
    (out / 'review_google_video_demo.md').write_text(
        '総評: 公開可\n重大度: 低\n', encoding='utf8')
    rows = report.collect([str(root)])
    assert len(rows) == 1
    assert rows[0]['target'] == 'google-video'
    assert rows[0]['slug'] == 'demo'


def test_both_targets_spawn_two_processes(tmp_path, monkeypatch):
    """--target both は2つの子プロセスを起こし、両方の完了を待つ。"""
    import subprocess
    from ytkit.review import __main__ as cli

    path = tmp_path / 'script.json'
    _write_json(path, HONNOJI)
    calls = []

    class FakeProc:
        def __init__(self, argv):
            calls.append(argv)
            self.argv = argv

        def wait(self):
            return 0

        @property
        def returncode(self):
            return 0

    monkeypatch.setattr(subprocess, 'Popen', FakeProc)
    rc = cli.main(['run', str(path), '--adapter', 'honnoji_json',
                   '--project', 'p', '--slug', 's', '--target', 'both',
                   '--out-dir', str(tmp_path)])
    assert rc == 0
    assert len(calls) == 2
    assert '--target' in calls[0] and calls[0][calls[0].index('--target') + 1] == 'chatgpt'
    assert '--target' in calls[1] and calls[1][calls[1].index('--target') + 1] == 'google'
