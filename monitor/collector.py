"""Public page adapter. No login, private API signing, or CAPTCHA bypass."""
import json
import logging
import re
import time
from urllib.parse import quote, urlparse

from .models import FetchError, Post
from .rules import extract_hashtags, normalize

log = logging.getLogger(__name__)


def parse_item(item: dict) -> Post | None:
    """Only accept complete video objects; never infer tags from the discovery page."""
    video_id = str(item.get('id', ''))
    author = item.get('author')
    caption = item.get('desc')
    if not (re.fullmatch(r'[0-9]{5,25}', video_id) and 'video' in item
            and isinstance(author, dict) and isinstance(caption, str)):
        return None
    username = author.get('uniqueId')
    created = item.get('createTime')
    if not isinstance(username, str) or not username or isinstance(created, bool):
        return None
    try:
        created = int(created)
    except (TypeError, ValueError):
        return None
    if not 0 < created <= time.time() + 86400:
        return None
    tags = extract_hashtags(caption)
    for entity in item.get('textExtra', []) or []:
        if isinstance(entity, dict) and entity.get('hashtagName'):
            try:
                tags.add(normalize(entity['hashtagName']))
            except ValueError:
                pass
    return Post(video_id, f'https://www.tiktok.com/@{quote(username, safe="._-")}/video/{video_id}',
                username, caption, tuple(sorted(tags)), created)


def posts_in_payload(payload) -> list[Post]:
    found = {}
    def walk(value):
        if isinstance(value, dict):
            post = parse_item(value)
            if post:
                found[post.id] = post
            else:
                for child in value.values():
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(payload)
    return list(found.values())


class BrowserCollector:
    def __init__(self, scrolls=3, wait_seconds=5, headed=False):
        self.scrolls = scrolls
        self.wait_seconds = wait_seconds
        self.headed = headed

    def collect(self, tags):
        from playwright.sync_api import sync_playwright, Error
        results = {}
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=not self.headed)
                context = browser.new_context(locale='ja-JP')
                context.route('**/*', lambda route: route.abort() if route.request.resource_type
                              in {'image', 'media', 'font'} else route.continue_())
                for tag in tags:
                    page = context.new_page()
                    found = {}
                    invalid = []
                    diagnostics = {'list_responses': 0, 'script_failures': 0, 'page_errors': 0}
                    def request_failed(request):
                        if request.resource_type == 'script':
                            diagnostics['script_failures'] += 1
                    def page_error(error):
                        diagnostics['page_errors'] += 1
                    page.on('requestfailed', request_failed)
                    page.on('pageerror', page_error)
                    def response_received(response):
                        parsed = urlparse(response.url)
                        if parsed.hostname not in {'www.tiktok.com', 'www.tiktokv.com'}:
                            return
                        if parsed.path.rstrip('/') != '/api/challenge/item_list':
                            return
                        diagnostics['list_responses'] += 1
                        try:
                            if response.status != 200:
                                invalid.append(f'HTTP {response.status}')
                                return
                            if not response.body():
                                invalid.append('動画一覧の応答本文が空です（HTTP 200）')
                                return
                            data = response.json()
                            if data.get('statusCode') != 0 or not isinstance(data.get('itemList'), list):
                                invalid.append('動画一覧の応答形式/ステータス異常')
                                return
                            for item in data['itemList']:
                                post = parse_item(item) if isinstance(item, dict) else None
                                if post is None:
                                    invalid.append('動画メタデータ欠落')
                                else:
                                    found[post.id] = post
                        except Exception:
                            invalid.append('動画一覧JSON解析失敗')
                    page.on('response', response_received)
                    response = page.goto(f'https://www.tiktok.com/tag/{quote(tag, safe="")}',
                                         wait_until='domcontentloaded', timeout=45000)
                    if not response or response.status >= 400:
                        raise FetchError(f'#{tag}: ページ取得失敗')
                    for step in range(self.scrolls + 1):
                        page.wait_for_timeout(self.wait_seconds * 1000)
                        for script_id in ('__UNIVERSAL_DATA_FOR_REHYDRATION__', 'SIGI_STATE'):
                            script = page.locator(f'script[id="{script_id}"]')
                            if script.count():
                                try:
                                    payload = json.loads(script.first.text_content() or '{}')
                                    # Restrict hydration traversal to tag-specific scopes, not recommendations.
                                    if script_id == 'SIGI_STATE':
                                        payload = payload.get('ItemModule', {})
                                    else:
                                        payload = {k: v for k, v in payload.get('__DEFAULT_SCOPE__', {}).items()
                                                   if 'challenge' in k}
                                    for post in posts_in_payload(payload):
                                        found[post.id] = post
                                except (ValueError, TypeError):
                                    invalid.append('埋め込みJSON解析失敗')
                        if step < self.scrolls:
                            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    if invalid or not found:
                        location = urlparse(page.url)
                        diagnostics.update({
                            'host': location.hostname, 'path': location.path,
                            'title': page.title(),
                            'video_links': page.locator('a[href*="/video/"]').count(),
                            'hydration_scripts': page.locator('script[id="__UNIVERSAL_DATA_FOR_REHYDRATION__"], script[id="SIGI_STATE"]').count(),
                            'visible_text': page.locator('body').inner_text(timeout=5000)[:300],
                        })
                        log.error('fetch_diagnostics=%s', json.dumps(diagnostics, ensure_ascii=False))
                    if invalid:
                        raise FetchError(f'#{tag}: {invalid[0]}')
                    if not found:
                        # Empty JSON can also be an anti-bot response. Do not claim absence.
                        raise FetchError(f'#{tag}: 有効な動画0件。空タグ/アクセス制限/仕様変更を識別できないため停止')
                    results[tag] = list(found.values())
                    log.info('tag=%s fetched=%d', tag, len(found))
                    page.close()
                browser.close()
        except FetchError:
            raise
        except Error as error:
            raise FetchError(f'ブラウザ取得失敗 ({type(error).__name__})') from None
        return results
