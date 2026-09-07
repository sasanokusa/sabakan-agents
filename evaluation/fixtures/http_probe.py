"""Independent HTTP client run in a separate, isolated observer container."""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def probe(url):
    try:
        try:
            response = urlopen(url, timeout=1)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.code
            raw = response.read(4097)
        body = json.loads(raw) if len(raw) <= 4096 else None
        return {'http_status': status, 'body': body,
                'ok': status == 200 and body == {'status': 'ready', 'dependency': 'ready'}}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {'http_status': None, 'body': None, 'ok': False, 'error': type(exc).__name__}


if __name__ == '__main__':
    print(json.dumps(probe(sys.argv[1])))
