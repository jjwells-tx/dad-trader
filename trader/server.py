"""Local app server: the rung sheet (rendered live from the database) plus the /chat endpoint.

  python -m trader serve                       http://localhost:8000
  python -m trader serve --port 8001           what the EC2 install runs; httpd/nginx proxies /chat to it

Binds to 127.0.0.1 only. On the server, the web server's password login sits in front of it.
"""
import json, os, threading, time
from collections import deque
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from . import chat, report

MAX_BODY = 64 * 1024
RATE = (30, 60)          # at most 30 chat requests per 60 seconds, across everyone


class RateLimit:
    def __init__(self, n, per):
        self.n, self.per, self.hits, self.lock = n, per, deque(), threading.Lock()

    def ok(self):
        with self.lock:
            now = time.monotonic()
            while self.hits and now - self.hits[0] > self.per:
                self.hits.popleft()
            if len(self.hits) >= self.n:
                return False
            self.hits.append(now)
            return True


def make_handler(db_path, rounding="nearest", ask=chat.ask):
    limit = RateLimit(*RATE)

    class Handler(BaseHTTPRequestHandler):
        server_version = "rung-sheet"

        def _send(self, code, body, ctype):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj), "application/json")

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                plans = report.build_plan(db_path, rounding=rounding)
                self._send(200, report.render_html(plans, date.today().isoformat(), rounding, report.positions_info(db_path)),
                           "text/html; charset=utf-8")
            elif path == "/healthz":
                self._send(200, "ok", "text/plain")
            else:
                self._send(404, "Not found", "text/plain")

        def do_POST(self):
            if urlsplit(self.path).path != "/chat":
                return self._send(404, "Not found", "text/plain")
            # Same-origin only: a JSON content type forces a CORS preflight, which we never approve.
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(415, dict(error="Expected JSON."))
            origin, host = self.headers.get("Origin"), self.headers.get("X-Forwarded-Host") or self.headers.get("Host")
            if origin and urlsplit(origin).netloc != host:
                return self._json(403, dict(error="Cross-origin requests aren't allowed."))
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= MAX_BODY:
                return self._json(413, dict(error="Conversation too long. Clear the chat and start over."))
            if not limit.ok():
                return self._json(429, dict(error="Too many questions at once. Wait a minute and try again."))
            try:
                msgs = json.loads(self.rfile.read(n)).get("messages")
                self._json(200, ask(msgs, chat.build_context(db_path)))
            except chat.ChatError as e:
                self._json(e.status, dict(error=str(e)))
            except (ValueError, AttributeError):
                self._json(400, dict(error="Bad request."))
            except Exception as e:                       # keep the server up; log the details
                self.log_error("chat failed: %r", e)
                self._json(500, dict(error="Something went wrong on the server."))

    return Handler


def serve(db_path="data/trader.db", host="127.0.0.1", port=8000, rounding="nearest"):
    httpd = ThreadingHTTPServer((host, port), make_handler(db_path, rounding))
    print(f"Rung sheet with chat at http://{'localhost' if host == '127.0.0.1' else host}:{port}  (Ctrl-C to stop)")
    if not os.environ.get("GEMINI_API_KEY"):
        print("WARN: GEMINI_API_KEY isn't set; the page works but chat will say it isn't set up.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
