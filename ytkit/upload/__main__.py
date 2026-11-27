"""python -m ytkit.upload の入口。"""
import argparse
import json
from pathlib import Path

from .pack import load_pack
from .studio import upload


def main(argv=None):
    ap = argparse.ArgumentParser(description='YouTube Studio へのアップロード')
    sub = ap.add_subparsers(dest='cmd', required=True)

    run = sub.add_parser('run', help='パックをアップロードして非公開で保存する')
    run.add_argument('pack')
    run.add_argument('--slug', default=None)
    run.add_argument('--publish', action='store_true',
                     help='公開する。省略時は非公開')
    run.add_argument('--dry-run', action='store_true')
    run.add_argument('--timeout', type=int, default=600)
    run.add_argument('--channel-id', default=None)

    chk = sub.add_parser('check', help='パックの必須ファイルだけ確認する')
    chk.add_argument('pack')

    a = ap.parse_args(argv)
    pack = load_pack(a.pack)

    if a.cmd == 'check':
        print(json.dumps({
            'title': pack['title_text'],
            'description_chars': len(pack['description_text']),
            'video': str(pack['video']),
            'thumbnail': 'thumbnail' in pack,
            'subtitles': 'subtitles' in pack,
        }, ensure_ascii=False))
        return 0

    slug = a.slug or Path(a.pack).name
    result = upload(pack, slug=slug, publish=a.publish,
                    dry_run=a.dry_run, timeout=a.timeout,
                    channel_id=a.channel_id)
    if a.dry_run:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({k: v for k, v in result.items() if k != 'tail'},
                         ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
