import subprocess
from pathlib import Path

import pytest

from ytkit import ffmpeg_tools, freevideo, loudness, qa, voicevox

M = {'input_i': '-15.3', 'input_tp': '-1.4', 'input_lra': '4.2', 'input_thresh': '-25.6', 'target_offset': '0.3'}
LIMITER = 'alimiter=limit=0.79:level=disabled'


# ---- loudness: 移行前の各リポジトリが組み立てていた文字列と一致すること

def test_loudnorm_filter_matches_rakuten_two_pass():
    old = ('loudnorm=I=-14:TP=-1.5:LRA=7:measured_I=%s:measured_TP=%s:measured_LRA=%s'
           ':measured_thresh=%s:offset=%s:linear=true,alimiter=limit=0.79:level=disabled'
           % (M['input_i'], M['input_tp'], M['input_lra'], M['input_thresh'], M['target_offset']))
    assert loudness.loudnorm_filter(M, -14, -1.5, 7, limiter=LIMITER) == old


def test_loudnorm_filter_matches_rakuten_single_pass_fallback():
    assert loudness.loudnorm_filter(None, -14, -1.5, 7, limiter=LIMITER) == \
        'loudnorm=I=-14:TP=-1.5:LRA=7,alimiter=limit=0.79:level=disabled'


def test_loudnorm_filter_matches_rekishikaisetu_vp_two_pass():
    old = (f"loudnorm=I=-14:TP=-1.5:LRA=9:measured_I={M['input_i']}:measured_TP={M['input_tp']}"
           f":measured_LRA={M['input_lra']}:measured_thresh={M['input_thresh']}:offset={M['target_offset']}:linear=true")
    assert loudness.loudnorm_filter(M, -14, -1.5, 9) == old


def test_measure_loudnorm_parses_real_ffmpeg_json_layout(monkeypatch):
    """ffmpeg は { と \"input_i\" の間に改行とタブを入れる。移行前の正規表現はこれに不一致だった。"""
    stderr = '''[Parsed_loudnorm_0 @ 00000183c23d6b40]
{
\t"input_i" : "-15.3",
\t"input_tp" : "-1.4",
\t"input_lra" : "4.2",
\t"input_thresh" : "-25.6",
\t"output_i" : "-14.0",
\t"target_offset" : "0.3"
}
[out#0/null @ 00000183c0472800] video:0KiB audio:750KiB'''

    class Result:
        pass

    result = Result()
    result.stderr = stderr
    monkeypatch.setattr(loudness.subprocess, 'run', lambda *a, **kw: result)
    got = loudness.measure_loudnorm('x.wav')
    assert got is not None
    assert all(got[k] == v for k, v in M.items())


# ---- voicevox

def test_apply_pron_longest_key_first():
    assert voicevox.apply_pron('本能寺の変', {'本能': 'ほんのう', '本能寺': 'ほんのうじ'}) == 'ほんのうじの変'
    assert voicevox.apply_pron('abc', None) == 'abc'


class _Resp:
    def __init__(self, data=None, content=b''):
        self._d, self.content = data, content

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


