"""Serve the redesigned UI and local OpenStrandStudio renderer on loopback only.

Run: python site/serve_native.py
Qt rendering remains on the main thread; HTTP workers enqueue bounded jobs.
"""
import argparse
import json
import queue
from pathlib import Path
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from jev_settings import JevSettings
from native_renderer import NativeRenderer, validate
from workflow import Workflow

PORT = 5174
ROOT = Path(__file__).resolve().parent
# The private chatgpt.site copy and the GitHub Pages deployment (.github/workflows/site.yml).
HOSTED_ORIGINS = {'https://mxn-strand-studio.topspin-tech-0568.chatgpt.site', 'https://ysetbon.github.io'}
JOBS = queue.Queue(maxsize=3)
JEV = JevSettings()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'dist'), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def allowed(self):
        # Reject rebinding and cross-origin drive-by requests.
        hosts = {f'127.0.0.1:{PORT}', f'localhost:{PORT}'}
        origins = HOSTED_ORIGINS | {f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}
        return self.headers.get('Host') in hosts and self.headers.get('Origin', '') in origins | {''}

    def end_headers(self):
        origin = self.headers.get('Origin')
        if self.allowed() and origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def reply(self, code, data):
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        if not self.allowed():
            return self.reply(403, {'error': 'Origin not allowed'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if not self.allowed():
            return self.reply(403, {'error': 'Origin not allowed'})
        if urlsplit(self.path).path == '/api/health':
            return self.reply(200, {'renderer': 'OpenStrandStudio', 'animals': True})
        if urlsplit(self.path).path == '/api/jev':
            return self.reply(200, JEV.status())
        return super().do_GET()

    def do_POST(self):
        if not self.allowed():
            return self.reply(403, {'error': 'Origin not allowed'})
        if self.path not in ('/api/render', '/api/workflow', '/api/jev'):
            return self.reply(404, {'error': 'Not found'})
        try:
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('Content-Type must be application/json')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                raise ValueError('Invalid request size')
            request = json.loads(self.rfile.read(size))
            if self.path == '/api/jev':
                return self.reply(200, JEV.update(request))
            if self.path == '/api/render':
                request = validate(request)
            response = queue.Queue(maxsize=1)
            JOBS.put_nowait((self.path, request, response))
        except queue.Full:
            return self.reply(503, {'error': 'Renderer is busy. Try again shortly.'})
        except (ValueError, TypeError) as error:
            return self.reply(400, {'error': str(error)})
        try:
            code, result = response.get(timeout=600)
            self.reply(code, result)
        except queue.Empty:
            self.reply(504, {'error': 'Rendering timed out. Try a smaller grid.'})


def main():
    renderer = NativeRenderer()
    workflow = Workflow(renderer, JEV)
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'MxN native workspace: http://127.0.0.1:{PORT}/', flush=True)
    print('Rendering with OpenStrandStudio; press Ctrl+C to stop.', flush=True)
    try:
        while True:
            renderer.app.processEvents()
            try:
                path, request, response = JOBS.get(timeout=.02)
            except queue.Empty:
                continue
            try:
                response.put((200, workflow.start(request) if path == '/api/render' else workflow.run(request)))
            except ValueError as error:
                response.put((400, {'error': str(error)}))
            except Exception as error:
                print(f'Render failed: {error}', flush=True)
                response.put((500, {'error': 'OpenStrandStudio could not render this pattern. Check the local renderer log.'}))
            finally:
                JOBS.task_done()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
