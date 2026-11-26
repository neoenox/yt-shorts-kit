"""python -m ytkit.review の入口。"""
import argparse
from pathlib import Path

from .prompt import build_prompt, build_video_prompt
from .report import build_report
from .runner import finish, run_one, run_parallel, targets_of
from .script import load_script


def _parser():
    ap = argparse.ArgumentParser(description='台本レビューの共通部品')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def common(p, path_help):
        p.add_argument('path', help=path_help)
        p.add_argument('--project', default='custom')
        p.add_argument('--slug', required=True)
        p.add_argument('--target', default='both', choices=['chatgpt', 'google', 'both'])
        p.add_argument('--out-dir', default='out')
        p.add_argument('--dry-run', action='store_true')

    run = sub.add_parser('run', help='台本を ChatGPT / Google AI に送る')
    common(run, '台本ファイル')
    run.add_argument('--adapter', required=True,
                     choices=['honnoji_json', 'rakuten_result', 'markdown'])

    custom = sub.add_parser('custom', help='任意のテキストとプロンプトを AI に送る')
    common(custom, 'レビュー対象のテキストファイル')
    custom.add_argument('--prompt-file', help='{{ARTICLE}} を本文に置換するテンプレート')

    vid = sub.add_parser('video', help='完成動画を Google AI に送る')
    vid.add_argument('video')
    vid.add_argument('--slug', default=None)
    vid.add_argument('--title', default='')
    vid.add_argument('--out-dir', default='out')
    vid.add_argument('--dry-run', action='store_true')

    rep = sub.add_parser('report', help='レビュー成果物の一覧 HTML を作る')
    rep.add_argument('--roots', required=True, help='カンマ区切りのプロジェクトルート')
    rep.add_argument('--out', default='out/review_index.html')
    return ap


def _compose(a):
    """サブコマンドごとの (script, prompts, video) を返す。"""
    if a.cmd == 'custom':
        text = Path(a.path).read_text(encoding='utf8')
        if a.prompt_file:
            tpl = Path(a.prompt_file).read_text(encoding='utf8')
            prompt = tpl.replace('{{ARTICLE}}', text)
        else:
            prompt = text
        return {}, {t: prompt for t in targets_of(a.target)}, None

    if a.cmd == 'run':
        script = load_script(a.path, a.adapter, a.project, a.slug)
        prompts = {t: build_prompt(script, t) for t in targets_of(a.target)}
        return script, prompts, None

    prompt = build_video_prompt(a.title)
    return {}, {'google': prompt}, a.video


def main(argv=None):
    a = _parser().parse_args(argv)

    if a.cmd == 'report':
        roots = [x for x in a.roots.split(',') if x.strip()]
        print(build_report(roots, a.out))
        return 0

    script, prompts, video = _compose(a)
    if a.dry_run:
        for target, prompt in prompts.items():
            print(f'--- {target} ---')
            print(prompt)
        return 0

    if a.cmd == 'custom' and a.target == 'both':
        # 子には compose 済みプロンプトを渡す。子は単一 target なので直接送信する。
        cmd = ['custom', a.path]
        if a.prompt_file:
            cmd += ['--prompt-file', a.prompt_file]
        cmd += ['--project', a.project]
        rc = run_parallel(cmd, a.out_dir, a.slug, prompts)
    elif a.cmd == 'run' and a.target == 'both':
        cmd = ['run', a.path, '--adapter', a.adapter, '--project', a.project]
        rc = run_parallel(cmd, a.out_dir, a.slug, prompts)
    else:
        target = next(iter(prompts))
        run_one(script, target, prompts[target], a.out_dir, a.slug, video)
        rc = 0

    if rc == 0:
        finish()
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
