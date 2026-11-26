"""ytcore.vp の描画回帰テスト。

チャンネル固有の素材を使わず、合成 spec で 7 フレームを描き、ピクセルを固定する。
フォントは環境依存なので、Noto Sans/Serif JP VF が無いときはハッシュ検証を飛ばし、
構造的な検証（寸法・冪等性・場面差）だけを行う。
"""
import hashlib
import importlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

# 2026-11-23 時点の Windows 環境（NotoSansJP-VF.ttf / NotoSerifJP-VF.ttf）で
# 現在の ytcore.vp を描画した値。描画順・座標・色を変えると壊れる。
# 更新ルール: README「描画 Golden の更新」を参照。意図した描画変更のときだけ
# 担当者が現環境で取り直し、日付・フォント環境・理由をここに残す。
GOLDEN = {
    0: '933776a9a922802cba75e2a75a778f81dc111151bf6bdde538c4da590e97b2a3',
    15: 'd3ecec0969d16744b6e0612e77651d874fe87c8c0b09121748a25f7e2adf9c4b',
    45: 'b1fe77d48d6fa3aeaa830eb2971b45875e3c685a951159259f782c41f46c5331',
    90: '3c8b41f83e69a082e077c2ad544d274f2c0c5c732387466264e1e3551699488d',
    120: '467a8c38f0babba20260ec726bc16ba5779a7de18a43292354cb7f217ed0d51d',
    150: '701ee0702e985f2f73dfaa7fe0de3b2219a6d59de1f2280731b1cc9b4c2e307d',
    175: '73e986c151c25c1b50e526ab18421b050ef81acdcc53ca84023cd3ba9fecb589',
}
FONT_CANDIDATES = (
    Path(r'C:\Windows\Fonts\NotoSansJP-VF.ttf'),
    Path(r'C:\Windows\Fonts\NotoSerifJP-VF.ttf'),
)
CHANNEL_TOML = '''[channel]
about = "a"
name = "n"
tagline = "t"
tagline_tiktok = "tt"
terms_check = "c"
[voice]
speaker = "S"
style = "N"
speed = 1.0
label = "L"
credit = "v"
credit_long = "v"
[bgm]
dir = "d"
pattern = "p{name}.mp3"
credit = "b"
credit_long = "b"
file = "f.wav"
[bgm.names]
[fonts]
dir = "{fonts_dir}"
sans = "{sans}"
serif = "{serif}"
[hashtags]
shorts = "#s"
tiktok = "#t"
[project]
plugin_dir = "scripts"
'''

# 10 種類の部品を 1 章に詰め込む（stack / panel / image 以外をすべて描画）。
SCENE = [
    {'t': 'big', 'text': '千五百八十二年', 'y': 400, 'size': 70, 'at': 0},
    {'t': 'panel', 'box': [100, 550, 1700, 720], 'text': '光秀の兵は約一万三千', 'title': '検出', 'size': 40, 'at': 0},
    {'t': 'stack', 'items': [{'text': '一つ目', 'at': 0}, {'text': '二つ目', 'at': 1}], 'y0': 760, 'ymax': 1040, 'at': 0},
    {'t': 'timeline', 'nodes': [{'x': 400, 'label': '本能寺', 'sub': '六月二日', 'at': 0}, {'x': 1200, 'label': '山崎', 'sub': '七月', 'at': 1}], 'y': 500, 'at': 0},
    {'t': 'bars', 'box': [100, 600, 1700, 850], 'data': [{'label': 'A', 'value': 10, 'at': 0}, {'label': 'B', 'value': 20, 'at': 1}], 'at': 0},
    {'t': 'chips', 'items': [{'text': '信長', 'at': 0}, {'text': '光秀', 'at': 1}], 'y': 300, 'at': 0},
    {'t': 'table', 'box': [100, 120, 1700, 260], 'cols': ['年', '出来事'],
     'rows': [{'cells': ['1582', '本能寺'], 'at': 0}], 'size': 26, 'at': 0},
    {'t': 'daybar', 'rows': [{'label': '一日', 'mk': 360, 'bk': 1080, 'at': 0}], 'y': 880, 'at': 0},
    {'t': 'line', 'box': [100, 620, 1700, 840],
     'series': [{'label': 'A', 'value': 5, 'year': 0, 'at': 0}, {'label': 'B', 'value': 15, 'year': 1, 'at': 1}], 'at': 0},
    {'t': 'swirl', 'c': [1500, 900], 'r': 100, 'label': '渦', 'at': 0},
    {'t': 'shade', 'box': [60, 100, 1860, 300], 'alpha': 0.6, 'at': 0},
    {'t': 'art', 'name': 'dummy', 'box': [1400, 300, 1850, 700], 'dim': 0.7, 'at': 0},
]
SEGS = [
    {'scene': 0, 'text': '天正十年六月二日の未明、本能寺で信長が討たれました。',
     'start': 0.2, 'end': 2.8, 'pauses': [1.5], 'cue_times': [0.2, 1.5, 2.8]},
    {'scene': 0, 'text': 'その後、山崎で戦いがありました。',
     'start': 3.0, 'end': 5.5, 'pauses': [4.2], 'cue_times': [3.0, 4.2, 5.5]},
]


