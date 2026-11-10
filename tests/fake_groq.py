"""A tiny local stand-in for Groq's chat endpoint, used only by tests.

Fixture, not a measurement: header names and the 429 body shape follow docs/RESEARCH.md
and are NOT real Groq output. It listens on 127.0.0.1 only.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeGroq:
    def __init__(self):
        self.limit_per_window = 10_000
        self.window_s = 60
        self.reply_text = "Hello [attention-C-001]."
        self.reasoning_text = ""  # when set, reasoning deltas stream before content
        self.delay_s = 0.0  # pause before each content delta
        self.stream_error = None  # when set, sent as an error event after the content
        self.done_line = b"data: [DONE]\n\n"
        self.requests = []  # bodies received by the chat endpoint
        self._window_start = time.monotonic()
        self._count = 0
        self.base_url = None

    def admit(self):
        """True if this request fits the current window; also returns seconds to wait."""
        now = time.monotonic()
        if now - self._window_start >= self.window_s:
            self._window_start, self._count = now, 0
        self._count += 1
        wait = max(1, int(self.window_s - (now - self._window_start) + 0.999))
        return self._count <= self.limit_per_window, wait


def _handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep test output quiet
            pass

        def _json(self, status, payload, headers=None):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self):
            if self.headers.get("Authorization", "").startswith("Bearer "):
                return True
            self._json(401, {"error": {"message": "Invalid API Key", "type": "invalid_request_error"}})
            return False

        def do_GET(self):
            if self.path == "/openai/v1/models" and self._authorised():
                self._json(200, {"data": [{"id": "fake-model"}]})

        def do_POST(self):
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path != "/openai/v1/chat/completions" or not self._authorised():
                return
            fake.requests.append(body)
            ok, wait = fake.admit()
            if not ok:
                limit = fake.limit_per_window
                self._json(429, {"error": {
                    "message": f"Rate limit reached for model `fake-model` in organization "
                               f"`org_fake` on requests per minute (RPM): Limit {limit}, "
                               f"Used {limit}, Requested 1. Please try again in {wait}s.",
                    "type": "requests", "code": "rate_limit_exceeded"}},
                    {"retry-after": str(wait)})
                return
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            for name, value in {
                "x-ratelimit-limit-requests": "1000",
                "x-ratelimit-remaining-requests": str(max(0, 1000 - len(fake.requests))),
                "x-ratelimit-reset-requests": "1m26.4s",
                "x-ratelimit-limit-tokens": "6000",
                "x-ratelimit-remaining-tokens": "5975",
                "x-ratelimit-reset-tokens": "7.66s",
                "set-cookie": "__cf_bm=fixture-cookie; path=/",  # must not be saved
            }.items():
                self.send_header(name, value)
            self.end_headers()

            def send(delta, extra=None):
                chunk = {"id": "chatcmpl-fake", "object": "chat.completion.chunk",
                         "model": body.get("model"),
                         "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                chunk.update(extra or {})
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()

            send({"role": "assistant", "content": ""})
            if fake.reasoning_text:
                for word in fake.reasoning_text.split():
                    send({"reasoning": word + " "})
            third = max(1, len(fake.reply_text) // 3)
            for part in (fake.reply_text[:third], fake.reply_text[third:2 * third],
                         fake.reply_text[2 * third:]):
                time.sleep(fake.delay_s)
                send({"content": part})
            final = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "x_groq": {"id": "req_fake", "usage": {
                         "prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
                         "queue_time": 0.01}}}
            if fake.stream_error:
                self.wfile.write(f"data: {json.dumps({'error': fake.stream_error})}\n\n".encode())
            send({}, final)
            self.wfile.write(fake.done_line)
            self.wfile.flush()

    return Handler


@pytest.fixture
def fake_groq():
    fake = FakeGroq()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    fake.base_url = f"http://127.0.0.1:{server.server_address[1]}/openai/v1"
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield fake
    server.shutdown()
    server.server_close()
