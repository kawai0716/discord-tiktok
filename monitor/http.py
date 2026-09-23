import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HTTPFailure(RuntimeError):
    def __init__(self, status, body=b''):
        self.status = status
        self.body = body
        super().__init__(f'HTTP {status}')


def request_json(method, url, payload=None, headers=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = Request(url, data=data, method=method, headers={
        'User-Agent': 'lovely7-monitor/1.0', 'Content-Type': 'application/json', **(headers or {})})
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else None
    except HTTPError as error:
        raise HTTPFailure(error.code, error.read()) from None
    except (URLError, TimeoutError, OSError, ValueError):
        # Do not print request URLs: webhook tokens are part of the URL.
        raise HTTPFailure(0) from None