@pytest.fixture
def golden_vp(tmp_path, monkeypatch):
    """合成プロジェクトを用意して ytcore.vp を読み直す（test_core の vp fixture と同じ方式）。"""
    available = [p for p in FONT_CANDIDATES if p.exists()]
    if not available:
        pytest.skip('日本語可变フォントが無いため描画テストをスキップ')
    for src in available:
        shutil.copy(src, tmp_path / src.name)
    sans = next((p.name for p in available if 'Sans' in p.name), available[0].name)
    serif = next((p.name for p in available if 'Serif' in p.name), available[0].name)
    toml = (CHANNEL_TOML
            .replace('{fonts_dir}', tmp_path.as_posix().replace('\\', '/') + '/')
            .replace('{sans}', sans)
            .replace('{serif}', serif))

    (tmp_path / 'channel.toml').write_text(toml, encoding='utf8')
    monkeypatch.setenv('YT_PROJECT_ROOT', str(tmp_path))
    monkeypatch.setenv('PYTHONIOENCODING', 'utf8')

    for d in ('data', 'out', 'assets'):
        (tmp_path / d).mkdir(exist_ok=True)

    spec = {
        'theme_dir': 'theme', 'header_sub': 'golden',
        'chapters': [{'key': 'ch1', 'title': '第一章', 'chapter_title': '第一章', 'scene': SCENE}],
        'images': {'dummy': {'file': 'assets/dummy.png'}}, 'bgm': [],
    }
    (tmp_path / 'data/golden_spec.json').write_text(json.dumps(spec, ensure_ascii=False), encoding='utf8')
    Image.new('RGB', (400, 500), (60, 90, 130)).save(tmp_path / 'assets/dummy.png')
    (tmp_path / 'data/golden_timeline.json').write_text(json.dumps(
        [{'key': 'ch1', 'id': 0, 'start': 0.0, 'duration': 6.0, 'end': 6.0}], ensure_ascii=False), encoding='utf8')
    (tmp_path / 'out/golden_audio_report.json').write_text(json.dumps({'segments': SEGS}, ensure_ascii=False), encoding='utf8')

    old_path = sys.path[:]
    sys.modules.pop('ytcore.vp', None)
    vp = importlib.import_module('ytcore.vp')
    try:
        vp.load_spec('golden')
        vp.load_runtime()
        yield vp, bool(sans)
    finally:
        sys.modules.pop('ytcore.vp', None)
        sys.path[:] = old_path


