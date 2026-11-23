"""ytcore の純粋な部品の回帰テスト。

描画そのものはプロジェクトの素材を要するが、字幕・数字表記・ロックは
共有パッケージだけで決まるので、ここで固定する。
"""
import importlib
import os
import sys

import pytest

from ytcore import hn_text, rich_text, subtitles, thin_commas, vp_lock


CHANNEL_TOML = '''[channel]
about = "テスト"
name = "ch"
tagline = "tag"
tagline_tiktok = "tt"
terms_check = "確認"
[voice]
speaker = "テスト話者"
style = "ノーマル"
speed = 1.0
label = "テスト話者"
credit_long = "音声: テスト"
credit = "音声: テスト"
[bgm]
dir = "assets/bgm"
pattern = "bgm_{name}.mp3"
credit_long = "BGM: {tracks}"
file = "music/a.wav"
credit = "BGM"
[hashtags]
shorts = "#s"
tiktok = "#t"
[bgm.names]
[fonts]
dir = "fonts/"
sans = "sans.ttf"
serif = "serif.ttf"
[project]
plugin_dir = "scripts"
'''


@pytest.fixture
def vp(monkeypatch, tmp_path):
    """最小の channel.toml を用意して vp を読み込む（プロジェクト側の shim の代わり）。"""
    (tmp_path / 'channel.toml').write_text(CHANNEL_TOML, encoding='utf8')
    monkeypatch.setenv('YT_PROJECT_ROOT', str(tmp_path))
    old_path = sys.path[:]
    sys.modules.pop('ytcore.vp', None)
    module = importlib.import_module('ytcore.vp')
    try:
        yield module
    finally:
        for name in ('ytcore.vp', 'ytcore.make_short', 'ytcore.make_short2'):
            sys.modules.pop(name, None)
        sys.path[:] = old_path


# ---- 字幕の数字表記

def test_display_converts_quantities_but_keeps_idioms():
    assert hn_text.display('天正十年六月二日の未明') == '天正10年6月2日の未明'
    assert hn_text.display('光秀の兵は、約一万三千ともいわれます。') == '光秀の兵は、約1万3千ともいわれます。'
    assert hn_text.display('約十七点五キロメートルでした。') == '約17.5キロメートルでした。'
    assert hn_text.display('5分の一') == '5分の1'
    # 「十分」を「10分」にしない。慣用句・固有名詞も守る。
    assert hn_text.display('不十分と十分な準備') == '不十分と十分な準備'
    assert hn_text.display('一騎当千と三日月') == '一騎当千と三日月'
    assert hn_text.display('八千代市と三千院、百舌鳥。') == '八千代市と三千院、百舌鳥。'
    assert hn_text.display('数十人') == '数十人'
    # 一〇〇万 のような 〇 を含む位取りは、0 ではなく 100万 にする
    assert hn_text.display('一〇〇万人が見た') == '100万人が見た'
    assert hn_text.big('一〇〇万') == '100万'
    assert hn_text.k2i('二〇二六') == 2026
    # 慣用句の退避に PUA を使わない（フォントの豆腐化を防ぐ）
    out = hn_text.display('不十分と十分な準備')
    assert not any(0xe000 <= ord(c) <= 0xf8ff or 0xf0000 <= ord(c) <= 0xffffd for c in out)


def test_thin_keeps_conjunction_and_long_clauses():
    assert thin_commas.thin('家康は、なぜ、浜松城から出て、信玄と戦ったのでしょうか。') == \
        '家康はなぜ浜松城から出て、信玄と戦ったのでしょうか。'
    assert thin_commas.thin('ところが、同時代に近い『信長公記』には、どちらも、書かれていません。') == \
        'ところが、同時代に近い『信長公記』には、どちらも書かれていません。'


