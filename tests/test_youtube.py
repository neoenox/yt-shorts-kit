"""YouTube リサーチ部品のテスト。API は呼ばず、レスポンスを差し替える。"""
import json
import xml.etree.ElementTree as ET

import pytest

from ytkit import youtube


INFO = {'id': 'UC1', 'title': '比較チャンネル', 'uploads': 'UU1'}


def _item(vid, title, published, duration, views, likes=0, comments=0, tags=()):
    return {
        'id': vid,
        'snippet': {'title': title, 'publishedAt': published, 'tags': list(tags)},
        'contentDetails': {'duration': duration},
        'statistics': {'viewCount': str(views), 'likeCount': str(likes), 'commentCount': str(comments)},
    }


def test_duration_seconds():
    assert youtube.duration_seconds('PT30S') == 30
    assert youtube.duration_seconds('PT1H2M3S') == 3723
    assert youtube.duration_seconds('P1DT2H') == 93600
    assert youtube.duration_seconds('') == 0


def test_recent_videos_parses_and_sorts(monkeypatch):
    calls = []

    def fake_get(path, params, api_key, timeout=30):
        calls.append(path)
        if path == '/channels':
            return {'items': [{'id': 'UC1', 'snippet': {'title': 'Ch'},
                               'contentDetails': {'relatedPlaylists': {'uploads': 'UU1'}}}]}
        if path == '/playlistItems':
            return {'items': [{'contentDetails': {'videoId': 'old'}},
                              {'contentDetails': {'videoId': 'new'}}]}
        return {'items': [
            _item('old', '古い動画', '2026-01-01T00:00:00Z', 'PT10M', 100, 5, 1),
            _item('new', '新しい #shorts', '2026-02-01T00:00:00Z', 'PT45S', 1000, 50, 10, ['#shorts']),
        ]}

    monkeypatch.setattr(youtube, '_get', fake_get)
    records = youtube.recent_videos('UC1', 'key', limit=10)
    assert calls == ['/channels', '/playlistItems', '/videos']
    assert [r['id'] for r in records] == ['new', 'old']
    assert records[0]['is_short'] is True
    assert records[1]['is_short'] is False
    assert (records[0]['views'], records[0]['likes'], records[0]['comments']) == (1000, 50, 10)


def test_summarize_and_report_compare_channels():
    records = [
        youtube.video_record(_item('a', 'A #shorts', '2026-01-01T00:00:00Z', 'PT30S', 100, 10, 5, ['#shorts'])),
        youtube.video_record(_item('b', 'B', '2026-01-08T00:00:00Z', 'PT10M', 300, 15, 5)),
    ]
    s = youtube.summarize(INFO, records)
    assert s['count'] == 2
    assert s['avg_views'] == 200
    assert s['avg_engagement_pct'] == 10.83
    assert s['short_ratio'] == 0.5
    assert s['median_gap_days'] == 7.0
    assert s['top_hashtags'] == ['shorts']

    md = youtube.report_markdown([s])
    assert '| 比較チャンネル | 2 | 200 | 200 | 10.83% | 50% |' in md
    assert '#shorts' in md


def test_discover_returns_channel_ids(monkeypatch):
    def fake_get(path, params, api_key, timeout=30):
        assert path == '/search' and params['type'] == 'channel'
        return {'items': [{'snippet': {'channelId': 'UC9', 'title': '似たチャンネル'}}]}

    monkeypatch.setattr(youtube, '_get', fake_get)
    found = youtube.discover(['歴史'], 'key', limit=5)
    assert found == [{'id': 'UC9', 'topic': '歴史', 'title': '似たチャンネル', 'description': ''}]


def test_main_writes_markdown_and_json(tmp_path, monkeypatch):
    monkeypatch.setenv('YOUTUBE_API_KEY', 'key')
    monkeypatch.setattr(youtube, '_config', lambda: (
        tmp_path, {'research': {'channels': ['UC1'], 'lookback_days': 30, 'max_per_channel': 10}}))
    monkeypatch.setattr(youtube, 'channel_info', lambda cid, key: INFO)
    monkeypatch.setattr(youtube, 'recent_videos', lambda *a, **kw: [
        youtube.video_record(_item('a', 'A #shorts', '2026-01-01T00:00:00Z', 'PT30S', 100, 10, 5, ['#shorts']))
    ])

    assert youtube.main(['research']) == 0
    md = (tmp_path / 'out' / 'youtube_research.md').read_text(encoding='utf8')
    data = json.loads((tmp_path / 'out' / 'youtube_research.json').read_text(encoding='utf8'))
    assert '比較チャンネル' in md and '#shorts' in md
    assert data[0]['id'] == 'UC1' and data[0]['count'] == 1


def test_main_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv('YOUTUBE_API_KEY', raising=False)
    monkeypatch.setattr(youtube, '_config', lambda: (tmp_path, {}))
    with pytest.raises(youtube.YouTubeError, match='YOUTUBE_API_KEY'):
        youtube.main(['research'])


RSS_FEED = '''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <title>RSSチャンネル</title>
  <entry><title>A #shorts</title><published>2026-01-01T00:00:00Z</published><yt:videoId>a</yt:videoId></entry>
  <entry><title>B</title><published>2026-01-08T00:00:00Z</published><yt:videoId>b</yt:videoId></entry>
</feed>'''


def test_feed_snapshot_parses_public_rss(monkeypatch):
    monkeypatch.setattr(youtube, '_feed_root', lambda cid, timeout=30: ET.fromstring(RSS_FEED))
    info, records = youtube.feed_snapshot('UC1', limit=2)
    assert info['title'] == 'RSSチャンネル'
    assert len(records) == 2
    assert records[0]['views'] is None and records[0]['duration_seconds'] is None
    assert records[0]['is_short'] is True and records[1]['is_short'] is False

    s = youtube.summarize(info, records)
    assert s['avg_views'] is None and s['avg_engagement_pct'] is None
    md = youtube.report_markdown([s])
    assert '| RSSチャンネル | 2 | - | - | - | 50% |' in md


def test_main_feed_writes_report_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv('YOUTUBE_API_KEY', raising=False)
    monkeypatch.setattr(youtube, '_config', lambda: (
        tmp_path, {'research': {'channels': ['UC1'], 'feed_limit': 2}}))
    monkeypatch.setattr(youtube, 'feed_snapshot', lambda cid, limit=15: (INFO, [
        {'id': 'a', 'title': 'A #shorts', 'published_at': '2026-01-01T00:00:00Z',
         'views': None, 'likes': None, 'comments': None, 'duration_seconds': None,
         'is_short': True, 'tags': []},
    ]))

    assert youtube.main(['feed']) == 0
    md = (tmp_path / 'out' / 'youtube_research_rss.md').read_text(encoding='utf8')
    data = json.loads((tmp_path / 'out' / 'youtube_research_rss.json').read_text(encoding='utf8'))
    assert '比較チャンネル' in md and data[0]['count'] == 1
