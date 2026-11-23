"""VOICEVOX ENGINE への問い合わせ。

ENGINE の場所は環境変数 VOICEVOX_URL（既定 http://127.0.0.1:50021）。
"""
import os

import requests

DEFAULT_BASE = 'http://127.0.0.1:50021'


class SpeakerNotFound(LookupError):
    pass


def base_url(base=None):
    return base or os.environ.get('VOICEVOX_URL') or DEFAULT_BASE


def speaker_id(name, style='ノーマル', base=None, timeout=30):
    """話者名とスタイル名から id を引く。スタイルが無ければその話者の先頭スタイル。"""
    sp = requests.get(base_url(base) + '/speakers', timeout=timeout).json()
    for s in sp:
        if s['name'] == name:
            styles = s.get('styles') or []
            for st in styles:
                if st['name'] == style:
                    return st['id']
            if styles:
                return styles[0]['id']
    raise SpeakerNotFound(name)


def apply_pron(text, dic):
    """読み辞書で置換する。長い語から順に（部分一致で壊れないように）。"""
    for k, v in sorted((dic or {}).items(), key=lambda z: -len(z[0])):
        text = text.replace(k, v)
    return text


def synth(text, speaker, speed, intonation=1.0, pre=0.1, post=0.3, rate=24000,
          base=None, query_timeout=120, synth_timeout=180):
    """1文を合成して (wav のバイト列, VOICEVOX が返した読み kana) を返す。"""
    b = base_url(base)
    query = requests.post(b + '/audio_query', params={'text': text, 'speaker': speaker},
                          timeout=query_timeout)
    query.raise_for_status()
    q = query.json()
    q.update(speedScale=speed, intonationScale=intonation, prePhonemeLength=pre,
             postPhonemeLength=post, outputSamplingRate=rate)
    r = requests.post(b + '/synthesis', params={'speaker': speaker}, json=q, timeout=synth_timeout)
    r.raise_for_status()
    return r.content, q.get('kana', '')
