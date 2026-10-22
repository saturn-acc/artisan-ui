"""HTTP-only LLM adapter; no model, tokenizer, or weights live in this project."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class LLMClient:
    def __init__(self, base_url='http://127.0.0.1:8000/v1', model='artisan',
                 backend='artisan', api_key=None, timeout=120):
        url = urlsplit(base_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use an http(s) API base URL without credentials, query, or fragment.')
        if backend not in ('artisan', 'openai'):
            raise ValueError('Backend must be artisan or openai.')
        if not model.strip():
            raise ValueError('Model ID cannot be empty.')
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.supports_specdecode = backend == 'artisan'
        self.api_key = api_key
        self.timeout = timeout

    def __call__(self, messages, specdecode=False):
        payload = {'model': self.model, 'messages': messages, 'stream': False}
        if self.supports_specdecode:
            payload['specdecode'] = bool(specdecode)
        elif specdecode:
            raise ValueError('This backend does not expose speculative decoding.')
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        request = Request(self.base_url + '/chat/completions',
                          data=json.dumps(payload).encode(), headers=headers, method='POST')
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except HTTPError as error:
            # Display a useful status, without echoing backend bodies that may
            # contain credentials or proxy diagnostics into the chat.
            error.close()
            raise RuntimeError(f'LLM backend returned HTTP {error.code}. Check its model, API key, and server logs.') from None
        except (URLError, TimeoutError):
            raise RuntimeError('Cannot reach the LLM backend. Start the inference server or check --base-url.') from None
        except (ValueError, UnicodeError):
            raise RuntimeError('The LLM backend returned invalid JSON.') from None
        try:
            content = data['choices'][0]['message']['content']
            if not isinstance(content, str):
                raise TypeError
        except (KeyError, IndexError, TypeError):
            raise RuntimeError('The backend must return text in choices[0].message.content.') from None
        return content
