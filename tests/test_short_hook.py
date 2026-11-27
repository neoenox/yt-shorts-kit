"""冒頭の結論カードと字幕の出現時刻を、外部素材なしで固定する回帰テスト。

frame_at の 3.2s（カード表示の間は場面の見出し・図を出さない）と
2.7s（字幕の二重表示を抑止する）を戻すと失敗する。
channel.toml と背景 PNG は tmp_path に作り、音声合成・ffmpeg・実アートは使わない。
"""
import importlib
import sys

import pytest
from PIL import Image, ImageFont

CHANNEL_TOML = '''[channel]
about = "test"
name = "ch"
tagline = "tag"
tagline_tiktok = "tt"
terms_check = "check"
[voice]
speaker = "S"
style = "N"
speed = 1.0
label = "L"
credit = "v"
credit_long = "v"
[bgm]
dir = "assets"
pattern = "bgm_{name}.mp3"
credit = "b"
credit_long = "b"
file = "music/a.wav"
[bgm.names]
[fonts]
dir = "fonts/"
sans = "sans.ttf"
serif = "serif.ttf"
[hashtags]
shorts = "#s"
tiktok = "#t"
[project]
plugin_dir = "scripts"
'''

BG_COLOR = (80, 120, 160)
BG_FILE = 'assets/bg.png'
# 場面の sub パネル(y800〜)、字幕帯(y1240〜1540)、カードの左枠(x60〜、y560〜760)。
SCENE_SUB_BOX = (60, 800, 960, 1000)
CAPTION_BOX = (50, 1240, 960, 1545)
HOOK_EDGE_BOX = (60, 560, 68, 760)
MODULES = ('ytcore.make_short2', 'ytcore.make_short')


@pytest.fixture
def short_hook(tmp_path, monkeypatch):
    """合成プロジェクトを読み込んだ make_short2 を返す（他テストの import 状態は戻す）。"""
    (tmp_path / 'channel.toml').write_text(CHANNEL_TOML, encoding='utf8')
    (tmp_path / 'assets').mkdir()
    Image.new('RGB', (64, 64), BG_COLOR).save(tmp_path / BG_FILE)
    monkeypatch.setenv('YT_PROJECT_ROOT', str(tmp_path))
    saved = {name: sys.modules.get(name) for name in MODULES}
    for name in MODULES:
        sys.modules.pop(name, None)
    try:
        m2 = importlib.import_module('ytcore.make_short2')
        ms = importlib.import_module('ytcore.make_short')
        # フォント環境に依存させない（描画の有無だけを見るので等幅フォントで十分）。
        plain = ImageFont.load_default()
        monkeypatch.setattr(ms, 'font', lambda size, serif=False: plain)
        monkeypatch.setattr(m2, 'font', lambda size, serif=False: plain)
        monkeypatch.setattr(m2, 'ROOT', tmp_path)
        m2._BG.clear()
        yield m2
    finally:
        for name, old in saved.items():
            sys.modules.pop(name, None)
            if old is not None:
                sys.modules[name] = old


def spec_with(**changes):
    spec = {
        'title': '題名', 'head': '見出し', 'answer': '答えはこれ',
        'art': BG_FILE,
        'scenes': [{'text': 'あいうえお、かきくけこ。', 'big': '大きな文字',
                    'sub': '補足の文', 'dim': 1.0}],
    }
    spec.update(changes)
    return spec


SEGS = [{'i': 0, 'text': 'あいうえお、かきくけこ。', 'start': 0.5, 'end': 10.0}]
CKS = [(0.0, 10.0, '字幕の一文')]


def frame_at(m2, t, **changes):
    return m2.frame_at(spec_with(**changes), SEGS, CKS, t)


def ink(im, box):
    """一色の背景から変わったピクセル数（その領域に何か描かれたかの指標）。"""
    raw = im.crop(box).convert('RGB').tobytes()
    bg = bytes(BG_COLOR)
    return sum(raw[i:i + 3] != bg for i in range(0, len(raw), 3))


def spy_draw(m2, monkeypatch):
    """描かれた場面の内容と alpha を記録する（カードは枠のピクセルで判定）。"""
    calls = []
    scene = m2.draw_scene

    def record(im, sc, spec, a):
        calls.append((dict(sc), a))
        return scene(im, sc, spec, a)

    monkeypatch.setattr(m2, 'draw_scene', record)
    return calls


def test_scene_subtitle_hidden_at_3_0_and_shown_after_3_2(short_hook):
    """カード window を 2.25s に戻すと t=3.0 で場面字幕が出て落ちる。"""
    early = frame_at(short_hook, 3.0)
    assert ink(early, SCENE_SUB_BOX) == 0
    assert ink(early, HOOK_EDGE_BOX) == 0   # カード本体は 1.9s で消えている

    late = frame_at(short_hook, 3.3)
    assert ink(late, SCENE_SUB_BOX) > 0
    assert ink(late, HOOK_EDGE_BOX) == 0


def test_hook_window_boundary_reveals_scene_content(short_hook):
    """3.2s ちょうどで場面の見出し・図が戻る（少し前はまだ出さない）。"""
    assert ink(frame_at(short_hook, 3.19), SCENE_SUB_BOX) == 0
    assert ink(frame_at(short_hook, 3.2), SCENE_SUB_BOX) > 0


def test_caption_chunk_suppressed_until_2_7(short_hook):
    """字幕抑止を 1.75s に戻すと t=2.5 で字幕が出て落ちる。"""
    assert ink(frame_at(short_hook, 2.5), CAPTION_BOX) == 0
    for t in (2.7, 2.9, 3.0, 3.3):
        assert ink(frame_at(short_hook, t), CAPTION_BOX) > 0, f'{t}s の字幕が出ない'


def test_hook_alpha_ramp_leaves_no_scene_overlap(short_hook, monkeypatch):
    """1.9〜3.2s はカードが消えた後も場面の見出し・図を出さず、重なりのないまま 3.2s で戻る。"""
    calls = spy_draw(short_hook, monkeypatch)
    for t in (1.8, 2.0, 2.25, 3.1):
        calls.clear()
        im = frame_at(short_hook, t)
        assert len(calls) == 1
        sc, a = calls[0]
        assert all(k not in sc for k in ('big', 'sub', 'viz', 'src')), f'{t}s で場面が重なる'
        assert a == pytest.approx(1.0)   # この間はヘッダーだけを不透明に描く
        if t <= 1.9:
            assert ink(im, HOOK_EDGE_BOX) > 0   # カードが消える前だけ枠が見える
        else:
            assert ink(im, HOOK_EDGE_BOX) == 0

    calls.clear()
    im = frame_at(short_hook, 3.2)
    assert len(calls) == 1
    sc, a = calls[0]
    assert all(k in sc for k in ('big', 'sub'))
    assert a == pytest.approx(1.0)
    assert ink(im, SCENE_SUB_BOX) > 0


@pytest.mark.parametrize('changes', [{'hook_card': False}, {'answer': None}])
def test_caption_visible_without_card_at_3_0(short_hook, changes):
    """hook_card=False / answer 無しなら、3.0s でも字幕と場面の補足が出る。"""
    im = frame_at(short_hook, 3.0, **changes)
    assert ink(im, CAPTION_BOX) > 0
    assert ink(im, SCENE_SUB_BOX) > 0
    assert ink(im, HOOK_EDGE_BOX) == 0
