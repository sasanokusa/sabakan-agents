"""Small real HTTP service used only inside the isolated research fixture."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.request import urlopen


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if sys.argv[1] == 'observer' and self.path == '/probe':
            from probe import probe
            self.reply(200, probe('http://' + os.environ['FRONTEND_ADDRESS'] + ':8080/health'))
            return
        if self.path != '/health':
            self.reply(404, {'status': 'not_found'})
            return
        if sys.argv[1] == 'backend':
            self.reply(200, {'status': 'ready'})
            return
        try:
            config = json.loads(Path('/config/service.json').read_text())
        except (OSError, ValueError):
            self.reply(503, {'status': 'unavailable', 'cause': 'config_parse_error'})
            return
        if not isinstance(config, dict) or config.get('enabled') is not True or config.get('upstream') != 'sabakan':
            self.reply(503, {'status': 'unavailable', 'cause': 'config_invalid'})
            return
        try:
            # The physical address is trusted fixture input, never config or
            # model text. The network has no external route.
            with urlopen('http://' + os.environ['BACKEND_ADDRESS'] + ':8080/health', timeout=0.5) as response:
                dependency = json.load(response)
            if dependency != {'status': 'ready'}:
                raise ValueError('unexpected dependency response')
        except Exception:
            self.reply(503, {'status': 'unavailable', 'cause': 'dependency_unavailable'})
            return
        self.reply(200, {'status': 'ready', 'dependency': 'ready'})

    def reply(self, status, payload):
        data = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
