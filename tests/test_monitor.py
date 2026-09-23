import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor.collector import parse_item, posts_in_payload
from monitor.discord import DiscordNotifier, payload_for
from monitor.engine import run
from monitor.http import HTTPFailure
from monitor.models import DeliveryError, FetchError, Post
from monitor.rules import extract_hashtags, normalize, parse_config
from monitor.state import GitHubStore, LocalStore, validate_state


def config(rules=None, limit=20):
    return parse_config({'rules': rules or [{'name': 'a', 'allOf': ['lovely7']}], 'maxNotificationsPerRun': limit})


def post(video_id='12345', tags=('lovely7',), created=110):
    return Post(video_id, f'https://www.tiktok.com/@test/video/{video_id}', 'test',
                ' '.join('#' + tag for tag in tags), tags, created)


class MemoryStore:
    def __init__(self):
        self.value = None
        self.saves = 0

    def load(self):
        return copy.deepcopy(self.value)

    def save(self, state):
        self.value = json.loads(json.dumps(state))
        self.saves += 1


class FakeCollector:
    def __init__(self, posts):
        self.posts = posts

    def collect(self, tags):
        return {tag: self.posts for tag in tags}


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, post, rules):
        if self.fail:
            raise DeliveryError('test failure')
        self.sent.append((post.id, rules))


class RulesTest(unittest.TestCase):
    def test_combinations(self):
        c = config([
            {'name': 'single', 'allOf': ['Lovely7']},
            {'name': 'and', 'allOf': ['lovely7', 'birthday']},
            {'name': 'or', 'anyOf': ['lovely7', 'lovelyseven']},
            {'name': 'mixed', 'allOf': ['birthday'], 'anyOf': ['lovely7', 'lovelyseven']},
            {'name': 'two', 'tags': ['lovely7', 'birthday', 'idol'], 'minMatches': 2},
        ])
        for tags, expected in [
            ({'lovely7'}, ['single', 'or']),
            ({'lovely7', 'birthday'}, ['single', 'and', 'or', 'mixed', 'two']),
            ({'lovelyseven', 'birthday'}, ['or', 'mixed']),
            ({'birthday', 'idol'}, ['two']),
            ({'lovely7extra'}, []),
        ]:
            self.assertEqual(c.matching_names(tags), expected)
        self.assertEqual(c.watch_tags, ['birthday', 'idol', 'lovely7', 'lovelyseven'])

    def test_unicode(self):
        self.assertEqual(normalize(' ＃ＬＯＶＥＬＹ７ '), 'lovely7')
        self.assertEqual(extract_hashtags('今日は #Lovely7、#誕生日 #idol🎵 ＃推し活 #cafe\u0301'),
                         {'lovely7', '誕生日', 'idol', '推し活', 'café'})

    def test_invalid(self):
        for row in [{'name': 'bad'}, {'name': 'bad', 'allof': ['a']},
                    {'name': 'bad', 'tags': ['a', '#A'], 'minMatches': 2},
                    {'name': 'bad', 'tags': ['a'], 'minMatches': True},
                    {'name': 'bad', 'tags': ['a']}, {'name': 'bad', 'allOf': ['x y']}]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                config([row])


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.notify = FakeNotifier()
        self.old = post('10000', created=90)
        run(config(), FakeCollector([self.old]), self.notify, self.store, initialize=True, now=100)

    def test_baseline_then_duplicate_across_tags_and_rules(self):
        self.assertEqual(self.notify.sent, [])
        c = config([{'name': 'a', 'allOf': ['lovely7']}, {'name': 'b', 'anyOf': ['lovely7', 'birthday']}])
        run(c, FakeCollector([self.old]), self.notify, self.store, now=100)
        for _ in range(2):
            run(c, FakeCollector([post()]), self.notify, self.store, now=120)
        self.assertEqual(self.notify.sent, [('12345', ['a', 'b'])])

    def test_failure_keeps_outbox_even_when_post_disappears(self):
        self.assertEqual(run(config(), FakeCollector([post()]), FakeNotifier(True), self.store), 1)
        self.assertNotIn('12345', self.store.value['known'])
        run(config(), FakeCollector([self.old]), self.notify, self.store)
        self.assertEqual(self.notify.sent[0][0], '12345')
        self.assertEqual(self.store.value['pending'], {})

    def test_empty_fetch_preserves_state(self):
        before = copy.deepcopy(self.store.value)
        with self.assertRaises(FetchError):
            run(config(), FakeCollector([]), self.notify, self.store)
        self.assertEqual(self.store.value, before)

    def test_dry_run_preserves_state(self):
        before = copy.deepcopy(self.store.value)
        run(config(), FakeCollector([post()]), self.notify, self.store, dry_run=True)
        self.assertEqual(self.store.value, before)
        self.assertEqual(self.notify.sent, [])

    def test_old_unseen_video_is_not_new(self):
        run(config(), FakeCollector([post(created=80)]), self.notify, self.store)
        self.assertEqual(self.notify.sent, [])

    def test_limit_retains_pending(self):
        run(config(limit=1), FakeCollector([post('12345'), post('12346')]), self.notify, self.store)
        self.assertEqual(len(self.notify.sent), 1)
        self.assertEqual(len(self.store.value['pending']), 1)

    def test_config_change_baselines_without_flood(self):
        changed = config([{'name': 'new', 'anyOf': ['lovely7', 'idol']}])
        run(changed, FakeCollector([post()]), self.notify, self.store, now=120)
        self.assertEqual(self.notify.sent, [])
        self.assertIn('12345', self.store.value['known'])

    def test_missing_state_needs_explicit_initialization(self):
        with self.assertRaises(ValueError):
            run(config(), FakeCollector([post()]), self.notify, MemoryStore())

    def test_local_store_round_trip_with_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            store = LocalStore(Path(folder) / 'state.json')
            run(config(), FakeCollector([self.old]), self.notify, store, initialize=True, now=100)
            run(config(), FakeCollector([post()]), FakeNotifier(True), store, now=120)
            self.assertIn('12345', store.load()['pending'])
            run(config(), FakeCollector([self.old]), self.notify, store, now=130)
            self.assertIn('12345', store.load()['known'])
            self.assertEqual(store.load()['pending'], {})

    def test_persistence_failure_stops_before_next_delivery(self):
        original = self.store.save
        calls = 0
        def save(state):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('disk full')
            original(state)
        self.store.save = save
        with self.assertRaises(OSError):
            run(config(), FakeCollector([post(), post('12346')]), self.notify, self.store)
        self.assertEqual(len(self.notify.sent), 1)
        self.assertEqual(len(self.store.value['pending']), 2)


