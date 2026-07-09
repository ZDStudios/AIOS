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
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sys

PORT = int(os.environ.get("AIOS_HUB_PORT", "8787"))
ROOT = Path(os.environ.get("AIOS_ROOT", Path(__file__).resolve().parent))
DASHBOARD = Path(os.environ.get("AIOS_DASHBOARD", ROOT / "docs" / "dashboard.html"))
ENV_FILE = ROOT / ".env"
CONFIG_FILE = ROOT / "aios.config.yaml"
CHANNEL_KEYS = ["TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
EDITABLE_ENV = ["AIOS_LLM_PROVIDER", "AIOS_LLM_API_KEY", "AIOS_DEFAULT_MODEL",
                "AIOS_LLM_BASE_URL", "OPENCODE_SERVER_PASSWORD"] + CHANNEL_KEYS


def _mask(v: str) -> str:
    if not v:
        return ""
    return v[:4] + "…" + v[-4:] if len(v) > 8 else "*" * len(v)


def read_env_file() -> dict:
    d = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                d[k.strip()] = v.strip()
    return d


def write_env_updates(updates: dict):
    d = read_env_file()
    for k, v in updates.items():
        if v is None:
            continue
        if isinstance(v, str) and ("…" in v or (v and set(v) == {"*"})):
            continue  # ignore masked placeholders the UI echoed back
        d[k] = v
    lines = ["# The AI OS secrets — DO NOT COMMIT (edited via hub)"]
    lines += [f"{k}={v}" for k, v in d.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_aios(*a, background=False):
    cmd = [sys.executable, str(ROOT / "aios.py"), *a]
    # Strip inherited AIOS_LLM_*/model vars so the child setup reads .env (the
    # file we just wrote), not the hub's own launch-time environment.
    env = dict(os.environ)
    for k in ("AIOS_LLM_PROVIDER", "AIOS_LLM_API_KEY", "AIOS_LLM_BASE_URL", "AIOS_DEFAULT_MODEL"):
        env.pop(k, None)
    if background:
        threading.Thread(target=lambda: subprocess.run(cmd, cwd=str(ROOT), env=env,
                         capture_output=True), daemon=True).start()
        return {"ok": True, "started": " ".join(a)}
    r = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
    return {"ok": r.returncode == 0, "out": (r.stdout or r.stderr)[-2000:]}

# Registry of everything the hub knows about.
PEERS = {
    "opencode": os.environ.get("AIOS_OPENCODE_URL", "http://127.0.0.1:4096"),
    "hermes": os.environ.get("AIOS_HERMES_URL", "http://127.0.0.1:9119"),
    "openclaw": os.environ.get("AIOS_OPENCLAW_URL", "http://127.0.0.1:18789"),
    "crewai": os.environ.get("AIOS_CREWAI_URL", "http://127.0.0.1:4788"),
    "claudecode": os.environ.get("AIOS_CLAUDECODE_URL", "http://127.0.0.1:8000"),
    "openclaw-os": os.environ.get("AIOS_OPENCLAWOS_URL", "http://127.0.0.1:18789/plugins/openclawos/"),
}
CLAUDECODE = os.environ.get("AIOS_CLAUDECODE_URL", "http://127.0.0.1:8000").rstrip("/")
OPENCLAW_EMBED = os.environ.get("AIOS_OPENCLAWPROXY_URL", "http://127.0.0.1:8791/")
HERMES_EMBED = os.environ.get("AIOS_HERMESPROXY_URL", "http://127.0.0.1:8792/")
SCHEDULES_FILE = ROOT / ".aios" / "schedules.json"
SYSTEM_PROMPT_FILE = ROOT / ".aios" / "system_prompt.txt"


def read_system_prompt() -> str:
    try:
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


# Chat "targets" the AIOS API exposes as OpenAI-style models.
TARGETS = ["brain", "team", "opencode", "crewai", "claudecode", "all"]

MEMORY_FILE = ROOT / ".aios" / "memory.json"
USAGE_FILE = ROOT / ".aios" / "usage.json"
PROMPTS_FILE = ROOT / ".aios" / "prompts.json"


def _load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_memory() -> list:
    return _load_json(MEMORY_FILE, [])


def bump_usage(target: str):
    u = _load_json(USAGE_FILE, {})
    u[target] = u.get(target, 0) + 1
    # claude-code (subscription) and brain-on-subscription cost $0 in API terms.
    _save_json(USAGE_FILE, u)


def _llm_key() -> str:
    return (os.environ.get("AIOS_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or "sk-aios")


def _models_from(url: str, key: str = "") -> list:
    hdr = {"Authorization": f"Bearer {key}"} if key else {}
    req = urllib.request.Request(url.rstrip("/") + "/models", headers=hdr)
    data = json.loads(urllib.request.urlopen(req, timeout=15).read())
    # OpenAI shape {"data":[{"id":..}]} or a bare list
    items = data.get("data", data) if isinstance(data, dict) else data
    return [m.get("id") for m in items if isinstance(m, dict) and m.get("id")]


def fetch_provider_models() -> dict:
    """List models the active provider serves (your Claude models via claude-code-api, etc.).
    Returns {models, base, error} so the UI can show what happened."""
    base, key = llm_base(), _llm_key()
    out = {"models": [], "base": base, "error": ""}
    try:
        out["models"] = _models_from(base, key)
    except Exception as e:
        out["error"] = str(e)[:200]
    # Fallback: if nothing came back, try claude-code-api directly (common case).
    if not out["models"] and CLAUDECODE.rstrip("/") + "/v1" != base:
        try:
            m = _models_from(CLAUDECODE + "/v1")
            if m:
                out.update(models=m, base=CLAUDECODE + "/v1", error="")
        except Exception:
            pass
    return out


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
        "claudecode": CLAUDECODE + "/v1",  # Claude Pro/Max via claude-code-api
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


def ask_claudecode(message: str, history: list | None = None) -> str:
    """Call claude-code-api's OpenAI-compatible endpoint."""
    msgs = (history or []) + [{"role": "user", "content": message}]
    body = json.dumps({"model": "claude-sonnet-4-5", "messages": msgs}).encode()
    req = urllib.request.Request(CLAUDECODE + "/v1/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return f"⚠️ claude-code-api not reachable ({e}). Start it (`aios start claudecode`) and make sure the `claude` CLI is installed + authenticated."


def route(target: str, message: str, history: list | None = None) -> str:
    history = history or []
    target = (target or "brain").lower()
    bump_usage(target)
    if target in ("brain", "aios", "hub"):
        sys = read_system_prompt() or (
               "You are the AIOS Brain — the orchestrator of The AI OS, which unifies six agents: "
               "opencode (coding), hermes (autonomous), openclaw (channels), CrewAI (multi-agent crews), "
               "claude-code (Claude Code API), and LifeOS (shared skills). Be concise and helpful. Suggest "
               "which agent is best for a task. When a visual answer helps (charts, tables, forms, dashboards), "
               "you may emit OpenUI Lang (https://www.openui.com) which the openclaw-os dashboard renders live.")
        mem = read_memory()
        if mem:  # shared cross-agent memory — every brain reply knows these facts
            sys += "\n\nKnown facts / preferences about the user (remember these):\n" + \
                   "\n".join("- " + str(m) for m in mem[:40])
        return llm_chat(history + [{"role": "user", "content": message}], system=sys)
    if target == "crewai":
        return ask_crewai(message)
    if target == "opencode":
        return ask_opencode(message)
    if target in ("claudecode", "claude-code"):
        return ask_claudecode(message, history)
    if target in ("team", "auto", "merge"):
        return run_team(message, history)
    if target == "all":
        parts = []
        for t in ("brain", "crewai", "opencode", "claudecode"):
            parts.append(f"### {t}\n{route(t, message, history)}")
        return "\n\n".join(parts)
    return f"⚠️ Unknown target '{target}'. Use brain | team | crewai | opencode | claudecode | all."


# --------------------------------------------------------------------------- #
# Unique features: auto-router, arena (A/B), council (consensus), pipeline     #
# --------------------------------------------------------------------------- #
def auto_route(message: str, history: list | None = None) -> dict:
    """Pick the best agent for the message automatically, then answer with it."""
    sysp = ("Classify which AI OS agent should handle the user's request. Reply with ONLY one word: "
            "opencode (writing/running code), crewai (multi-step research/workflows), "
            "claudecode (coding via Claude Code), or brain (general/orchestration). Request:")
    pick = (llm_chat([{"role": "user", "content": message}], system=sysp) or "brain").strip().lower()
    pick = next((t for t in ("opencode", "crewai", "claudecode", "brain") if t in pick), "brain")
    return {"chosen": pick, "reply": route(pick, message, history)}


def run_arena(message: str, targets: list, history: list | None = None) -> dict:
    """Same prompt to 2+ agents/models, side by side, to compare."""
    return {"results": [{"target": t, "reply": route(t, message, history)} for t in targets[:4]]}


def run_council(message: str, targets: list, history: list | None = None) -> dict:
    """Ask several agents, then synthesize a consensus noting agreement/disagreement."""
    results = [{"target": t, "reply": route(t, message, history)} for t in targets[:4]]
    joined = "\n\n".join(f"[{r['target']}]\n{r['reply']}" for r in results)
    consensus = llm_chat([{"role": "user", "content":
                           f"Question: {message}\n\nAnswers from the council:\n{joined}\n\n"
                           "Give one best answer. Note where they agree and flag any disagreement."}],
                         system="You are the council chair for The AI OS. Be decisive and concise.")
    return {"results": results, "consensus": consensus}


def run_pipeline(message: str, steps: list, history: list | None = None) -> dict:
    """Chain agents: each step's output feeds the next (research → code → summarize)."""
    out, cur = [], message
    for t in steps[:6]:
        r = route(t, cur, [])
        out.append({"target": t, "output": r})
        cur = r
    return {"steps": out, "final": cur}


# --------------------------------------------------------------------------- #
# "Team" — a single agent that orchestrates the others (the practical merge)   #
# --------------------------------------------------------------------------- #
AGENT_TOOLS = {
    "opencode": "writing/editing/running code, repos, technical build tasks",
    "crewai": "multi-step research or workflows that benefit from a crew of roles",
    "claudecode": "Claude Code — coding with the Claude Code CLI",
}


def run_team(message: str, history: list | None = None) -> str:
    """One agent, backed by the whole team: the Brain plans, delegates subtasks to
    the specialist agents, then synthesizes one answer. Delegation format the model
    emits: lines like `CALL opencode: <subtask>` (or `ANSWER: ...` to reply directly)."""
    roster = "\n".join(f"- {k}: {v}" for k, v in AGENT_TOOLS.items())
    plan_sys = (
        "You are The AI OS — one assistant backed by a team of specialist agents. "
        "Decide how to handle the user's request. You may delegate subtasks to agents by writing "
        "one directive per line in the form `CALL <agent>: <subtask>`. Available agents:\n" + roster +
        "\nIf you can answer directly with no agent, write `ANSWER: <your answer>`. "
        "Only delegate when it genuinely helps. Output directives only.")
    plan = llm_chat((history or []) + [{"role": "user", "content": message}], system=plan_sys)
    if plan.lstrip().upper().startswith("ANSWER:"):
        return plan.split(":", 1)[1].strip()

    calls = []
    for line in plan.splitlines():
        s = line.strip()
        if s.upper().startswith("CALL "):
            body = s[5:]
            agent, _, sub = body.partition(":")
            agent = agent.strip().lower()
            if agent in AGENT_TOOLS and sub.strip():
                calls.append((agent, sub.strip()))
    if not calls:
        # model didn't delegate cleanly — just answer as the Brain
        return route("brain", message, history)

    results = []
    for agent, sub in calls[:3]:  # cap fan-out
        results.append(f"[{agent}] {sub}\n{route(agent, sub)}")
    synth_sys = ("You are The AI OS. Synthesize a single, clear answer to the user's request from the "
                 "agent results below. Don't mention the internal delegation unless useful.")
    joined = "\n\n".join(results)
    return llm_chat([{"role": "user", "content": f"Request: {message}\n\nAgent results:\n{joined}"}],
                    system=synth_sys)


# --------------------------------------------------------------------------- #
# Automations — schedule prompts to run against an agent on an interval        #
# --------------------------------------------------------------------------- #
def load_schedules() -> list:
    if SCHEDULES_FILE.exists():
        try:
            return json.loads(SCHEDULES_FILE.read_text())
        except Exception:
            return []
    return []


def save_schedules(items: list):
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _scheduler_loop():
    import time as _t
    while True:
        try:
            now = _t.time()
            items = load_schedules()
            changed = False
            for it in items:
                if not it.get("enabled", True):
                    continue
                every = int(it.get("every_minutes", 60)) * 60
                if now - it.get("last_run", 0) >= every:
                    it["last_run"] = now
                    it["last_reply"] = route(it.get("target", "brain"), it.get("prompt", ""))[:2000]
                    changed = True
            if changed:
                save_schedules(items)
        except Exception:
            pass
        _t.sleep(30)


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
            self._send(200, {**PEERS, "openclaw-embed": OPENCLAW_EMBED, "hermes-embed": HERMES_EMBED})
        elif self.path == "/api/schedules":
            self._send(200, load_schedules())
        elif self.path == "/api/system_prompt":
            self._send(200, {"prompt": read_system_prompt()})
        elif self.path == "/api/models":
            self._send(200, fetch_provider_models())
        elif self.path == "/api/memory":
            self._send(200, {"memory": read_memory()})
        elif self.path == "/api/prompts":
            self._send(200, {"prompts": _load_json(PROMPTS_FILE, [])})
        elif self.path == "/api/usage":
            u = _load_json(USAGE_FILE, {})
            free = u.get("claudecode", 0)
            self._send(200, {"usage": u, "total": sum(u.values()), "free_requests": free})
        elif self.path in ("/v1/models", "/api/v1/models"):
            # AIOS as an OpenAI-compatible API: its "models" are the chat targets.
            now = int(time.time())
            self._send(200, {"object": "list", "data": [
                {"id": t, "object": "model", "created": now, "owned_by": "aios"} for t in TARGETS]})
        elif self.path == "/api/config":
            env = read_env_file()
            self._send(200, {
                "provider": env.get("AIOS_LLM_PROVIDER", "openrouter"),
                "model": env.get("AIOS_DEFAULT_MODEL", ""),
                "env": {k: _mask(env.get(k, "")) for k in EDITABLE_ENV},
                "has_key": bool(env.get("AIOS_LLM_API_KEY")),
                "channels": CHANNEL_KEYS,
                "config_text": CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else "",
            })
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
        elif self.path in ("/v1/chat/completions", "/api/v1/chat/completions"):
            # OpenAI-compatible endpoint — POST from any OpenAI SDK / curl.
            msgs = payload.get("messages", [])
            user_msg = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), "")
            history = [m for m in msgs if m.get("role") in ("user", "assistant")][:-1]
            mdl = (payload.get("target") or payload.get("model") or "brain").lower()
            target = mdl if mdl in TARGETS else "brain"
            reply = route(target, user_msg, history)
            now = int(time.time())
            self._send(200, {
                "id": f"aios-{now}", "object": "chat.completion", "created": now,
                "model": target, "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": reply}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
        elif self.path == "/api/env":
            write_env_updates(payload.get("updates", {}))
            res = run_aios("setup", "--non-interactive", "--skip-tools",
                           "--skip-install", "--skip-wire")  # re-render into agents
            self._send(200, {"ok": res["ok"], "saved": True})
        elif self.path == "/api/claude_connect":
            # Point the brain/team/crews at claude-code-api → uses the user's Claude
            # Pro/Max subscription (auth = the local `claude` CLI login, no API key).
            model = "claude-sonnet-4-5"
            authed = True
            try:
                m = json.loads(urllib.request.urlopen(CLAUDECODE + "/v1/models", timeout=6).read())
                ids = [x.get("id") for x in m.get("data", []) if x.get("id")]
                if ids:
                    model = next((i for i in ids if "sonnet" in i.lower()), ids[0])
            except Exception:
                authed = False
            write_env_updates({
                "AIOS_LLM_PROVIDER": "claudecode",
                "AIOS_LLM_BASE_URL": CLAUDECODE + "/v1",
                "AIOS_LLM_API_KEY": "sk-aios-claudecode",
                "AIOS_DEFAULT_MODEL": model,
            })
            run_aios("setup", "--non-interactive", "--skip-tools", "--skip-install", "--skip-wire")
            # Actually try a tiny completion — this reveals whether the `claude` CLI is logged in.
            logged_in, detail = False, ""
            if authed:
                try:
                    b = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}],
                                    "max_tokens": 5}).encode()
                    rq = urllib.request.Request(CLAUDECODE + "/v1/chat/completions", data=b, method="POST",
                                                headers={"Content-Type": "application/json",
                                                         "Authorization": "Bearer sk-aios-claudecode"})
                    urllib.request.urlopen(rq, timeout=45)
                    logged_in = True
                except Exception as e:
                    detail = str(e)[:160]
            self._send(200, {
                "ok": True, "model": model, "reachable": authed, "logged_in": logged_in,
                "note": ("Connected — your Claude subscription is working." if logged_in else
                         "Pointed at claude-code, but the Claude CLI isn't logged in yet. Run "
                         "`aios claude-login` (or `claude setup-token`) in a terminal to authorize your "
                         "Pro/Max account, then chat.")})
        elif self.path == "/api/route_auto":
            self._send(200, auto_route(payload.get("message", ""), payload.get("history", [])))
        elif self.path == "/api/arena":
            self._send(200, run_arena(payload.get("message", ""),
                                      payload.get("targets", ["brain", "claudecode"]),
                                      payload.get("history", [])))
        elif self.path == "/api/council":
            self._send(200, run_council(payload.get("message", ""),
                                        payload.get("targets", ["brain", "crewai", "claudecode"]),
                                        payload.get("history", [])))
        elif self.path == "/api/pipeline":
            self._send(200, run_pipeline(payload.get("message", ""),
                                         payload.get("steps", ["crewai", "opencode", "brain"]),
                                         payload.get("history", [])))
        elif self.path == "/api/memory":
            mem = read_memory()
            op = payload.get("op", "add")
            if op == "add" and payload.get("text"):
                mem.append(payload["text"])
            elif op == "delete":
                mem = [m for i, m in enumerate(mem) if i != payload.get("index")]
            elif op == "clear":
                mem = []
            _save_json(MEMORY_FILE, mem)
            self._send(200, {"ok": True, "memory": mem})
        elif self.path == "/api/prompts":
            items = _load_json(PROMPTS_FILE, [])
            op = payload.get("op", "add")
            if op == "add":
                items.append({"name": payload.get("name", "prompt"), "text": payload.get("text", "")})
            elif op == "delete":
                items = [p for p in items if p.get("name") != payload.get("name")]
            _save_json(PROMPTS_FILE, items)
            self._send(200, {"ok": True, "prompts": items})
        elif self.path == "/api/schedules":
            items = load_schedules()
            op = payload.get("op", "add")
            if op == "add":
                items.append({"id": str(int(time.time() * 1000)), "name": payload.get("name", "task"),
                              "target": payload.get("target", "brain"), "prompt": payload.get("prompt", ""),
                              "every_minutes": int(payload.get("every_minutes", 60)),
                              "enabled": True, "last_run": 0})
            elif op == "delete":
                items = [i for i in items if i.get("id") != payload.get("id")]
            elif op == "toggle":
                for i in items:
                    if i.get("id") == payload.get("id"):
                        i["enabled"] = not i.get("enabled", True)
            save_schedules(items)
            self._send(200, {"ok": True, "schedules": items})
        elif self.path == "/api/config_text":
            try:
                CONFIG_FILE.write_text(payload.get("text", ""), encoding="utf-8")
                self._send(200, {"ok": True})
            except Exception as e:
                self._send(200, {"ok": False, "error": str(e)})
        elif self.path == "/api/system_prompt":
            try:
                SYSTEM_PROMPT_FILE.parent.mkdir(parents=True, exist_ok=True)
                SYSTEM_PROMPT_FILE.write_text(payload.get("prompt", ""), encoding="utf-8")
                self._send(200, {"ok": True})
            except Exception as e:
                self._send(200, {"ok": False, "error": str(e)})
        elif self.path == "/api/action":
            action = payload.get("action")
            svc = payload.get("service")
            if action == "rerender":
                self._send(200, run_aios("setup", "--non-interactive", "--skip-tools",
                                         "--skip-install", "--skip-wire"))
            elif action == "restart":
                run_aios("stop", *( [svc] if svc else ["all"]))
                self._send(200, run_aios("start", *([svc] if svc else ["all"]), background=True))
            elif action == "stop":
                self._send(200, run_aios("stop", *([svc] if svc else ["all"])))
            elif action == "start":
                self._send(200, run_aios("start", *([svc] if svc else ["all"]), background=True))
            else:
                self._send(400, {"error": "unknown action"})
        else:
            self._send(404, {"error": "not found"})


def main():
    threading.Thread(target=_scheduler_loop, daemon=True).start()
    # Bind all interfaces by default so the Windows browser can reach it over WSL.
    host = os.environ.get("AIOS_HUB_HOST", "0.0.0.0")
    srv = ThreadingHTTPServer((host, PORT), Handler)
    print(f"AIOS Hub listening on http://{host}:{PORT}/  (dashboard + interconnect + scheduler)")
    print(f"peers: {json.dumps(PEERS)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
