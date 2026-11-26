"""ターゲットごとの実行と、並列実行の調整。

Playwright の sync API はスレッド間で共有できないため、
複数ターゲットは別プロセスで走らせる。
"""
import subprocess
import sys
from pathlib import Path

from .browser import close_review_tabs, submit, submit_video


def targets_of(value):
    """'both' を2つの target に広げる。"""
    return ['chatgpt', 'google'] if value == 'both' else [value]


def save_answer(out_dir, slug, target, answer):
    path = Path(out_dir) / f'review_{target}_{slug}.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(answer, encoding='utf8')
    print(f'saved {path} ({len(answer)} chars)')
    return path


def _run_child(cmd, out_dir, slug, target, prompt):
    """ compose 済みプロンプトを一時ファイル経由で子に渡す。"""
    tmp = Path(out_dir) / f'_prompt_{target}_{slug}.txt'
    tmp.write_text(prompt, encoding='utf8')
    argv = [sys.executable, '-m', 'ytkit.review'] + cmd + [
        '--slug', slug, '--target', target, '--out-dir', str(out_dir)]
    return tmp, subprocess.Popen(argv)


def run_parallel(cmd, out_dir, slug, prompts):
    """複数 target を別プロセスで同時に実行する。失敗数を返す。"""
    children = []
    for target, prompt in prompts.items():
        children.append((target, *_run_child(cmd, out_dir, slug, target, prompt)))
    failed = []
    for target, tmp, proc in children:
        if proc.wait() != 0:
            failed.append(target)
        tmp.unlink(missing_ok=True)
    if failed:
        print(f'failed: {", ".join(failed)}', file=sys.stderr)
    return len(failed)


def run_one(script, target, prompt, out_dir, slug, video=None):
    """単一 target を現在のプロセスで実行して保存する。"""
    if video:
        answer = submit_video(video, prompt)
    else:
        answer = submit(script, target, prompt)
    save_answer(out_dir, slug, target, answer)


def finish():
    """レビュー後のタブ始末。"""
    close_review_tabs()
