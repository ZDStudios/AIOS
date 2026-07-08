#!/usr/bin/env python3
"""
AIOS embed proxy — a tiny reverse proxy that strips frame-blocking headers so a
target dashboard (openclaw's control-UI) can be embedded in an <iframe> inside
the AIOS Hub. Proxies HTTP path-for-path (so the SPA's absolute URLs work) and
relays WebSocket upgrades. Pure Python standard library.

Env:  AIOS_PROXY_PORT (default 8791), AIOS_PROXY_TARGET (default http://127.0.0.1:18789)
"""
from __future__ import annotations

import os
import select
import socket
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORT = int(os.environ.get("AIOS_PROXY_PORT", "8791"))
TARGET = os.environ.get("AIOS_PROXY_TARGET", "http://127.0.0.1:18789").rstrip("/")
_t = urlparse(TARGET)
THOST, TPORT = _t.hostname or "127.0.0.1", _t.port or 80

# Headers we drop so the page can be framed and isn't locked to its own origin.
STRIP = {"x-frame-options", "content-security-policy", "content-security-policy-report-only",
         "cross-origin-opener-policy", "cross-origin-embedder-policy"}
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
       "te", "trailers", "transfer-encoding", "upgrade", "content-length"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _is_ws(self):
        return self.headers.get("Upgrade", "").lower() == "websocket"

    def _proxy_ws(self):
        # Open a raw connection to the target and replay the client's upgrade
        # request, then pipe bytes both ways until either side closes.
        try:
            up = socket.create_connection((THOST, TPORT), timeout=10)
        except Exception:
            self.send_error(502, "ws upstream unreachable")
            return
        req = f"{self.command} {self.path} {self.protocol_version}\r\n"
        for k, v in self.headers.items():
            req += f"{k}: {v}\r\n"
        req += "\r\n"
        up.sendall(req.encode("latin-1", "ignore"))
        cli = self.connection
        cli.setblocking(False)
        up.setblocking(False)
        socks = [cli, up]
        try:
            while True:
                r, _, x = select.select(socks, [], socks, 60)
                if x:
                    break
                for s in r:
                    try:
                        data = s.recv(65536)
                    except Exception:
                        return
                    if not data:
                        return
                    (up if s is cli else cli).sendall(data)
        finally:
            try:
                up.close()
            except Exception:
                pass

    def _proxy_http(self):
        body = None
        if "Content-Length" in self.headers:
            body = self.rfile.read(int(self.headers["Content-Length"]))
        url = TARGET + self.path
        req = urllib.request.Request(url, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() in ("host", "content-length"):
                continue
            req.add_header(k, v)
        req.add_header("Host", f"{THOST}:{TPORT}")
        try:
            resp = urllib.request.urlopen(req, timeout=60)
            status, headers, payload = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, headers, payload = e.code, e.headers, e.read()
        except Exception as e:
            self.send_error(502, f"proxy error: {e}")
            return
        self.send_response(status)
        for k, v in headers.items():
            if k.lower() in STRIP or k.lower() in HOP:
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except Exception:
            pass

    def _handle(self):
        if self._is_ws():
            self._proxy_ws()
        else:
            self._proxy_http()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _handle


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"AIOS embed proxy: http://127.0.0.1:{PORT}/  →  {TARGET}  (frame headers stripped)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