class AdapterTest(unittest.TestCase):
    def test_payload_and_missing_data(self):
        raw = {'id': '12345', 'video': {}, 'author': {'uniqueId': 'test'},
               'desc': '#Lovely7 #誕生日', 'createTime': '1700000000',
               'textExtra': [{'hashtagName': 'idol'}]}
        self.assertEqual(set(parse_item(raw).hashtags), {'lovely7', '誕生日', 'idol'})
        self.assertEqual(len(posts_in_payload({'itemList': [raw, raw]})), 1)
        del raw['desc']
        self.assertIsNone(parse_item(raw))
        self.assertEqual(posts_in_payload({'statusCode': 0, 'itemList': []}), [])

    def test_discord_payload_disables_mentions(self):
        payload = payload_for(post(tags=('everyone',)), ['@everyone'])
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertLess(len(json.dumps(payload, ensure_ascii=False)), 6000)

    @patch('monitor.discord.time.sleep')
    @patch('monitor.discord.request_json')
    def test_rate_limit_then_success(self, request, sleep):
        request.side_effect = [HTTPFailure(429, b'{"retry_after":0.1}'), {'id': 'message'}]
        notify = DiscordNotifier('https://discord.com/api/webhooks/123/test')
        notify.send(post(), ['a'])
        self.assertIn('wait=true', request.call_args.args[1])
        self.assertEqual(request.call_count, 2)

    @patch('monitor.discord.request_json', return_value=None)
    def test_requires_delivery_receipt(self, request):
        with self.assertRaises(DeliveryError):
            DiscordNotifier('https://discord.com/api/webhooks/123/test').send(post(), ['a'])

    def test_corrupt_state_is_not_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            path.write_text('{"initialized":true}')
            with self.assertRaises(ValueError):
                LocalStore(path).load()
            path.write_text('null')
            with self.assertRaises(ValueError):
                LocalStore(path).load()

    @patch.object(GitHubStore, 'api')
    def test_github_initial_state_is_committed_before_branch_exists(self, api):
        state = {'version': 1, 'initialized': True, 'fingerprint': 'hash',
                 'cutoff': 100, 'known': [], 'pending': {}}
        api.side_effect = [{'sha': 'blob'}, {'sha': 'tree'}, {'sha': 'commit'}, {}]
        store = GitHubStore('owner/repo', 'token')
        store.save(state)
        self.assertEqual([call.args[1] for call in api.call_args_list],
                         ['/git/blobs', '/git/trees', '/git/commits', '/git/refs'])
        self.assertEqual(api.call_args_list[-1].args[2]['sha'], 'commit')
        store.save(state)
        self.assertEqual(api.call_count, 4)

    @patch.object(GitHubStore, 'api')
    def test_github_update_uses_prior_sha(self, api):
        store = GitHubStore('owner/repo', 'token')
        store.branch_exists = True
        store.sha = 'previous'
        api.return_value = {'content': {'sha': 'next'}}
        state = {'version': 1, 'initialized': True, 'fingerprint': 'hash',
                 'cutoff': 100, 'known': [], 'pending': {}}
        store.save(state)
        self.assertEqual(api.call_args.args[2]['sha'], 'previous')
        self.assertEqual(store.sha, 'next')

    @patch.object(GitHubStore, 'api')
    def test_github_missing_file_is_not_first_run(self, api):
        api.side_effect = [{}, HTTPFailure(404)]
        with self.assertRaises(ValueError):
            GitHubStore('owner/repo', 'token').load()

    @patch.object(GitHubStore, 'api')
    def test_github_read_error_is_not_first_run(self, api):
        api.side_effect = HTTPFailure(403)
        with self.assertRaises(HTTPFailure):
            GitHubStore('owner/repo', 'token').load()


if __name__ == '__main__':
    unittest.main()
