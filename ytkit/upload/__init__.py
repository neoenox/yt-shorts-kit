"""YouTube Studio へのアップロード共通部品。"""
from .pack import load_pack
from .studio import upload

__all__ = ['load_pack', 'upload']