def test_render_frames_are_structurally_stable(golden_vp):
    """描画が必ず 1920x1080 で、同じ時刻なら同じ絵になることを確認する。"""
    vp, _ = golden_vp
    first = vp.render_frame(45).convert('RGB')
    assert first.size == (1920, 1080)
    again = vp.render_frame(45).convert('RGB')
    assert first.tobytes() == again.tobytes()
    # 別の時刻では、字幕の切り替わりで絵が変わる
    other = vp.render_frame(90).convert('RGB')
    assert first.tobytes() != other.tobytes()
    # 背景だけではなく、何かが描かれている（単色でない）
    raw = first.tobytes()
    assert len({raw[i:i + 3] for i in range(0, len(raw), 3)}) > 100


def test_chapter_crossfade_blends_neighbouring_chapters(golden_vp, monkeypatch):
    """章の切れ目では前後の章が混ざり、どちらとも同じ絵にならない。"""
    vp, _ = golden_vp
    ch1 = {'key': 'ch1', 'id': 0, 'start': 0.0, 'duration': 6.0, 'end': 6.0}
    ch2 = {'key': 'ch2', 'id': 1, 'start': 6.0, 'duration': 6.0, 'end': 12.0}
    seg2 = {'scene': 1, 'text': '第二章の長いナレーションです。',
            'start': 6.2, 'end': 9.0, 'pauses': [], 'cue_times': [6.2, 9.0]}
    monkeypatch.setattr(vp.STATE, 'tl', [ch1, ch2])
    monkeypatch.setattr(vp.STATE, 'segs', SEGS + [seg2])
    ch2_spec = {'key': 'ch2', 'title': '第二章', 'chapter_title': '第二章', 'scene': SCENE}
    vp.STATE.spec['chapters'].append(ch2_spec)
    monkeypatch.setattr(vp.STATE, 'keys', ['ch1', 'ch2'])
    monkeypatch.setattr(vp.STATE, 'n', 360)
    monkeypatch.setattr(vp.STATE, 'subp', {})

    before = vp.render_frame(175).convert('RGB').tobytes()   # t=5.83 (章1のみ)
    boundary = vp.render_frame(180).convert('RGB').tobytes() # t=6.00 (クロスフェード)
    after = vp.render_frame(185).convert('RGB').tobytes()    # t=6.17 (章2寄り)

    assert before != boundary
    assert boundary != after
    # 境界の絵は、単独で描いたどちらの章とも異なる
    vp.STATE.tl = [ch1]
    vp.STATE.segs = SEGS
    vp.STATE.keys = ['ch1']
    only_first = vp.render_frame(180).convert('RGB').tobytes()
    assert boundary != only_first


def test_subtitle_pages_advance_with_time(golden_vp, monkeypatch):
    """長い文は複数ページに分かれ、時刻が進むと字幕が切り替わる。"""
    vp, _ = golden_vp
    long_text = '彼は、まず城へ行き、次に町へ行き、それから川を渡り、さらに山を登り、最後に寺に着きました。' + \
                'その後、また戻ってきて、もう一度同じ道を通り、別の場所へ向かいました。' + \
                'こうして、長い一日が終わり、夜になって、静かな場面になりました。'
    seg = {'scene': 0, 'text': long_text, 'start': 0.5, 'end': 5.5,
           'pauses': [], 'cue_times': []}
    monkeypatch.setattr(vp.STATE, 'segs', [seg])
    monkeypatch.setattr(vp.STATE, 'subp', {})
    d = ImageDraw.Draw(Image.new('RGB', (8, 8)))
    pages = vp.sub_lines(d, seg, vp.FSUB[52], 1.0)
    later = vp.sub_lines(d, seg, vp.FSUB[52], 4.0)
    assert pages != later, '長い文の字幕ページが時刻で切り替わらない'


def test_render_frame_pixel_hashes(golden_vp):
    """Noto VF フォントがある環境では、ピクセルを黄金値と比較する。"""
    vp, has_noto = golden_vp
    if not has_noto:
        pytest.skip('NotoSansJP-VF.ttf / NotoSerifJP-VF.ttf が無いためハッシュ比較をスキップ')
    for frame, expected in GOLDEN.items():
        got = hashlib.sha256(vp.render_frame(frame).convert('RGB').tobytes()).hexdigest()
        assert got == expected, f'frame {frame}: {got} != {expected}'
