import json
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .http import HTTPFailure, request_json
from .models import DeliveryError


def payload_for(post, rules):
    return {
        'content': '🎵 新しいTikTok投稿\n' + post.url,
        'allowed_mentions': {'parse': []},
        'embeds': [{
            'title': '新しいTikTok投稿', 'url': post.url, 'color': 0xFE2C55,
            'fields': [
                {'name': '一致ルール', 'value': '\n'.join('・' + name for name in rules)[:1024]},
                {'name': '投稿者', 'value': ('@' + post.username)[:1024]},
                {'name': 'ハッシュタグ', 'value': (' '.join('#' + t for t in post.hashtags) or 'なし')[:1024]},
            ],
            'description': post.caption[:1500],
        }],
    }


class DiscordNotifier:
    def __init__(self, url):
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.hostname not in {'discord.com', 'discordapp.com'}
                or parts.username or parts.password or parts.port
                or not parts.path.startswith('/api/webhooks/')
                or len(parts.path.rstrip('/').split('/')) != 5):
            raise ValueError('DISCORD_WEBHOOK_URL が不正です')
        query = dict(parse_qsl(parts.query))
        query['wait'] = 'true'
        self.url = urlunsplit(parts._replace(query=urlencode(query), fragment=''))

    def send(self, post, rules):
        for attempt in range(3):
            try:
                response = request_json('POST', self.url, payload_for(post, rules))
                if not isinstance(response, dict) or not response.get('id'):
                    raise DeliveryError('Discordの保存確認がありません')
                return
            except HTTPFailure as error:
                if error.status == 429 and attempt < 2:
                    try:
                        delay = float(json.loads(error.body)['retry_after'])
                    except (ValueError, TypeError, KeyError):
                        delay = 5
                    if not 0 <= delay <= 60:
                        raise DeliveryError('Discord rate limit: 次回再試行') from None
                    time.sleep(delay + 0.5)
                    continue
                raise DeliveryError(f'Discord送信失敗 HTTP {error.status} (0=通信/応答異常)') from None