def test_rich_text_splits_numbers_from_surrounding_text():
    assert rich_text.runs('約21時間（1,250分）') == [
        ('約', False), ('21時間', True), ('（', False), ('1,250分', True), ('）', False)]
    assert rich_text.runs('abc2026年x') == [('abc', False), ('2026年', True), ('x', False)]
    assert rich_text.runs('1,250.5キロ') == [('1,250.5キロ', True)]


# ---- 字幕の境界・場面の表示判定

def test_split_clauses_breaks_long_text_at_reading_pauses(vp):
    text = 'あ' * 30 + '、' + 'い' * 30
    assert vp.split_clauses(text) == ['あ' * 30 + '、', 'い' * 30]
    assert vp.split_clauses('短い文') == ['短い文']


def test_snap_bounds_uses_pauses_and_keeps_minimum_cue(vp):
    seg = {'start': 0.0, 'end': 10.0, 'pauses': [4.5]}
    assert vp.snap_bounds(seg, [0.0, 0.5, 1.0]) == [0.0, 4.5, 10.0]
    # 無音が文頭に近すぎるときは、比例位置を保つ（字幕が一瞬で消えない）。
    seg = {'start': 0.0, 'end': 10.0, 'pauses': [0.1]}
    assert vp.snap_bounds(seg, [0.0, 0.5, 1.0]) == [0.0, 5.0, 10.0]


def test_ctx_respects_at_and_until(vp, monkeypatch):
    monkeypatch.setattr(vp.STATE, 'segs', [{'scene': 0, 'start': 1.0, 'end': 3.0}])
    monkeypatch.setattr(vp.STATE, 'keys', ['章'])
    cx = vp.Ctx(0, 2.0)
    assert cx.vis({'at': 0}) is True
    assert cx.vis({'at': 1}) is False
    assert cx.vis({'at': None, 'until': 0}) is False


def test_vp_cli_rejects_missing_arguments(vp):
    with pytest.raises(SystemExit, match='usage:'):
        vp.main([])
    with pytest.raises(SystemExit, match='usage:'):
        vp.main(['slug'])
    with pytest.raises(SystemExit, match='unknown command'):
        vp.main(['slug', 'nope'])
    with pytest.raises(SystemExit, match='part に引数が足りません'):
        vp.main(['slug', 'part', '1'])


def test_vp_cli_dispatches_known_command(vp, monkeypatch):
    called = []
    monkeypatch.setattr(vp, 'load_spec', lambda slug: called.append(('spec', slug)))
    monkeypatch.setattr(vp, 'stage_desc', lambda: called.append('desc'))
    vp.main(['slug', 'desc'])
    assert called == [('spec', 'slug'), 'desc']


def test_loud_args_uses_two_pass_measurement(vp, monkeypatch):
    measured = {'input_i': '-15.3', 'input_tp': '-1.4', 'input_lra': '4.2',
                'input_thresh': '-25.6', 'target_offset': '0.3'}
    monkeypatch.setattr(vp, '_ffmpeg', lambda: '/tools/ffmpeg')
    monkeypatch.setattr(vp.yloud, 'measure_loudnorm',
                        lambda path, ffmpeg=None, lra=None: measured)
    af, got = vp.loud_args('narration.wav')
    assert got is measured
    assert af == ('loudnorm=I=-14:TP=-1.5:LRA=9:measured_I=-15.3:measured_TP=-1.4'
                  ':measured_LRA=4.2:measured_thresh=-25.6:offset=0.3:linear=true')


# ---- 二重起動防止

