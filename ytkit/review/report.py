"""各プロジェクトのレビュー成果物を走査し、HTML 一覧を生成する。

新形式 <root>/out/review_<target>_<slug>.md を優先し、既存の名前も読む。
"""
import html
import re
from datetime import datetime
from pathlib import Path

# (target, slug) を取り出す。新しい順に試す。
PATTERNS = [
    ('google-video', re.compile(r'^review_google_video_(.+)\.md$')),
    ('chatgpt', re.compile(r'^review_chatgpt_(.+)\.md$')),
    ('google', re.compile(r'^review_google_(.+)\.md$')),
    ('google', re.compile(r'^review_googleai_(.+)\.md$')),
    ('google', re.compile(r'^google_ai_review_(.+)_(script|video|custom)\.(txt|md)$')),
    # honnoji の chatgpt_review_<slug>.md は台本そのものなので拾わない。
    ('gemini', re.compile(r'^review_gemini\.md$')),
]

# 実際の返答にある判定語。長いものから順に試す。
VERDICTS = (
    ('作り直し', '作り直し'),
    ('直してから公開', '修正必要'),
    ('修正してから公開', '修正必要'),
    ('修正すれば公開可', '修正必要'),
    ('軽微な修正をすれば公開可能', '修正必要'),
    ('修正必要', '修正必要'),
    ('このまま公開', '公開可'),
    ('公開可', '公開可'),
)
SEVERITY = re.compile(r'重大度\s*[:：]\s*(高|中|低)')


def _parse(path, target, slug, project):
    text = path.read_text(encoding='utf8', errors='replace')
    verdict = '判定なし'
    for word, label in VERDICTS:
        if word in text:
            verdict = label
            break
    count = len(SEVERITY.findall(text))
    return {
        'project': project,
        'path': str(path),
        'target': target,
        'slug': slug,
        'verdict': verdict,
        'count': count,
        'mtime': datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
    }


# 成果物は out/ 直下か shorts/<slug>/ か docs/ 配下にある。深掘りしない。
SEARCH_DIRS = ('out', 'out_en', 'shorts', 'docs')


def collect(roots):
    """roots 配下のレビュー成果物を集める。"""
    found = []
    for root in roots:
        base = Path(root)
        if not base.exists():
            continue
        dirs = [base] + [base / d for d in SEARCH_DIRS if (base / d).is_dir()]
        for d in dirs:
            for path in sorted(d.glob('*.md')) + sorted(d.glob('*.txt')):
                if not path.is_file():
                    continue
                for target, rx in PATTERNS:
                    m = rx.match(path.name)
                    if not m:
                        continue
                    slug = m.group(1) if m.groups() and m.lastindex else path.parent.name
                    found.append(_parse(path, target, slug, base.name))
                    break
    return found


def _row(r):
    uri = Path(r['path']).as_uri()
    return (
        '<tr>'
        f"<td>{html.escape(r['project'])}</td>"
        f"<td>{html.escape(r['slug'])}</td>"
        f"<td>{html.escape(r['target'])}</td>"
        f"<td>{html.escape(r['verdict'])}</td>"
        f"<td>{r['count']}</td>"
        f"<td>{html.escape(r['mtime'])}</td>"
        f"<td><a href=\"{html.escape(uri, quote=True)}\">開く</a></td>"
        '</tr>'
    )


def build_report(roots, out):
    """HTML 一覧を out に書き、行数の dict を返す。"""
    rows = collect(roots)
    body = '\n'.join(_row(r) for r in rows)
    doc = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>台本レビュー一覧</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; color: #1b2430; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccd3da; padding: 6px 10px; text-align: left; }}
th {{ background: #eef2f6; }}
</style></head><body>
<h1>台本レビュー一覧</h1>
<p>{len(rows)} 件</p>
<table><thead><tr><th>プロジェクト</th><th>slug</th><th>対象</th><th>判定</th><th>指摘</th><th>更新</th><th>元ファイル</th></tr></thead>
<tbody>
{body}
</tbody></table></body></html>
"""
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc, encoding='utf8')
    return {'rows': len(rows), 'out': str(target)}
