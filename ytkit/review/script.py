"""各プロジェクトの台本を共通形に変換する。

共通形:
    project: str
    slug: str
    title: str
    scenes: [{'text', 'big', 'caption', 'source'}]
    claims: [{'id', 'statement', 'source_url', 'evidence_note'}]
    needs_research: [str]
"""
import json
import re
from pathlib import Path


def _text(v):
    return '' if v is None else str(v)


def _honnoji_json(path, project, slug):
    d = json.loads(path.read_text(encoding='utf8'))
    scenes = []
    for sc in d.get('scenes', []):
        cap = sc.get('sub') or ''
        viz = sc.get('viz') or {}
        if viz.get('type') == 'timeline':
            cap = cap or ' / '.join(_text(e[1]) for e in viz.get('events', []) if len(e) > 1)
        scenes.append({
            'text': _text(sc.get('text')),
            'big': _text(sc.get('big')),
            'caption': cap,
            'source': _text(sc.get('src')),
        })
    claims = [{
        'id': _text(c.get('id')),
        'statement': _text(c.get('statement')),
        'source_url': _text(c.get('source_url')),
        'evidence_note': _text(c.get('evidence_note')),
    } for c in d.get('claims', [])]
    return {
        'project': project,
        'slug': slug,
        'title': _text(d.get('title') or d.get('head') or slug),
        'hook': _text(d.get('hook')),
        'scenes': scenes,
        'claims': claims,
        'needs_research': [str(x) for x in d.get('needs_research') or []],
    }


def _rakuten_result(path, project, slug):
    d = json.loads(path.read_text(encoding='utf8'))
    scenes = []
    for sc in d.get('scenes', []):
        cap = sc.get('caption') or []
        if isinstance(cap, list):
            cap = ' / '.join(_text(x) for x in cap)
        scenes.append({
            'text': _text(sc.get('narration')),
            'big': _text(sc.get('big')),
            'caption': _text(cap),
            'source': _text(sc.get('visual')),
        })
    claims = [{
        'id': _text(c.get('id')),
        'statement': _text(c.get('statement')),
        'source_url': _text(c.get('source_url')),
        'evidence_note': _text(c.get('evidence_note')),
    } for c in d.get('claims', [])]
    return {
        'project': project,
        'slug': slug,
        'title': _text(d.get('title') or slug),
        'hook': _text(d.get('hook')),
        'scenes': scenes,
        'claims': claims,
        'needs_research': [str(x) for x in d.get('needs_research') or []],
    }


def _markdown(path, project, slug):
    text = path.read_text(encoding='utf8')
    parts = re.split(r'(?m)^##\s+', text)
    title = parts[0].strip().splitlines()[0].lstrip('# ').strip() if parts else slug
    scenes = []
    for chunk in parts[1:]:
        lines = chunk.strip().splitlines()
        head = lines[0].strip() if lines else ''
        body = '\n'.join(lines[1:]).strip()
        if not body:
            continue
        first = body.split('\n')[0]
        scenes.append({
            'text': first,
            'big': head,
            'caption': '',
            'source': '',
        })
    if not scenes and text.strip():
        scenes = [{
            'text': text.strip()[:600],
            'big': title,
            'caption': '',
            'source': '',
        }]
    return {
        'project': project,
        'slug': slug,
        'title': title or slug,
        'hook': '',
        'scenes': scenes,
        'claims': [],
        'needs_research': [],
    }


ADAPTERS = {
    'honnoji_json': _honnoji_json,
    'rakuten_result': _rakuten_result,
    'markdown': _markdown,
}


def load_script(path, adapter, project, slug):
    """path を adapter で読み、共通形を返す。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'台本が無い: {p}')
    fn = ADAPTERS.get(adapter)
    if fn is None:
        raise ValueError(f'未知の adapter: {adapter}（{list(ADAPTERS)}）')
    return fn(p, project, slug)
