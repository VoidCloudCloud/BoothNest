# SPDX-License-Identifier: GPL-3.0-only
"""Loopback transport with a per-process credential and origin checks."""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ALLOWED = {
    "get_state", "poll", "heartbeat", "load_dataset", "set_root", "pick_root",
    "check_root", "refresh", "cancel", "get_summary", "get_groups", "get_products",
    "get_product_detail", "get_image", "prefetch_thumbs", "thumb_stats",
    "get_unidentified", "get_duplicates", "export_excel", "export_filtered",
    "open_path", "open_url", "reveal_item", "clear_cache", "app_info",
    "set_preferences", "shutdown", "window_closed",
    "get_items", "set_item_override", "check_duplicate_files", "get_duplicate_check",
    "reveal_verified_file", "export_duplicate_check",
}
MAX_BODY = 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "BoothNest"
    api = None
    ui_dir: Path | None = None
    token = ""
    origin = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        for key, value in {
            "Content-Type": ctype, "Content-Length": str(len(body)),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'nonce-" + self.token + "'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'none'"),
        }.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _discard_oversized_body(self, size):
        # Closing with unread input can reset the socket on Windows and hide
        # the 413 response. Drain ordinary near-limit uploads, but never wait
        # indefinitely or trust an arbitrarily large declared length.
        if size > MAX_BODY * 2:
            return
        deadline = time.monotonic() + 1
        try:
            while size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(min(size, 65536))
                if not chunk:
                    break
                size -= len(chunk)
        except OSError:
            pass
        finally:
            self.connection.settimeout(15)

    def _trusted_host(self):
        if self.headers.get("Host") != self.origin.removeprefix("http://"):
            self._json({"ok": False, "error": "Invalid host"}, 403)
            return False
        return True

    def do_GET(self):
        if not self._trusted_host():
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = (self.ui_dir / "ui.html").read_text(encoding="utf-8")
            body = body.replace("__BOOTH_SESSION_TOKEN__", self.token)
            body = body.replace("<script>", '<script nonce="' + self.token + '">')
            return self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/ping":
            return self._json({"ok": True})
        return self._json({"ok": False, "error": "Use authenticated POST"},
                          405 if path.startswith("/api/") else 404)

    def do_POST(self):
        if not self._trusted_host():
            return
        origin = self.headers.get("Origin")
        if (origin and origin != self.origin) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._json({"ok": False, "error": "Invalid origin"}, 403)
        token = self.headers.get("X-BoothNest-Token", "")
        if not hmac.compare_digest(token.encode("utf-8"), self.token.encode("ascii")):
            return self._json({"ok": False, "error": "Invalid session"}, 403)
        name = urlparse(self.path).path.removeprefix("/api/")
        if not self.path.startswith("/api/") or name not in ALLOWED:
            return self._json({"ok": False, "error": "Unknown method"}, 404)
        if self.headers.get_content_type() != "application/json":
            return self._json({"ok": False, "error": "JSON required"}, 415)
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > MAX_BODY:
                self._discard_oversized_body(n)
                return self._json({"ok": False, "error": "Invalid body size"}, 413)
            if n <= 0:
                return self._json({"ok": False, "error": "Invalid body size"}, 413)
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("args", []), list):
                raise ValueError("args must be a list")
        except (ValueError, UnicodeError, OSError):
            return self._json({"ok": False, "error": "Invalid JSON request"}, 400)
        try:
            res = getattr(self.api, name)(*payload.get("args", []))
            return self._json(res if res is not None else {"ok": True})
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": "参数无效"}, 400)
        except Exception:
            return self._json({"ok": False, "error": "操作失败，请重试或查看任务日志"}, 500)


def make_server(api, ui_dir: Path):
    handler = type("SessionHandler", (Handler,), {
        "api": api, "ui_dir": Path(ui_dir), "token": secrets.token_urlsafe(32),
    })
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    srv.session_token = handler.token
    handler.origin = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, handler.origin + "/"
