"""アップロード用パックの読み込みと検証。

パックは1フォルダに次を揃えたもの。
    video.mp4      必須
    title.txt      必須
    description.txt 必須
    thumbnail.jpg  任意
    subtitles.srt  任意

"""
from pathlib import Path

FILES = {
    'video': ('video.mp4', True),
    'title': ('title.txt', True),
    'description': ('description.txt', True),
    'thumbnail': ('thumbnail.jpg', False),
    'subtitles': ('subtitles.srt', False),
}


def load_pack(path):
    """パックを読み、存在するファイルのパスと本文を返す。"""
    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f'パックが無い: {root}')
    result = {}
    for key, (name, required) in FILES.items():
        p = root / name
        if p.is_file():
            result[key] = p
        elif required:
            raise FileNotFoundError(f'必須ファイルが無い: {p}')
    title = result['title'].read_text(encoding='utf8').strip()
    description = result['description'].read_text(encoding='utf8').strip()
    if not title:
        raise ValueError('title.txt が空です')
    if len(description) < 20:
        raise ValueError('description.txt が短すぎます')
    result['title_text'] = title
    result['description_text'] = description
    return result