def test_synth_sends_same_payload_as_the_old_code(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        return _Resp([{'name': '四国めたん', 'styles': [{'name': 'ノーマル', 'id': 2}, {'name': 'あまあま', 'id': 0}]}])

    def fake_post(url, params=None, json=None, timeout=None):
        calls.append((url, params, json))
        if url.endswith('/audio_query'):
            return _Resp({'kana': 'テスト', 'speedScale': 1.0})
        return _Resp(content=b'WAV')

    monkeypatch.setattr(voicevox.requests, 'get', fake_get)
    monkeypatch.setattr(voicevox.requests, 'post', fake_post)
    sid = voicevox.speaker_id('四国めたん', 'ノーマル')
    assert sid == 2
    wav, kana = voicevox.synth('テスト', sid, 0.95, intonation=1.08)
    assert (wav, kana) == (b'WAV', 'テスト')
    assert calls[0] == ('http://127.0.0.1:50021/audio_query', {'text': 'テスト', 'speaker': 2}, None)
    body = calls[1][2]
    assert body == {'kana': 'テスト', 'speedScale': 0.95, 'intonationScale': 1.08,
                    'prePhonemeLength': 0.1, 'postPhonemeLength': 0.3, 'outputSamplingRate': 24000}


def test_speaker_style_falls_back_to_first_and_unknown_speaker_raises(monkeypatch):
    monkeypatch.setattr(voicevox.requests, 'get',
                        lambda url, timeout: _Resp([{'name': 'X', 'styles': [{'name': 'a', 'id': 7}]}]))
    assert voicevox.speaker_id('X', 'ノーマル') == 7
    with pytest.raises(voicevox.SpeakerNotFound):
        voicevox.speaker_id('Y')


def test_voicevox_url_from_env(monkeypatch):
    monkeypatch.setenv('VOICEVOX_URL', 'http://example:1')
    assert voicevox.base_url() == 'http://example:1'
    assert voicevox.base_url('http://explicit') == 'http://explicit'


# ---- ffmpeg_tools

def test_find_ffmpeg_order(tmp_path, monkeypatch):
    ffmpeg_tools.clear_cache()
    a, b, c = (tmp_path / n for n in ('a.exe', 'b.exe', 'c.exe'))
    for f in (a, b, c):
        f.write_text('x')
    monkeypatch.delenv('FFMPEG', raising=False)
    monkeypatch.setattr(ffmpeg_tools.shutil, 'which', lambda n: None)
    assert ffmpeg_tools.find_ffmpeg(fallback=[str(c)]) == str(c)
    assert ffmpeg_tools.find_ffmpeg(prefer=[str(b)], fallback=[str(c)]) == str(b)
    monkeypatch.setenv('FFMPEG', str(a))
    assert ffmpeg_tools.find_ffmpeg(prefer=[str(b)]) == str(a)


def test_find_ffmpeg_is_cached_until_cleared(tmp_path, monkeypatch):
    ffmpeg_tools.clear_cache()
    ff = tmp_path / 'ffmpeg.exe'
    ff.write_text('x')
    calls = []

    def fake_which(name):
        calls.append(name)
        return str(ff) if name == 'ffmpeg' else None

    monkeypatch.setattr(ffmpeg_tools.shutil, 'which', fake_which)
    monkeypatch.delenv('FFMPEG', raising=False)
    assert ffmpeg_tools.find_ffmpeg() == str(ff)
    assert ffmpeg_tools.find_ffmpeg() == str(ff)
    assert calls == ['ffmpeg']   # 2回目はキャッシュから返る

    ffmpeg_tools.clear_cache()
    ffmpeg_tools.find_ffmpeg()
    assert calls == ['ffmpeg', 'ffmpeg']


def test_find_ffmpeg_not_found(monkeypatch):
    ffmpeg_tools.clear_cache()
    monkeypatch.delenv('FFMPEG', raising=False)
    monkeypatch.setattr(ffmpeg_tools.shutil, 'which', lambda n: None)
    with pytest.raises(ffmpeg_tools.FFmpegNotFound):
        ffmpeg_tools.find_ffmpeg()


def test_find_ffprobe_uses_sibling_then_default(tmp_path, monkeypatch):
    ffmpeg_tools.clear_cache()
    monkeypatch.delenv('FFPROBE', raising=False)
    monkeypatch.setattr(ffmpeg_tools.shutil, 'which', lambda n: None)
    ff = tmp_path / 'ffmpeg.exe'
    ff.write_text('x')
    assert ffmpeg_tools.find_ffprobe(str(ff), default=str(ff)) == str(ff)
    (tmp_path / 'ffprobe.exe').write_text('x')
    ffmpeg_tools.clear_cache()   # ファイルが出来たので探索をやり直す
    assert ffmpeg_tools.find_ffprobe(str(ff)) == str(tmp_path / 'ffprobe.exe')
    assert ffmpeg_tools.find_ffprobe(None, default='ffprobe') == 'ffprobe'


# ---- freevideo

def test_freevideo_quality_profiles():
    balanced = freevideo.graph('a', 544, 960, 5, seed=1)['1']['inputs']
    assert (balanced['two_pass'], balanced['base_steps'], balanced['refine_steps'],
            balanced['upscale_factor']) == (True, 8, 1, '2')

    fast = freevideo.graph('a', 544, 960, 5, seed=1, quality='fast')['1']['inputs']
    assert (fast['two_pass'], fast['base_steps']) == (False, 6)
    assert 'refine_steps' not in fast
    # upscale_factor は two_pass 専用（options は '2'/'1.5'/'1.2'）。一パスでは渡さない。
    assert 'upscale_factor' not in fast

    fastest = freevideo.graph('a', 544, 960, 5, seed=1, quality='fastest')['1']['inputs']
    assert fastest['base_steps'] == 4
    assert 'refine_steps' not in fastest
    assert 'upscale_factor' not in fastest

    custom = freevideo.graph('a', 544, 960, 5, seed=1, quality='fast', base_steps=3)
    assert custom['1']['inputs']['base_steps'] == 3
    with pytest.raises(ValueError, match='未知の quality'):
        freevideo.graph('a', 544, 960, 5, quality='ultra')


def test_freevideo_graph_and_video_of(tmp_path):
    g = freevideo.graph('a scene', 544, 960, 7, seed=5)
    inp = g['1']['inputs']
    assert (inp['text'], inp['width'], inp['height'], inp['seconds'], inp['seed']) == ('a scene', 544, 960, 7.0, 5)
    assert g['1']['inputs']['media'] == ['2', 0] and g['2']['class_type'] == 'FreeVideoMedia'
    entry = {'outputs': {'1': {'images': [{'filename': 'x.png'}, {'filename': 'v.mp4', 'subfolder': 's'}]}}}
    assert freevideo.video_of(entry, tmp_path) == tmp_path / 's' / 'v.mp4'
    assert freevideo.video_of({'outputs': {}}, tmp_path) is None


# ---- 実際の ffmpeg を使う検査（ffmpeg が無ければ飛ばす）

try:
    FF = ffmpeg_tools.find_ffmpeg()
except ffmpeg_tools.FFmpegNotFound:
    FF = None


@pytest.mark.skipif(not FF, reason='ffmpeg が無い')
def test_black_spans_detects_black_and_clean_video(tmp_path):
    blk, ok = tmp_path / 'blk.mp4', tmp_path / 'ok.mp4'
    subprocess.run([FF, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=white:s=320x240:d=2,format=yuv420p',
                    '-f', 'lavfi', '-i', 'color=c=black:s=320x240:d=1.5,format=yuv420p',
                    '-f', 'lavfi', '-i', 'color=c=white:s=320x240:d=1,format=yuv420p',
                    '-filter_complex', '[0][1][2]concat=n=3:v=1:a=0', str(blk)], check=True)
    subprocess.run([FF, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=white:s=320x240:d=3,format=yuv420p',
                    str(ok)], check=True)
    spans = qa.black_spans(blk, FF)
    assert len(spans) == 1 and spans[0][0] == pytest.approx(2.0, abs=0.1) and spans[0][1] == pytest.approx(1.5, abs=0.1)
    assert qa.black_spans(ok, FF) == []


@pytest.mark.skipif(not FF, reason='ffmpeg が無い')
def test_measure_ebur128_on_silence_and_probe_duration(tmp_path):
    w = tmp_path / 's.wav'
    subprocess.run([FF, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', str(w)], check=True)
    i, p = loudness.measure_ebur128(w, FF)
    assert i is not None and -40 < i < 0 and p is not None
    probe = ffmpeg_tools.find_ffprobe(FF, default=None)
    if probe:
        assert ffmpeg_tools.probe_duration(w, probe) == pytest.approx(2.0, abs=0.1)
    m = loudness.measure_loudnorm(w, FF, lra=7)
    assert m is not None and 'input_i' in m


def test_probe_duration_without_probe_returns_none(tmp_path):
    assert ffmpeg_tools.probe_duration(tmp_path / 'x.mp4', None) is None
    assert ffmpeg_tools.probe_duration(tmp_path / 'x.mp4', str(tmp_path / 'no-such-probe')) is None


def test_speaker_with_no_styles_raises_named_error(monkeypatch):
    monkeypatch.setattr(voicevox.requests, 'get',
                        lambda url, timeout: _Resp([{'name': 'X', 'styles': []}]))
    with pytest.raises(voicevox.SpeakerNotFound):
        voicevox.speaker_id('X')


def test_freevideo_output_root_comes_from_env(monkeypatch):
    """出力ルートは import 時ではなく呼び出し時に解決する。"""
    monkeypatch.setenv('FREEVIDEO_OUTPUT_ROOT', 'E:/other/output')
    entry = {'outputs': {'1': {'images': [{'filename': 'v.mp4'}]}}}
    assert freevideo.video_of(entry) == Path('E:/other/output/v.mp4')
    # 呼び出し時に上書きできる（旧来の引数もそのまま効く）
    assert freevideo.video_of(entry, 'E:/explicit') == Path('E:/explicit/v.mp4')


def test_freevideo_base_url_comes_from_env(monkeypatch):
    """サーバー URL も import 時ではなく呼び出し時に解決する。"""
    seen = []
    monkeypatch.setenv('FREEVIDEO_URL', 'http://example:9')
    monkeypatch.setattr(freevideo.urllib.request, 'urlopen',
                        lambda url, timeout: seen.append(url) or _Bytes(b'{}'))
    freevideo.get('/queue')
    assert seen == ['http://example:9/queue']


class _Bytes(bytes):
    def read(self):
        return self
