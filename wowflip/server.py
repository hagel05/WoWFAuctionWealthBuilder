"""Small HTTP API for sync helpers on other PCs (standard library only).

    GET  /                  latest.html report, for a browser
    GET  /health            {"ok": true, "feed_age_minutes": ...}
    GET  /api/v1/feed       the latest flip feed (JSON)
    POST /api/v1/bankroll   {"characters": {"Name - Realm": {"gold": copper, "seen": epoch}}}

If WOWFLIP_API_TOKEN is set, /api/ calls need `Authorization: Bearer <token>`.
Meant for a home network; do not expose it to the internet.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from wowflip.bankroll import apply_game_bankroll
from wowflip.config import Config, GOLD
from wowflip.feed import feed_age_minutes, feed_path, load_feed

log = logging.getLogger("wowflip")
MAX_BODY = 256 * 1024


def make_handler(cfg: Config):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "wowflip"

        def log_message(self, fmt, *args):
            log.info("api %s - %s", self.address_string(), fmt % args)

        def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, data, extra: dict | None = None):
            self._send(code, json.dumps(data, separators=(",", ":")).encode(), extra=extra)

        def _authorized(self) -> bool:
            if not cfg.api_token:
                return True
            got = self.headers.get("Authorization", "")
            ok = hmac.compare_digest(got.encode(), f"Bearer {cfg.api_token}".encode())
            if not ok:
                self._json(401, {"error": "missing or wrong API token"})
            return ok

        def _feed(self):
            path = feed_path(cfg)
            if not path.is_file():
                return None
            return load_feed(path)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/health":
                try:
                    feed = self._feed()
                except ValueError:
                    feed = None
                age = round(feed_age_minutes(feed), 1) if feed else None
                return self._json(200, {"ok": True, "has_feed": feed is not None, "feed_age_minutes": age})
            if path == "/api/v1/feed":
                if not self._authorized():
                    return
                try:
                    feed = self._feed()
                except ValueError as exc:
                    return self._json(500, {"error": str(exc)})
                if feed is None:
                    return self._json(503, {"error": "no scan has finished yet"})
                etag = f'"{feed["generated_at"]}"'
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                return self._json(200, feed, {"ETag": etag})
            if path in ("/", "/index.html"):
                report = cfg.report_dir / "latest.html"
                if report.is_file():
                    return self._send(200, report.read_bytes(), "text/html; charset=utf-8")
                return self._send(200, b"<p>No scan has finished yet.</p>", "text/html; charset=utf-8")
            self._json(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path != "/api/v1/bankroll":
                return self._json(404, {"error": "not found"})
            if not self._authorized():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return self._json(413, {"error": "body too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                chars = body["characters"]
                if not isinstance(chars, dict):
                    raise TypeError
            except (ValueError, KeyError, TypeError):
                return self._json(400, {"error": 'expected {"characters": {...}}'})
            with lock:
                gold = apply_game_bankroll(cfg, chars)
                current = cfg.bankroll_copper() / GOLD
            self._json(200, {"updated": gold is not None, "bankroll_gold": round(current, 4)})

    return Handler


def serve(cfg: Config) -> None:
    httpd = ThreadingHTTPServer((cfg.server.host, cfg.server.port), make_handler(cfg))
    where = f"http://{cfg.server.host}:{cfg.server.port}"
    log.info("API listening on %s%s", where, "" if cfg.api_token else " (no API token set)")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
