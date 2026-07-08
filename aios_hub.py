#!/usr/bin/env python3
"""
AIOS Hub — the unified brain + interconnect for The AI OS.

One dashboard to talk to EVERYTHING (opencode, hermes, openclaw, CrewAI) and the
bus that lets the agents reach each other. Pure Python standard library.

Started by `aios start hub`. Config comes from the environment (aios injects it):
  AIOS_HUB_PORT, AIOS_LLM_PROVIDER, AIOS_LLM_API_KEY, AIOS_LLM_BASE_URL,
  AIOS_DEFAULT_MODEL, AIOS_OPENCODE_URL, AIOS_HERMES_URL, AIOS_OPENCLAW_URL,
  AIOS_CREWAI_URL, AIOS_OPENCLAWOS_URL, AIOS_OPENCODE_DIR, AIOS_BUN, AIOS_DASHBOARD
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("AIOS_HUB_PORT", "8787"))
ROOT = Path(os.environ.get("AIOS_ROOT", Path(__file__).resolve().parent))
DASHBOARD = Path(os.environ.get("AIOS_DASHBOARD", ROOT / "docs" / "dashboard.html"))

# Registry of everything the hub knows about.
PEERS = {
    "opencode": os.environ.get("AIOS_OPENCODE_URL", "http://127.0.0.1:4096"),
    "hermes": os.environ.get("AIOS_HERMES_URL", "http://127.0.0.1:9119"),
    "openclaw": os.environ.get("AIOS_OPENCLAW_URL", "http://127.0.0.1:18789"),
    "crewai": os.environ.get("AIOS_CREWAI_URL", "http://127.0.0.1:4788"),
    "openclaw-os": os.environ.get("AIOS_OPENCLAWOS_URL", "http://127.0.0.1:18789/plugins/openclawos/"),
}


# --------------------------------------------------------------------------- #
# LLM (OpenAI-compatible) — the "AIOS Brain"                                   #
# --------------------------------------------------------------------------- #
def llm_base() -> str:
    b = os.environ.get("AIOS_LLM_BASE_URL", "").strip()
    if b:
        return b.rstrip("/")
    prov = os.environ.get("AIOS_LLM_PROVIDER", "openrouter").lower()
    return {
        "openrouter": "https://openrouter.ai/api/v1",
        "openai": "https://api.openai.com/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    }.get(prov, "https://openrouter.ai/api/v1")


def llm_chat(messages: list, system: str | None = None) -> str:
    key = os.environ.get("AIOS_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY") \
        or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return "⚠️ No model API key set. Run `aios setup --force` and enter your key, then restart."
    model = os.environ.get("AIOS_DEFAULT_MODEL", "anthropic/claude-opus-4.6")
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = json.dumps({"model": model, "messages": msgs}).encode()
    req = urllib.request.Request(
        llm_base() + "/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                 "HTTP-Referer": "https://github.com/ZDStudios/AIOS", "X-Title": "The AI OS"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return f"⚠️ LLM error {e.code}: {e.read().decode(errors='replace')[:400]}"
    except Exception as e:
        return f"⚠️ LLM error: {e}"


# --------------------------------------------------------------------------- #
# Per-agent adapters                                                          #
# --------------------------------------------------------------------------- #
def post_json(url: str, payload: dict, timeout=180) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ask_crewai(message: str) -> str:
    try:
        out = post_json(PEERS["crewai"].rstrip("/") + "/chat", {"message": message})
        return out.get("reply") or out.get("error") or json.dumps(out)
    except Exception as e:
        return f"⚠️ CrewAI service not reachable ({e}). Is it running? `aios start crewai`"


def ask_opencode(message: str) -> str:
    """Run a one-shot opencode prompt via its CLI (headless)."""
    bun = os.environ.get("AIOS_BUN") or shutil.which("bun")
    ocdir = os.environ.get("AIOS_OPENCODE_DIR", "")
    if not (bun and ocdir and Path(ocdir).exists()):
        return "⚠️ opencode not available (bun/opencode dir missing)."
    try:
        r = subprocess.run([bun, "src/index.ts", "run", message], cwd=ocdir,
                           capture_output=True, text=True, timeout=240, env=os.environ)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return out[-6000:] if out else "(opencode returned no output)"
    except subprocess.TimeoutExpired:
        return "⚠️ opencode timed out (240s)."
    except Exception as e:
        return f"⚠️ opencode error: {e}"


def route(target: str, message: str, history: list | None = None) -> str:
    history = history or []
    target = (target or "brain").lower()
    if target in ("brain", "aios", "hub"):
        sys = ("You are the AIOS Brain — the orchestrator of The AI OS, which unifies five agents: "
               "opencode (coding), hermes (autonomous), openclaw (channels), CrewAI (multi-agent crews), "
               "and LifeOS (shared skills). Be concise and helpful. You can suggest which agent is best "
               "for a task. When a visual answer helps (charts, tables, forms, dashboards), you may emit "
               "OpenUI Lang (https://www.openui.com) which the openclaw-os dashboard renders as a live app.")
        return llm_chat(history + [{"role": "user", "content": message}], system=sys)
    if target == "crewai":
        return ask_crewai(message)
    if target == "opencode":
        return ask_opencode(message)
    if target == "all":
        parts = []
        for t in ("brain", "crewai", "opencode"):
            parts.append(f"### {t}\n{route(t, message, history)}")
        return "\n\n".join(parts)
    return f"⚠️ Unknown target '{target}'. Use brain | crewai | opencode | all."


# --------------------------------------------------------------------------- #
# Status                                                                       #
# --------------------------------------------------------------------------- #
def ping(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=1.2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        pass
    try:  # fall back to a fast TCP connect
        from urllib.parse import urlparse
        u = urlparse(url)
        with socket.socket() as s:
            s.settimeout(0.5)
            return s.connect_ex((u.hostname, u.port or (443 if u.scheme == "https" else 80))) == 0
    except Exception:
        return False


def services_status() -> dict:
    # Ping every peer concurrently so one down service can't slow the dashboard.
    from concurrent.futures import ThreadPoolExecutor
    names = list(PEERS)
    with ThreadPoolExecutor(max_workers=len(names) or 1) as ex:
        ups = list(ex.map(ping, [PEERS[n] for n in names]))
    out = {n: {"url": PEERS[n], "up": u} for n, u in zip(names, ups)}
    out["hub"] = {"url": f"http://127.0.0.1:{PORT}/", "up": True}
    return out


# --------------------------------------------------------------------------- #
# HTTP server                                                                  #
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet; aios captures stdout separately

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        if self.path in ("/", "/index.html", "/dashboard"):
            if DASHBOARD.exists():
                self._send(200, DASHBOARD.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            else:
                self._send(200, "<h1>AIOS Hub</h1><p>dashboard.html not found</p>", "text/html")
        elif self.path == "/api/services":
            self._send(200, services_status())
        elif self.path == "/api/peers":
            self._send(200, PEERS)
        elif self.path == "/health":
            self._send(200, {"ok": True, "service": "aios-hub"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            payload = {}
        if self.path in ("/api/chat", "/api/relay"):
            target = payload.get("target") or payload.get("to") or "brain"
            message = payload.get("message", "")
            history = payload.get("history", [])
            reply = route(target, message, history)
            self._send(200, {"target": target, "reply": reply})
        else:
            self._send(404, {"error": "not found"})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"AIOS Hub listening on http://127.0.0.1:{PORT}/  (dashboard + interconnect)")
    print(f"peers: {json.dumps(PEERS)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
