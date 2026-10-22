"""Local Artisan chat: python3 chat.py, then open the printed URL."""
import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from backend import LLMClient

class Chat:
    def __init__(self, generate=None, port=8765):
        self.generate = generate if generate is not None else LLMClient()
        self.messages = []
        self.specdecode = False
        self.port = port
        self.lock = Lock()

    def submit(self, text):
        text = text.strip()
        if not text:
            raise ValueError('Enter a message first.')
        command = ' '.join(text.lower().split())
        if command in ('/speculative decoding', '/speculative decoding off'):
            requested = command == '/speculative decoding'
            if requested and not getattr(self.generate, 'supports_specdecode', False):
                raise ValueError('This backend does not expose speculative decoding. Use --backend artisan to control it with slash commands.')
            self.specdecode = requested
            return {'kind': 'notice', 'text': 'Speculative decoding ' + ('enabled.' if self.specdecode else 'disabled.'), 'specdecode': self.specdecode}
        if text.startswith('/'):
            return {'kind': 'notice', 'text': 'Use /speculative decoding or /speculative decoding off.', 'specdecode': self.specdecode}
        pending = self.messages + [{'role': 'user', 'content': text}]
        reply = str(self.generate(pending, specdecode=self.specdecode))
        self.messages = pending + [{'role': 'assistant', 'content': reply}]
        return {'kind': 'assistant', 'text': reply, 'specdecode': self.specdecode}

    def create_server(self):
        chat = self
        page = Path(__file__).parent / 'ui' / 'index.html'

        class Handler(BaseHTTPRequestHandler):
            def respond(self, status, payload, content_type='application/json'):
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if urlsplit(self.path).path == '/':
                    self.respond(200, page.read_bytes(), 'text/html; charset=utf-8')
                elif self.path == '/state':
                    with chat.lock:
                        self.respond(200, {'messages': chat.messages, 'specdecode': chat.specdecode})
                else:
                    self.respond(404, {'error': 'Not found'})

            def do_POST(self):
                if self.path not in ('/chat', '/new-chat'):
                    self.respond(404, {'error': 'Not found'})
                    return
                # Only this local page may submit requests from a browser.
                origin = self.headers.get('Origin')
                allowed = {f'http://127.0.0.1:{chat.port}', f'http://localhost:{chat.port}'}
                if origin not in allowed or self.headers.get_content_type() != 'application/json':
                    self.respond(403, {'error': 'Open the chat using its local URL.'})
                    return
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 < length <= 65536:
                        raise ValueError('Message is too large or empty.')
                    body = json.loads(self.rfile.read(length))
                    if self.path == '/new-chat':
                        with chat.lock:
                            chat.messages.clear()
                        self.respond(200, {'specdecode': chat.specdecode})
                        return
                    text = body.get('text')
                    if not isinstance(text, str):
                        raise ValueError('Message must be text.')
                    with chat.lock:
                        result = chat.submit(text)
                    self.respond(200, result)
                except Exception as error:
                    self.respond(400, {'error': str(error)})

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', self.port), Handler)
        self.port = server.server_port
        return server

    def run(self, dynamic=False):
        if dynamic and sys.platform != 'darwin':
            raise SystemExit('The -d notch mode requires macOS.')
        executable = build_island() if dynamic else None
        try:
            server = self.create_server()
        except OSError as error:
            raise SystemExit(f'Cannot start Artisan on port {self.port}: {error}. Try --port 8766.') from error
        url = f'http://127.0.0.1:{self.port}'
        print(f'Artisan chat → {url}', flush=True)
        if dynamic:
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            process = None
            try:
                process = subprocess.Popen([str(executable), url])
                process.wait()
            except KeyboardInterrupt:
                pass
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait()
                server.shutdown()
                server.server_close()
                worker.join()
        else:
            print('Press Ctrl+C to stop.', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()


def build_island():
    root = Path(__file__).resolve().parent
    source = root / 'native' / 'Island.swift'
    build = root / '.build'
    build.mkdir(exist_ok=True)
    contents = build / 'Artisan Island.app' / 'Contents'
    (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
    executable = contents / 'MacOS' / 'ArtisanIsland'
    with (contents / 'Info.plist').open('wb') as info:
        plistlib.dump({'CFBundleIdentifier': 'local.artisan.island',
                       'CFBundleName': 'Artisan Island', 'CFBundleDisplayName': 'Artisan Island',
                       'CFBundleExecutable': 'ArtisanIsland', 'CFBundlePackageType': 'APPL',
                       'LSUIElement': True, 'NSHighResolutionCapable': True}, info)
    previous = build / 'ArtisanIsland'
    if not executable.exists() and previous.exists() and previous.stat().st_mtime >= source.stat().st_mtime:
        shutil.copy2(previous, executable)
    if not executable.exists() or source.stat().st_mtime > executable.stat().st_mtime:
        print('Building Artisan Island (first launch requires Xcode Command Line Tools)…', flush=True)
        try:
            subprocess.run(['xcrun', 'swiftc', str(source), '-o', str(executable),
                            '-module-cache-path', str(build / 'module-cache'),
                            '-framework', 'AppKit', '-framework', 'WebKit'], check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise SystemExit('Could not build the notch panel. Install Xcode Command Line Tools with xcode-select --install, then retry.') from error
    return executable


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Artisan chat')
    parser.add_argument('-d', '--dynamic-island', action='store_true', help='Run in the macOS notch panel')
    parser.add_argument('--port', type=int, default=8765, help='Local server port (default: 8765)')
    parser.add_argument('--backend', choices=('artisan', 'openai'), default=os.environ.get('LLM_BACKEND', 'artisan'), help='Backend protocol (default: artisan)')
    parser.add_argument('--base-url', default=os.environ.get('LLM_BASE_URL', 'http://127.0.0.1:8000/v1'), help='API base URL, including /v1')
    parser.add_argument('--model', default=os.environ.get('LLM_MODEL', 'artisan'), help='Model ID advertised by the backend')
    args = parser.parse_args()
    try:
        client = LLMClient(base_url=args.base_url, model=args.model, backend=args.backend, api_key=os.environ.get('LLM_API_KEY'))
    except ValueError as error:
        parser.error(str(error))
    Chat(generate=client, port=args.port).run(dynamic=args.dynamic_island)
