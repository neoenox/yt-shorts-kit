"""python -m ytkit.review の入口。"""
import argparse
from pathlib import Path

from .prompt import build_prompt
from .report import build_report
from .script import load_script
from .browser import submit


def main(argv=None):
    ap = argparse.ArgumentParser(description='台本レビューの共通部品')
    sub = ap.add_subparsers(dest='cmd', required=True)

    run = sub.add_parser('run', help='台本を ChatGPT / Google AI に送る')
    run.add_argument('path')
    run.add_argument('--adapter', required=True, choices=['honnoji_json', 'rakuten_result', 'markdown'])
    run.add_argument('--project', required=True)
    run.add_argument('--slug', required=True)
    run.add_argument('--target', default='both', choices=['chatgpt', 'google', 'both'])
    run.add_argument('--out-dir', default='out')
    run.add_argument('--dry-run', action='store_true')

    rep = sub.add_parser('report', help='レビュー成果物の一覧 HTML を作る')
    rep.add_argument('--roots', required=True, help='カンマ区切りのプロジェクトルート')
    rep.add_argument('--out', default='out/review_index.html')

    a = ap.parse_args(argv)

    if a.cmd == 'report':
        roots = [x for x in a.roots.split(',') if x.strip()]
        print(build_report(roots, a.out))
        return 0

    script = load_script(a.path, a.adapter, a.project, a.slug)
    targets = ['chatgpt', 'google'] if a.target == 'both' else [a.target]
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        prompt = build_prompt(script, target)
        if a.dry_run:
            print(f'--- {target} ---')
            print(prompt)
            continue
        answer = submit(script, target, prompt)
        path = out_dir / f'review_{target}_{a.slug}.md'
        path.write_text(answer, encoding='utf8')
        print(f'saved {path} ({len(answer)} chars)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
