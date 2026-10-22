# Artisan UI

Frontend mac UI for LLMs.

A standalone browser chat and native macOS notch interface with a Phthalo Green
gradient, spring animation, slash commands, and an expanding conversation panel.
This repository contains no inference engine, model weights, tokenizer, Torch,
or Transformers dependency. It connects to a separately running LLM server over HTTP.

## Start

Requires Python 3.10+. Browser mode runs on any platform; native notch mode
requires macOS 12+ and Xcode Command Line Tools.

```sh
python3 chat.py          # Browser UI at http://127.0.0.1:8765
python3 chat.py -d       # Native macOS notch UI
```

By default, both connect to the separate Artisan inference API at
`http://127.0.0.1:8000/v1`, using model ID `artisan`. Start that server from the
[Artisan repository](https://github.com/saturn-acc/Artisan) with `python3 server.py`.
The UI can start without a backend; sending a message then reports a connection error.

## Other LLM servers

Use an OpenAI-compatible **Chat Completions** API:

```sh
python3 chat.py -d --backend openai --base-url http://127.0.0.1:1234/v1 --model your-model-id
```

Use the model ID and base URL from your server. For authenticated services, set
`LLM_API_KEY` in your shell. The key stays in the Python process and is never sent
to browser code. `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_BACKEND` also supply defaults;
explicit CLI arguments override them. `.env` files are ignored by Git but are not
automatically loaded.

The adapter sends `model`, `messages`, and `stream: false` to
`POST /chat/completions`, and reads `choices[0].message.content`. Responses are
currently non-streaming text. Conversations are held in memory until restart;
**New chat** clears that history.

With `--backend artisan`, slash commands set the `specdecode` boolean sent with
the next inference request. Commands themselves never generate a message.
With `--backend openai`, no Artisan-specific field is sent; speculative decoding
must be configured on that server, and enabling it through the slash menu reports
that it is unsupported. The frontend flag does not implement speculative decoding.

## macOS notch mode

```sh
python3 chat.py -d
```

Hover over the notch at the top center of the display to open the chat, then
click the message field to type. The green gradient panel grows to fit replies;
long conversations scroll. Move the pointer outside the panel to hide it
completely, even while a reply is processing. Your draft and conversation are
preserved for the next hover. There is no collapsed strip or menu-bar icon.

The notch layout uses Coucou's 640-point width, compact icon toolbar, and inset
chat card, with Artisan's Phthalo Green gradient. Chat starts at 240 points tall
and expands with message content up to 900 points (or the available screen height
minus 80 points), then scrolls. **Chat** focuses the composer, **+** starts a new
conversation, the upward chevron hides the panel, and the power icon quits.

The panel expands from the notch with a damped spring, then folds back with a
0.34-second easing curve. Motion timing is inspired by
[Coucou's island animation](https://github.com/louis-cfm/coucou/blob/main/NotchBuddy/Sources/App/IslandRootView.swift):
0.5-second spring response, 0.72 damping, and a brief delay before content appears.
The native wrapper keeps chat layout stable during the shape change and respects
macOS Reduce Motion.

Use **+** for a new chat and the power icon to quit notch mode and stop its local server.
Press Escape in the input to hide the panel (Escape closes the slash menu first).
Type `/` to change speculative decoding; notch mode has no persistent status label.
The browser chat is still available at the printed URL while notch mode runs.

The first notch launch compiles a small AppKit/WebKit wrapper using Apple's
Xcode Command Line Tools. If needed, install them with `xcode-select --install`.
No extra Python package is required for the native panel. Compiled files are
cached under `.build/`. Notch mode requires macOS 12 or later; displays without a
notch use an invisible hover area at the top center.

If another chat is already using the port, stop it first or choose another:

```sh
python3 chat.py -d --port 8766
```

## Project layout

- `chat.py`: local UI server, conversation state, and native launcher.
- `backend.py`: HTTP adapter for Artisan and OpenAI-compatible servers.
- `ui/`: browser interface and assets, reused inside the notch.
- `native/Island.swift`: AppKit/WebKit notch host.
- `tests/`: isolated HTTP integration tests; no model downloads required.

```sh
python3 -m unittest discover -s tests -v
```

The panel geometry and motion are inspired by
[Coucou](https://github.com/louis-cfm/coucou), with Artisan's own theme and UI.
