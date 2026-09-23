import base64
import json
import os
from pathlib import Path
from urllib.parse import quote

from .http import HTTPFailure, request_json


def validate_state(state):
    try:
        def require(condition):
            if not condition:
                raise ValueError('invalid state')
        require(state['version'] == 1 and state['initialized'] is True)
        require(isinstance(state['fingerprint'], str))
        require(type(state['cutoff']) is int and state['cutoff'] > 0)
        require(isinstance(state['known'], list))
        require(all(isinstance(x, str) and x.isdigit() for x in state['known']))
        require(isinstance(state['pending'], dict))
        for key, post in state['pending'].items():
            require(post['id'] == key and key.isdigit())
            require(isinstance(post['hashtags'], list))
            require(all(isinstance(t, str) for t in post['hashtags']))
            require(all(isinstance(post[k], str) for k in ('url', 'username', 'caption')))
            require(type(post['created_at']) is int)
            require(post['url'].startswith('https://www.tiktok.com/@'))
        require(not set(state['known']) & set(state['pending']))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError('状態ファイルが不正です。初期化せず停止します') from None
    return state


def encode(state):
    validate_state(state)
    return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


class LocalStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return None
        return validate_state(json.loads(self.path.read_text(encoding='utf-8')))

    def save(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + '.tmp')
        with temp.open('w', encoding='utf-8') as stream:
            stream.write(encode(state))
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)


class GitHubStore:
    """Contents API SHA acts as an optimistic lock. No force pushes or expiring cache."""
    def __init__(self, repository, token, branch='monitor-state'):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('GITHUB_REPOSITORY が不正です')
        if not token:
            raise ValueError('GH_TOKEN がありません')
        self.base = f'https://api.github.com/repos/{repository}'
        self.headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                        'X-GitHub-Api-Version': '2022-11-28'}
        self.branch = branch
        self.sha = None
        self.branch_exists = False
        self.last_content = None

    def api(self, method, path, data=None):
        return request_json(method, self.base + path, data, self.headers)

    def load(self):
        try:
            self.api('GET', '/git/ref/heads/' + quote(self.branch, safe=''))
            self.branch_exists = True
        except HTTPFailure as error:
            if error.status == 404:
                return None
            raise
        try:
            data = self.api('GET', '/contents/state.json?ref=' + quote(self.branch, safe=''))
        except HTTPFailure as error:
            if error.status == 404:
                raise ValueError('状態ブランチにstate.jsonがありません。復旧が必要です') from None
            raise
        self.sha = data['sha']
        state = validate_state(json.loads(base64.b64decode(data['content'])))
        self.last_content = encode(state).encode()
        return state

    def save(self, state):
        content = encode(state).encode()
        if content == self.last_content:
            return
        if not self.branch_exists:
            # Create the orphan branch with state already present in its first commit.
            blob = self.api('POST', '/git/blobs', {'content': base64.b64encode(content).decode(), 'encoding': 'base64'})
            tree = self.api('POST', '/git/trees', {'tree': [
                {'path': 'state.json', 'mode': '100644', 'type': 'blob', 'sha': blob['sha']}]})
            commit = self.api('POST', '/git/commits', {'message': 'Initialize monitor state', 'tree': tree['sha'], 'parents': []})
            self.api('POST', '/git/refs', {'ref': 'refs/heads/' + self.branch, 'sha': commit['sha']})
            self.branch_exists = True
            self.sha = blob['sha']
        else:
            result = self.api('PUT', '/contents/state.json', {
                'message': 'Update monitor state', 'branch': self.branch,
                'sha': self.sha, 'content': base64.b64encode(content).decode()})
            self.sha = result['content']['sha']
        self.last_content = content