def test_part_fingerprint_is_isolated_per_chapter(vp, tmp_path):
    """他章の spec / 画像を変えても、ある章だけを含む part の指紋は変わらない。"""
    import json
    from PIL import Image

    (tmp_path / 'data').mkdir(exist_ok=True)
    (tmp_path / 'assets').mkdir(exist_ok=True)
    for name, col in (('a.png', (1, 2, 3)), ('b.png', (4, 5, 6)), ('c.png', (7, 8, 9))):
        Image.new('RGB', (8, 8), col).save(tmp_path / 'assets' / name)
    spec = {
        'theme_dir': 't', 'header_sub': 'h',
        'chapters': [
            {'key': 'a', 'title': 'A', 'scene': [{'t': 'image', 'name': 'ia', 'box': [0, 0, 10, 10]}]},
            {'key': 'b', 'title': 'B', 'scene': [{'t': 'image', 'name': 'ib', 'box': [0, 0, 10, 10]}]},
            {'key': 'c', 'title': 'C', 'scene': [{'t': 'image', 'name': 'ic', 'box': [0, 0, 10, 10]}]},
        ],
        'images': {
            'ia': {'file': 'assets/a.png'},
            'ib': {'file': 'assets/b.png'},
            'ic': {'file': 'assets/c.png'},
        },
        'bgm': [],
    }
    (tmp_path / 'data' / 'x_spec.json').write_text(json.dumps(spec, ensure_ascii=False), encoding='utf8')
    (tmp_path / 'data' / 'x_timeline.json').write_text(json.dumps([
        {'key': 'a', 'id': 0, 'start': 0.0, 'duration': 2.0, 'end': 2.0},
        {'key': 'b', 'id': 1, 'start': 2.0, 'duration': 2.0, 'end': 4.0},
        {'key': 'c', 'id': 2, 'start': 4.0, 'duration': 2.0, 'end': 6.0},
    ], ensure_ascii=False), encoding='utf8')
    (tmp_path / 'out').mkdir(exist_ok=True)
    (tmp_path / 'out' / 'x_audio_report.json').write_text(json.dumps({'segments': []}, ensure_ascii=False), encoding='utf8')

    vp.load_spec('x')
    vp.load_runtime()
    codefp = 'dummy-code-fp'
    chapter_fps = {ci: vp._chapter_fp(ci) for ci in range(len(vp.STATE.tl))}
    # 章Aの part（前後1章 = 章B までを見る）と章Cの part
    a_before = vp._part_fp(0, 29, codefp, chapter_fps)
    c_before = vp._part_fp(120, 149, codefp, chapter_fps)

    spec['chapters'][2]['title'] = 'C改'
    (tmp_path / 'data' / 'x_spec.json').write_text(json.dumps(spec, ensure_ascii=False), encoding='utf8')
    vp.load_spec('x')
    vp.load_runtime()
    chapter_fps2 = {ci: vp._chapter_fp(ci) for ci in range(len(vp.STATE.tl))}
    a_after = vp._part_fp(0, 29, codefp, chapter_fps2)
    c_after = vp._part_fp(120, 149, codefp, chapter_fps2)

    assert a_after == a_before   # 2章先の章Cを変えても章Aの part は再利用できる
    assert c_after != c_before   # 章Cの part は作り直す


def test_render_state_keeps_two_specs_independent(vp, monkeypatch, tmp_path):
    """2つの RenderState を切り替えても、互いの spec/timeline が混ざらない。"""
    import json
    (tmp_path / 'data').mkdir(exist_ok=True)
    (tmp_path / 'out').mkdir(exist_ok=True)
    for slug, title in (('a', 'A章'), ('b', 'B章')):
        (tmp_path / 'data' / f'{slug}_spec.json').write_text(json.dumps({
            'theme_dir': 't', 'header_sub': 'h',
            'chapters': [{'key': 'ch', 'title': title, 'chapter_title': title, 'scene': []}],
            'images': {}, 'bgm': [],
        }, ensure_ascii=False), encoding='utf8')
        (tmp_path / 'data' / f'{slug}_timeline.json').write_text(json.dumps(
            [{'key': 'ch', 'id': 0, 'start': 0.0, 'duration': 5.0, 'end': 5.0}], ensure_ascii=False), encoding='utf8')
        (tmp_path / 'out' / f'{slug}_audio_report.json').write_text(json.dumps({'segments': []}, ensure_ascii=False), encoding='utf8')

    states = []
    for slug in ('a', 'b'):
        st = vp.RenderState()
        st.load_spec(slug)
        st.load_runtime()
        states.append(st)

    assert states[0].spec['chapters'][0]['title'] == 'A章'
    assert states[1].spec['chapters'][0]['title'] == 'B章'
    assert states[0].keys == states[1].keys == ['ch']
    # proxy は各 state の現在値を読む（差し替えにも追従）
    pa, pb = states[0].as_dict(), states[1].as_dict()
    assert pa['SPEC'] is states[0].spec
    assert pb['SPEC'] is states[1].spec
    assert pa['P']('x') == vp.P('x')
    states[0].load_spec('a')   # 再ロードしても pb は影響しない
    assert pb['SPEC'] is states[1].spec


