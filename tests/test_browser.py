"""Optional real-Chromium integration tests using synthetic TikTok responses only."""
import json
import os
import unittest
from unittest.mock import patch

from monitor.collector import BrowserCollector
from monitor.models import FetchError


@unittest.skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'RUN_BROWSER_TESTS=1 でブラウザ検証')
class BrowserTest(unittest.TestCase):
    def collect_with_response(self, payload):
        from playwright.sync_api import BrowserContext
        new_page = BrowserContext.new_page
        def fake_page(context, *args, **kwargs):
            page = new_page(context, *args, **kwargs)
            def route_handler(route):
                if '/api/challenge/item_list/' in route.request.url:
                    route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))
                else:
                    route.fulfill(status=200, content_type='text/html', body='''
                    <html><body><script>
                    fetch('/api/challenge/item_list/').then(r => r.json());
                    </script></body></html>''')
            page.route('**/*', route_handler)
            return page
        with patch.object(BrowserContext, 'new_page', fake_page):
            return BrowserCollector(scrolls=0, wait_seconds=1).collect(['lovely7'])

    def test_reads_browser_network_video_metadata(self):
        result = self.collect_with_response({'statusCode': 0, 'itemList': [{
            'id': '12345', 'video': {}, 'author': {'uniqueId': 'example'},
            'desc': '#Lovely7 #birthday', 'createTime': 1700000000,
        }]})
        self.assertEqual(result['lovely7'][0].hashtags, ('birthday', 'lovely7'))

    def test_empty_success_response_is_not_trusted(self):
        with self.assertRaises(FetchError):
            self.collect_with_response({'statusCode': 0, 'itemList': []})

    def test_partial_metadata_does_not_pass_as_success(self):
        with self.assertRaises(FetchError):
            self.collect_with_response({'statusCode': 0, 'itemList': [{'id': '12345', 'video': {}}]})
