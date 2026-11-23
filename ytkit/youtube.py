"""YouTube Data API を使ったリサーチ部品。

競合チャンネルの「何を・いつ・どう出しているか」を集計して、比較用の成果物を出す。
タイトルやサムネイルをそのままコピーするためのものではなく、投稿間隔・Short 比率・
タイトルの傾向などのパターンを比較するための部品。

対象チャンネルや期間はプロジェクトの channel.toml の [research] に置く（チャンネル固有の値をここに決め打ちしない）。
API キーは環境変数 YOUTUBE_API_KEY のみ。API キーが無い場合は `feed`（公開 RSS）で投稿間隔・タイトル傾向だけを集計できる。
"""
from collections import Counter
from datetime import date, datetime, timedelta
import json
import os
import re
import statistics
import sys
import xml.etree.ElementTree as ET

import requests

API_BASE = 'https://www.googleapis.com/youtube/v3'
FEED_BASE = 'https://www.youtube.com/feeds/videos.xml'
ATOM = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
DURATION = re.compile(r'P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?')
HASHTAG = re.compile(r'#([^\s#]+)')


class YouTubeError(RuntimeError):
    pass


def duration_seconds(text):
    """ISO 8601 の長さ（PT30S / PT1H2M3S など）を秒にする。"""
    m = DURATION.fullmatch(text or '')
    if not m:
        return 0
    parts = {k: int(v or 0) for k, v in m.groupdict().items()}
    return parts['d'] * 86400 + parts['h'] * 3600 + parts['m'] * 60 + parts['s']