def test_lock_alive_detects_current_process():
    assert vp_lock.alive(os.getpid())
    assert not vp_lock.alive(-1)


def test_lock_others_counts_prep_and_audio_as_builds(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'other1.lock').write_text(f'{os.getpid()} prep 12:00:00', encoding='utf8')
    (cache / 'other2.lock').write_text(f'{os.getpid()} audio 12:00:00', encoding='utf8')
    (cache / 'other3.lock').write_text(f'{os.getpid()} build 12:00:00', encoding='utf8')
    (cache / 'self.lock').write_text(f'{os.getpid()} build 12:00:00', encoding='utf8')
    # Simulate lock contention for these metadata-only fixtures. Real OS-level
    # contention and stale-file behavior are exercised in tests/test_lock.py.
    monkeypatch.setattr(vp_lock, '_try_lock', lambda fd: False)
    assert vp_lock.others(tmp_path, 'self') == 3


# ---- 字幕書き出し・映像エンコードの共有部品

def test_srt_time_and_write_srt(tmp_path):
    assert subtitles.srt_time(0) == '00:00:00,000'
    assert subtitles.srt_time(61.5) == '00:01:01,500'
    assert subtitles.srt_time(3661.25) == '01:01:01,250'
    assert subtitles.srt_time(-0.001) == '00:00:00,000'   # 負の時刻は SRT で無効
    out = tmp_path / 'test.srt'
    subtitles.write_srt(out, [(0, 1.5, '一行目'), (60, 61.5, '二行目')])
    assert out.read_text(encoding='utf8') == (
        '1\n00:00:00,000 --> 00:00:01,500\n一行目\n\n'
        '2\n00:01:00,000 --> 00:01:01,500\n二行目\n')


def test_subtitle_chunks_handles_empty_text(vp):
    m2 = importlib.import_module('ytcore.make_short2')
    segs = [{'i': 0, 'text': '', 'start': 0.0, 'end': 2.0}]
    cks = m2.subtitle_chunks(segs)
    assert len(cks) == 1
    assert cks[0][0] == 0.0 and cks[0][1] == 2.0


def test_encode_frames_writes_frames_and_reports_failure(vp, monkeypatch, tmp_path):
    ms = importlib.import_module('ytcore.make_short')
    rc = [0]
    made = []

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.stdin = self
            self.written = []
            self.closed = False
            made.append(self)

        def write(self, data):
            self.written.append(data)

        def close(self):
            self.closed = True

        def wait(self):
            return rc[0]

    monkeypatch.setattr(ms.subprocess, 'Popen', FakeProc)
    monkeypatch.setattr(ms, 'find_ffmpeg', lambda: '/tools/ffmpeg')

    ms.encode_frames(tmp_path / 'a.mp4', [b'ab', b'cd'], preset='veryfast')
    assert made[0].cmd[0] == '/tools/ffmpeg'
    assert made[0].cmd[made[0].cmd.index('-preset') + 1] == 'veryfast'
    assert made[0].written == [b'ab', b'cd']
    assert made[0].closed

    rc[0] = 1
    with pytest.raises(ms.subprocess.CalledProcessError):
        ms.encode_frames(tmp_path / 'a.mp4', [b'ab'])
