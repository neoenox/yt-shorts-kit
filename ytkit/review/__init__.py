"""台本レビューの共通部品。

各プロジェクトの台本を共通形に直し、ChatGPT / Google AI へ送り、
結果を一覧ページにまとめる。
"""
from .script import load_script, ADAPTERS
from .prompt import build_prompt, build_video_prompt
from .browser import submit, submit_video, close_review_tabs
from .report import build_report

__all__ = [
    'load_script', 'ADAPTERS', 'build_prompt', 'build_video_prompt',
    'submit', 'submit_video', 'close_review_tabs', 'build_report',
]