def _get(path, params, api_key, timeout=30):
    r = requests.get(API_BASE + path, params={**params, 'key': api_key}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def channel_info(channel_id, api_key, timeout=30):
    """チャンネルの id・名前・アップロード再生リスト。"""
    data = _get('/channels', {'part': 'snippet,contentDetails', 'id': channel_id}, api_key, timeout)
    items = data.get('items') or []
    if not items:
        raise YouTubeError(f'チャンネルが見つからない: {channel_id}')
    item = items[0]
    return {
        'id': item['id'],
        'title': item.get('snippet', {}).get('title', channel_id),
        'uploads': item['contentDetails']['relatedPlaylists']['uploads'],
    }


def _playlist_items(playlist_id, api_key, limit, timeout=30):
    out, token = [], None
    while len(out) < limit:
        params = {'part': 'contentDetails', 'playlistId': playlist_id,
                  'maxResults': min(50, limit - len(out))}
        if token:
            params['pageToken'] = token
        data = _get('/playlistItems', params, api_key, timeout)
        out += data.get('items') or []
        token = data.get('nextPageToken')
        if not token:
            break
    return out[:limit]


def _videos(ids, api_key, timeout=30):
    out = []
    for i in range(0, len(ids), 50):
        data = _get('/videos', {'part': 'snippet,statistics,contentDetails',
                                'id': ','.join(ids[i:i + 50])}, api_key, timeout)
        out += data.get('items') or []
    return out


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def video_record(item):
    sn = item.get('snippet') or {}
    st = item.get('statistics') or {}
    dur = duration_seconds((item.get('contentDetails') or {}).get('duration'))
    return {
        'id': item.get('id'),
        'title': sn.get('title', ''),
        'published_at': sn.get('publishedAt', ''),
        'views': _number(st.get('viewCount')),
        'likes': _number(st.get('likeCount')),
        'comments': _number(st.get('commentCount')),
        'duration_seconds': dur,
        'is_short': 0 < dur <= 60,
        'tags': sn.get('tags') or [],
    }


def recent_videos(channel_id, api_key, limit=50, published_after=None, info=None, timeout=30):
    """指定チャンネルの最近の動画を新しい順に返す（published_after は YYYY-MM-DD）。"""
    info = info or channel_info(channel_id, api_key, timeout)
    items = _playlist_items(info['uploads'], api_key, limit, timeout)
    ids = [it['contentDetails']['videoId'] for it in items if it.get('contentDetails', {}).get('videoId')]
    records = [video_record(v) for v in _videos(ids, api_key, timeout)]
    if published_after:
        records = [r for r in records if r['published_at'][:10] >= published_after]
    return sorted(records, key=lambda r: r['published_at'], reverse=True)[:limit]

def _feed_root(channel_id, timeout=30):
    r = requests.get(FEED_BASE, params={'channel_id': channel_id}, timeout=timeout)
    r.raise_for_status()
    return ET.fromstring(r.content)

def feed_snapshot(channel_id, limit=15, timeout=30):
    """公開 RSS からチャンネル名と直近の動画を返す（API キー不要・再生数は取れない）。"""
    root = _feed_root(channel_id, timeout)
    title = root.findtext('a:title', namespaces=ATOM) or channel_id
    records = []
    for e in root.findall('a:entry', ATOM)[:limit]:
        entry_title = e.findtext('a:title', namespaces=ATOM) or ''
        # RSS のタグ（yt:tags/yt:tag と category）も集計に使う。タイトル内の # だけだと
        # ハッシュタグをタイトルに付けない動画が Short として数えられない。
        tags = [t.text.strip() for t in e.findall('yt:tags/yt:tag', ATOM) if t.text]
        tags += [t.get('term', '').strip() for t in e.findall('a:category', ATOM) if t.get('term')]
        tags += [m.group(1) for m in HASHTAG.finditer(entry_title)]
        tags = list(dict.fromkeys(t.lower().lstrip('#') for t in tags))
        records.append({
            'id': e.findtext('yt:videoId', namespaces=ATOM),
            'title': entry_title,
            'published_at': e.findtext('a:published', namespaces=ATOM) or '',
            'views': None,
            'likes': None,
            'comments': None,
            'duration_seconds': None,
            'is_short': any(t in ('shorts', 'short', 'ショート') for t in tags),
            'tags': tags,
        })
    return {'id': channel_id, 'title': title, 'uploads': ''}, records


def _hashtags(record):
    tags = [m.group(1).lower() for m in HASHTAG.finditer(record['title'])]
    tags += [t.lower().lstrip('#') for t in (record.get('tags') or [])]
    return list(dict.fromkeys(tags))


def summarize(info, records):
    """投稿間隔・エンゲージ・Short 比率・タイトル傾向を集計する。"""
    n = len(records)
    views = [r['views'] for r in records if isinstance(r.get('views'), int)]
    rates = [(r['likes'] + r['comments']) / r['views'] * 100
             for r in records if isinstance(r.get('views'), int) and r['views'] > 0]
    dates = []
    for r in records:
        try:
            dates.append(datetime.fromisoformat(r['published_at'].replace('Z', '+00:00')))
        except ValueError:
            pass
    dates.sort()
    gaps = [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])]
    tags = Counter(t for r in records for t in _hashtags(r))
    titles = [r['title'] for r in records]
    return {
        'id': info['id'],
        'title': info['title'],
        'count': n,
        'avg_views': round(statistics.mean(views)) if views else None,
        'median_views': round(statistics.median(views)) if views else None,
        'avg_engagement_pct': round(statistics.mean(rates), 2) if rates else None,
        'short_ratio': round(sum(bool(r['is_short']) for r in records) / n, 2) if n else 0.0,
        'avg_title_length': round(statistics.mean(len(t) for t in titles), 1) if titles else 0.0,
        'median_gap_days': round(statistics.median(gaps), 1) if gaps else 0.0,
        'top_hashtags': [tag for tag, _ in tags.most_common(5)],
    }


