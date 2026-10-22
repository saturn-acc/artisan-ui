import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from backend import LLMClient
from chat import Chat


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.fail = False
        test = self

        class Backend(BaseHTTPRequestHandler):
            def do_POST(self):
                test.requests.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length']))), self.headers.get('Authorization')))
                payload = {'choices': [{'message': {'content': 'Model reply'}}]}
                self.send_response(503 if test.fail else 200)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *_):
                pass

        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        self.start_server(self.backend)
        self.client = LLMClient(f'http://127.0.0.1:{self.backend.server_port}/v1', api_key='test-only-key')
        self.chat = Chat(generate=self.client, port=0)
        self.ui = self.chat.create_server()
        self.start_server(self.ui)
        self.url = f'http://127.0.0.1:{self.ui.server_port}'

    def start_server(self, server):
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def post(self, path, payload):
        request = Request(self.url + path, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Origin': self.url})
        with urlopen(request) as response:
            return json.load(response)

    def test_command_history_reset_and_key_boundary(self):
        self.assertTrue(self.post('/chat', {'text': '/speculative decoding'})['specdecode'])
        self.assertEqual(self.requests, [])
        self.assertEqual(self.post('/chat', {'text': 'Hello'})['text'], 'Model reply')
        path, body, auth = self.requests[-1]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(auth, 'Bearer test-only-key')
        self.assertTrue(body['specdecode'])
        self.assertEqual(body['messages'], [{'role': 'user', 'content': 'Hello'}])
        self.post('/chat', {'text': 'Continue'})
        self.assertEqual(len(self.requests[-1][1]['messages']), 3)
        self.post('/chat', {'text': '/speculative decoding off'})
        self.post('/new-chat', {})
        with urlopen(self.url + '/state') as response:
            state = response.read().decode()
        self.assertNotIn('test-only-key', state)
        self.assertEqual(json.loads(state), {'messages': [], 'specdecode': False})
        self.post('/chat', {'text': 'Fresh'})
        self.assertEqual(len(self.requests[-1][1]['messages']), 1)
        self.assertFalse(self.requests[-1][1]['specdecode'])

    def test_openai_payload_has_no_custom_field(self):
        client = LLMClient(self.client.base_url, model='example', backend='openai')
        self.assertEqual(client([{'role': 'user', 'content': 'Hello'}]), 'Model reply')
        body = self.requests[-1][1]
        self.assertEqual(set(body), {'model', 'messages', 'stream'})
        with self.assertRaises(ValueError):
            Chat(generate=client).submit('/speculative decoding')

    def test_error_does_not_save_failed_turn(self):
        self.fail = True
        with self.assertRaises(HTTPError) as result:
            self.post('/chat', {'text': 'Retry me'})
        result.exception.close()
        self.assertEqual(self.chat.messages, [])

    def test_notch_html_and_origin_check(self):
        with urlopen(self.url + '/?island=1&inset=37') as response:
            self.assertIn(b'setIslandOpen', response.read())
        request = Request(self.url + '/chat', data=b'{"text":"bad origin"}', headers={'Content-Type':'application/json','Origin':'https://example.com'})
        with self.assertRaises(HTTPError) as result:
            urlopen(request)
        self.assertEqual(result.exception.code, 403)
        result.exception.close()
        self.assertEqual(self.requests, [])
