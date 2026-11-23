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
    monkeypatch.setattr(vp, 'SEGS', [{'scene': 0, 'start': 1.0, 'end': 3.0}])
    monkeypatch.setattr(vp, 'KEYS', ['章'])
    cx = vp.Ctx(0, 2.0)
    assert cx.vis({'at': 0}) is True
    assert cx.vis({'at': 1}) is False
    assert cx.vis({'at': None, 'until': 0}) is False


def test_loud_args_uses_two_pass_measurement(vp, monkeypatch):
    measured = {'input_i': '-15.3', 'input_tp': '-1.4', 'input_lra': '4.2',
                'input_thresh': '-25.6', 'target_offset': '0.3'}
    monkeypatch.setattr(vp.yloud, 'measure_loudnorm',
                        lambda path, ffmpeg=None, lra=None: measured)
    af, got = vp.loud_args('narration.wav')
    assert got is measured
    assert af == ('loudnorm=I=-14:TP=-1.5:LRA=9:measured_I=-15.3:measured_TP=-1.4'
                  ':measured_LRA=4.2:measured_thresh=-25.6:offset=0.3:linear=true')


# ---- 二重起動防止

def test_lock_alive_detects_current_process():
    assert vp_lock.alive(os.getpid())
    assert not vp_lock.alive(-1)


# ---- 字幕書き出し・映像エンコードの共有部品

def test_srt_time_and_write_srt(tmp_path):
    assert subtitles.srt_time(0) == '00:00:00,000'
    assert subtitles.srt_time(61.5) == '00:01:01,500'
    assert subtitles.srt_time(3661.25) == '01:01:01,250'
    out = tmp_path / 'test.srt'
    subtitles.write_srt(out, [(0, 1.5, '一行目'), (60, 61.5, '二行目')])
    assert out.read_text(encoding='utf8') == (
        '1\n00:00:00,000 --> 00:00:01,500\n一行目\n\n'
        '2\n00:01:00,000 --> 00:01:01,500\n二行目\n')


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