def report_markdown(summaries):
    lines = [
        '# YouTube リサーチ',
        '',
        '同じジャンルのチャンネルを、投稿の間隔・タイトル・タグの傾向で比較する。',
        'API キーを使う research では、さらに再生数・エンゲージ・尺を表示する。',
        'タイトルやサムネイルを丸写しせず、パターンを参考にするための表。',
        '',
        '| チャンネル | 本数 | 平均再生 | 中央再生 | エンゲージ率 | Short比率 | 平均タイトル長 | 投稿間隔(日) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for s in summaries:
        avg = f"{s['avg_views']:,}" if s['avg_views'] is not None else '-'
        med = f"{s['median_views']:,}" if s['median_views'] is not None else '-'
        eng = f"{s['avg_engagement_pct']}%" if s['avg_engagement_pct'] is not None else '-'
        lines.append(f"| {s['title']} | {s['count']} | {avg} | {med} | {eng} | "
                     f"{s['short_ratio']:.0%} | {s['avg_title_length']} | {s['median_gap_days']} |")
    lines += ['', '## よく使うハッシュタグ', '']
    for s in summaries:
        tags = ', '.join('#' + t for t in s['top_hashtags']) or 'なし'
        lines.append(f"- {s['title']}: {tags}")
    return '\n'.join(lines) + '\n'


def discover(topics, api_key, limit=10, timeout=30):
    """キーワードから似たジャンルのチャンネルを探す（search.listは quota を多く使う）。

    limit は全トピック合計の上限。トピック数で割って各 search.list の maxResults に渡す。
    """
    topics = list(topics)
    if not topics:
        return []
    per = max(1, limit // len(topics))
    found = []
    for topic in topics:
        if len(found) >= limit:
            break
        data = _get('/search', {'part': 'snippet', 'type': 'channel', 'q': topic,
                                'maxResults': min(50, limit - len(found), per)}, api_key, timeout)
        for item in data.get('items') or []:
            if len(found) >= limit:
                break
            sn = item.get('snippet') or {}
            found.append({'id': sn.get('channelId'), 'topic': topic,
                          'title': sn.get('title', ''),
                          'description': sn.get('description', '')[:120]})
    return found


def _config():
    from ytkit.project import project_root, load_config
    root = project_root(__file__)
    return root, load_config(root)


def _channels(research):
    channels = research.get('channels') or []
    if not channels:
        raise YouTubeError('channel.toml の [research] channels に比較したいチャンネル ID を足してください')
    return channels


def _write_reports(root, summaries, stem):
    out = root / 'out'
    out.mkdir(exist_ok=True)
    (out / f'{stem}.json').write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf8')
    (out / f'{stem}.md').write_text(report_markdown(summaries), encoding='utf8')
    return out


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else 'research'
    root, cfg = _config()
    research = cfg.get('research') or {}

    if cmd == 'feed':   # 公開 RSS。API キー不要だが、再生数・エンゲージは取れない
        summaries = []
        for cid in _channels(research):
            info, records = feed_snapshot(cid, limit=int(research.get('feed_limit', 15)))
            summaries.append(summarize(info, records))
        _write_reports(root, summaries, 'youtube_research_rss')
        print(f'written out/youtube_research_rss.md ({len(summaries)} channels)')
        return 0

    key = os.environ.get('YOUTUBE_API_KEY')
    if not key:
        raise YouTubeError('YOUTUBE_API_KEY を環境変数に設定してください')
    if cmd == 'discover':
        topics = research.get('topics') or []
        if not topics:
            raise YouTubeError('channel.toml の [research] topics にキーワードを足してください')
        for ch in discover(topics, key, limit=int(research.get('discover_limit', 10))):
            print(f"{ch['id']}\t{ch['title']}\t{ch['topic']}")
        return 0
    if cmd != 'research':
        raise YouTubeError(f'未知のコマンド: {cmd}（feed / research / discover）')

    days = int(research.get('lookback_days', 90))
    limit = int(research.get('max_per_channel', 50))
    after = (date.today() - timedelta(days=days)).isoformat()
    summaries = []
    for cid in _channels(research):
        info = channel_info(cid, key)
        records = recent_videos(cid, key, limit=limit, published_after=after, info=info)
        summaries.append(summarize(info, records))
    _write_reports(root, summaries, 'youtube_research')
    print(f'written out/youtube_research.md ({len(summaries)} channels)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
