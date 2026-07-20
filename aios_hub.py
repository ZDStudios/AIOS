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

import copy
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aios_brain as brain    # noqa: E402  durable state: memory, tasks, flows, audit
import aios_sec as sec        # noqa: E402  the gate in front of full-control mode
import aios_tools as tools    # noqa: E402  shell + channel/skill catalogs
import aios_updates as updates  # noqa: E402  agent-supervised dependency updates

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
    env["AIOS_NO_UPDATE_CHECK"] = "1"  # never git-pull during a hub-triggered restart
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
TARGETS = ["brain", "team", "opencode", "crewai", "claudecode", "fabric", "all"]

MEMORY_FILE = ROOT / ".aios" / "memory.json"
USAGE_FILE = ROOT / ".aios" / "usage.json"
PROMPTS_FILE = ROOT / ".aios" / "prompts.json"
WIDGETS_FILE = ROOT / ".aios" / "widgets.json"  # generative-UI canvas any agent can edit


def _load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_memory() -> list:
    """All memories, newest first (the Memory page). Recall on a *turn* uses
    active_recall() instead — searching beats dumping the whole file."""
    return [m["text"] for m in brain.mem_all(200)]


def migrate_memory_once():
    """Old builds kept memory in .aios/memory.json. Fold it into SQLite once."""
    if not MEMORY_FILE.exists():
        return
    try:
        for item in _load_json(MEMORY_FILE, []):
            brain.mem_add(str(item), kind="fact", source="memory.json")
        MEMORY_FILE.rename(MEMORY_FILE.with_suffix(".json.migrated"))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Active Memory — a memory sub-agent that fires on EVERY turn, not just at      #
# session start. Recall is a free FTS query; extraction is one small async LLM  #
# call, so remembering never slows down or bills the turn the user is waiting   #
# on.                                                                          #
# --------------------------------------------------------------------------- #
def active_memory_on() -> bool:
    return os.environ.get("AIOS_ACTIVE_MEMORY", "1") == "1"


def active_recall(message: str, k: int = 6) -> str:
    if not active_memory_on():
        return ""
    hits = brain.mem_search(message, k=k)
    if not hits:
        return ""
    return ("\n\nRelevant things you already know about this user or system "
            "(recalled for this turn):\n" + "\n".join("- " + h["text"] for h in hits))


_EXTRACT_SYS = (
    "You maintain an agent's long-term memory. From the exchange below, extract "
    "durable facts worth remembering across sessions: user preferences, names, "
    "environment details, decisions, credentials' *locations* (never values). "
    "Ignore anything transient or specific to this one task. "
    "Output one fact per line, no bullets, no preamble. Output NOTHING if there is "
    "nothing durable — that is the common case.")


def active_extract(user_msg: str, reply: str):
    """Fire-and-forget: learn from the turn without blocking it."""
    if not active_memory_on():
        return
    try:
        text = llm_chat([{"role": "user",
                          "content": f"User: {user_msg[:2000]}\n\nAssistant: {reply[:2000]}"}],
                        system=_EXTRACT_SYS)
        for line in (text or "").splitlines():
            fact = line.strip().lstrip("-•* ").strip()
            if 8 < len(fact) < 300 and not fact.upper().startswith("NOTHING"):
                brain.mem_add(fact, kind="fact", source="active-memory")
    except Exception:
        pass


def remember_async(user_msg: str, reply: str):
    threading.Thread(target=active_extract, args=(user_msg, reply), daemon=True).start()


# --------------------------------------------------------------------------- #
# Self-improving skill loop — after a task that actually *did* something, judge #
# whether it taught a reusable procedure and, if so, write a SKILL.md that      #
# every agent mounts. This is the closed loop: the system gets faster at the    #
# things you actually ask it to do.                                            #
# --------------------------------------------------------------------------- #
def skill_learn_on() -> bool:
    return os.environ.get("AIOS_SKILL_LEARN", "1") == "1"


_LEARN_SYS = (
    "You are the Curator: an agent that turns completed tasks into reusable skills.\n"
    "Given a task, the commands that were run, and the outcome, decide whether this "
    "taught a GENERALIZABLE procedure worth saving — something that would help next time "
    "a similar task appears.\n\n"
    "Reply with EXACTLY 'SKIP' if it was trivial, one-off, purely conversational, or failed.\n"
    "Otherwise reply with a Markdown skill file and nothing else, in this shape:\n"
    "---\nname: <kebab-case-name>\ndescription: <one line, when to use this>\n---\n\n"
    "# <Title>\n\n## When to use\n...\n\n## Steps\n1. ...\n\n## Commands\n```sh\n...\n```\n")


def maybe_learn_skill(user_msg: str, reply: str, ran: list[str]):
    """Only fires when the turn ran commands — a conversation teaches no procedure."""
    if not (skill_learn_on() and ran):
        return
    try:
        ctx = (f"Task: {user_msg[:1500]}\n\nCommands run:\n" + "\n".join(f"$ {c}" for c in ran) +
               f"\n\nOutcome:\n{reply[:1500]}")
        out = (llm_chat([{"role": "user", "content": ctx}], system=_LEARN_SYS) or "").strip()
        if not out or out.upper().startswith("SKIP") or "---" not in out:
            return
        name = ""
        for line in out.splitlines():
            if line.lower().startswith("name:"):
                name = line.split(":", 1)[1].strip()
                break
        if not name:
            return
        tools.learn_skill(name, out, task=user_msg[:400])
        _log_event("learned", "curator", f"Learned a new skill: {name}")
    except Exception:
        pass


def learn_async(user_msg: str, reply: str, ran: list[str]):
    threading.Thread(target=maybe_learn_skill, args=(user_msg, reply, ran), daemon=True).start()


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


# --------------------------------------------------------------------------- #
# Agent modes — composable behavioural overlays from upstream projects:          #
#   caveman  (JuliusBrussee/caveman)  — trims how much the agent SAYS            #
#   ponytail (DietrichGebert/ponytail) — trims how much the agent BUILDS         #
# State persists so toggles survive restarts. Both can be on at once.            #
# --------------------------------------------------------------------------- #
MODES_FILE = ROOT / ".aios" / "modes.json"


def modes_state() -> dict:
    st = _load_json(MODES_FILE, {})
    return {k: {"enabled": bool(st.get(k, {}).get("enabled", False)),
                "level": st.get(k, {}).get("level", "full")}
            for k in tools.AGENT_MODES}


def set_mode(name: str, enabled: bool, level: str = "full") -> dict:
    if name not in tools.AGENT_MODES:
        return modes_state()
    st = modes_state()
    lv = level if level in tools.AGENT_MODES[name]["levels"] else "full"
    st[name] = {"enabled": bool(enabled), "level": lv}
    _save_json(MODES_FILE, st)
    return st


def modes_prompt_suffix() -> str:
    """Every enabled mode's overlay, concatenated. They compose cleanly because
    one governs prose style and the other governs engineering decisions."""
    return "".join(tools.mode_overlay(n, s["level"])
                   for n, s in modes_state().items() if s["enabled"])


# --------------------------------------------------------------------------- #
# Fabric — run any of the 255 danielmiessler/fabric patterns through AIOS's own  #
# model path. A pattern is a system prompt; the user's text is the input.        #
# --------------------------------------------------------------------------- #
def run_fabric(pattern: str, text: str, target: str = "brain") -> str:
    system = tools.fabric_pattern_system(pattern)
    if system is None:
        return f"⚠️ Unknown fabric pattern '{pattern}'. See the Patterns view for the full list."
    system += modes_prompt_suffix()
    # Route through claude-code when the brain is on the subscription, else the LLM.
    if target in ("claudecode", "claude-code"):
        return ask_claudecode(text, [{"role": "system", "content": system}])
    return llm_chat([{"role": "user", "content": text}], system=system)


TOOL_PROTOCOL = (
    "\n\nFULL CONTROL: you control the computer AIOS is installed on. To run a shell "
    "command, emit a line of exactly this form:\n"
    "RUN: <command>\n"
    "Emit up to 3 RUN lines, then stop and wait — the outputs are fed back to you and you "
    "continue. When you have the final answer, reply in normal prose with no RUN lines. "
    "Only reach for the shell when the task actually needs the machine (inspecting files, "
    "checking a service, git, installing packages). Never guess at output you could just go "
    "and read.")


def brain_system_prompt(message: str) -> str:
    sysp = read_system_prompt() or (
        "You are the AIOS Brain — the orchestrator of The AI OS, which unifies six agents: "
        "opencode (coding), hermes (autonomous), openclaw (channels), CrewAI (multi-agent crews), "
        "claude-code (Claude Code API), and LifeOS (shared skills). Be concise and helpful. Suggest "
        "which agent is best for a task.")
    sysp += ("\n\nGENERATIVE UI (OpenUI): when a visual answer helps (charts, tables, forms, dashboards, "
             "buttons), emit a fenced ```ui block containing a full, self-contained HTML document "
             "(inline CSS/JS, no external URLs). The hub renders it live and interactive inside the chat. "
             "Use the page's theme via CSS variables like var(--accent), var(--bg), var(--text). This is "
             "OpenUI-style generative UI (https://www.openui.com).")
    if tools.full_control():
        sysp += TOOL_PROTOCOL
        sysp += (
            "\n\nRESTYLING THIS DASHBOARD: if the user asks to change how the Control Room "
            f"looks — colours, text size, spacing/density, which sidebar items show, or adding "
            f"a live panel — do it through the hub API, NEVER by editing docs/dashboard.html "
            f"(editing the file can break the UI; the API cannot, and `reset` undoes it).\n"
            f"  RUN: curl -s http://127.0.0.1:{PORT}/api/dashboard\n"
            f"  RUN: curl -s -X POST http://127.0.0.1:{PORT}/api/dashboard -H 'Content-Type: application/json' "
            "-d '{\"op\":\"set\",\"vars\":{\"--accent\":\"#4f9dff\"},\"scale\":1.1,\"density\":\"compact\"}'\n"
            "Ops: set (vars/css/scale/density) · nav (hidden/order) · panel (add/del/clear, "
            "slot top|chat|sidebar, self-contained HTML styled with var(--accent) etc.) · "
            "reset (what: all|vars|css|panels|nav). Full reference: the `dashboard-designer` skill.")
    sysp += active_recall(message)      # Active Memory: relevant context, every turn
    sysp += modes_prompt_suffix()       # caveman / ponytail overlays when toggled on
    return sysp


def _parse_runs(text: str) -> list[str]:
    return [l.strip()[4:].strip() for l in (text or "").splitlines()
            if l.strip().upper().startswith("RUN:") and len(l.strip()) > 4]


# One request == one thread (ThreadingHTTPServer), so the handler can pick up
# which commands the Brain ran on this turn without threading it through route().
_TL = threading.local()


def commands_this_turn() -> list[str]:
    return list(getattr(_TL, "ran", []))


def run_brain(message: str, history: list, max_rounds: int = 4) -> tuple[str, list[str]]:
    """The Brain with a body: think → RUN → read output → think again."""
    sysp = brain_system_prompt(message)
    msgs = list(history) + [{"role": "user", "content": message}]
    ran: list[str] = []
    _TL.ran = ran
    out = ""
    for round_i in range(max_rounds):
        out = llm_chat(msgs, system=sysp)
        cmds = _parse_runs(out)
        if not cmds or not tools.full_control():
            return out, ran
        results = []
        for c in cmds[:3]:
            r = tools.shell(c, actor="brain")
            ran.append(c)
            body = (r["out"] or "") + (f"\n[stderr]\n{r['err']}" if r["err"] else "")
            if r.get("blocked"):
                body = r["err"]
            results.append(f"$ {c}\n(exit {r['code']})\n{body[:3000] or '(no output)'}")
        last = round_i == max_rounds - 1
        nudge = ("\n\nThat was the last command you may run. Give the final answer now, "
                 "with no RUN lines." if last else "")
        msgs += [{"role": "assistant", "content": out},
                 {"role": "user", "content": "Command results:\n\n" + "\n\n".join(results) + nudge}]
    out = llm_chat(msgs, system=sysp)  # force a prose answer after the last round
    return "\n".join(l for l in out.splitlines() if not l.strip().upper().startswith("RUN:")), ran


def route(target: str, message: str, history: list | None = None) -> str:
    history = history or []
    target = (target or "brain").lower()
    _TL.ran = []  # never attribute a previous turn's commands to this one
    bump_usage(target)
    if target in ("brain", "aios", "hub"):
        reply, ran = run_brain(message, history)
        if ran:
            reply += "\n\n---\n🔧 Ran: " + ", ".join(f"`{c}`" for c in ran[:6])
        return reply
    if target == "crewai":
        return ask_crewai(message)
    if target == "opencode":
        return ask_opencode(message)
    if target in ("claudecode", "claude-code"):
        return ask_claudecode(message, history)
    if target == "fabric":
        # "pattern: text"  →  run that fabric pattern; else summarize by default.
        pat, _, txt = message.partition(":")
        if txt.strip():
            return run_fabric(pat.strip(), txt.strip())
        return run_fabric("summarize", message)
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
# /dry — estimate tokens + cost before actually running a request             #
# --------------------------------------------------------------------------- #
_PRICING = {"ts": 0.0, "map": {}}


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)  # ~4 chars/token (rough, English)


def _model_pricing(model: str):
    """Per-token USD pricing for the active model (OpenRouter exposes it on /models)."""
    if os.environ.get("AIOS_LLM_PROVIDER", "openrouter").lower() != "openrouter":
        return None
    if time.time() - _PRICING["ts"] > 600 or not _PRICING["map"]:
        try:
            data = json.loads(urllib.request.urlopen(llm_base() + "/models", timeout=10).read())
            m = {}
            for it in data.get("data", []):
                p = it.get("pricing") or {}
                try:
                    m[it.get("id")] = {"prompt": float(p.get("prompt", 0) or 0),
                                       "completion": float(p.get("completion", 0) or 0)}
                except Exception:
                    pass
            _PRICING.update(map=m, ts=time.time())
        except Exception:
            pass
    return _PRICING["map"].get(model)


def dry_run(target: str, message: str, history: list | None = None) -> dict:
    history = history or []
    target = (target or "brain").lower()
    sysp = read_system_prompt() or ("You are the AIOS Brain, orchestrator of six agents. "
                                    "Be concise and helpful." * 3)
    mem = read_memory()
    ctx = (sysp + "\n" + "\n".join(str(m.get("content", "")) for m in history)
           + "\n" + "\n".join(str(x) for x in mem) + "\n" + message)
    in_tok = estimate_tokens(ctx)
    out_tok = 600
    model = os.environ.get("AIOS_DEFAULT_MODEL", "(unset)")
    prov = os.environ.get("AIOS_LLM_PROVIDER", "openrouter").lower()
    # multi-agent modes call the model several times
    mult = {"arena": 2, "team": 2, "council": 4, "pipeline": 3, "all": 4}.get(target, 1)
    free = prov == "claudecode"
    cost, priced, note = 0.0, False, ""
    if free:
        note = "Runs on your Claude Pro/Max subscription — $0 API cost."
    else:
        pr = _model_pricing(model)
        if pr:
            cost = (in_tok * pr["prompt"] + out_tok * pr["completion"]) * mult
            priced = True
        else:
            note = "No public pricing for this model — token estimate only."
    return {"target": target, "model": model, "provider": prov, "agents": mult,
            "input_tokens": in_tok, "est_output_tokens": out_tok * mult,
            "total_tokens": (in_tok + out_tok) * mult,
            "free": free, "priced": priced, "est_cost_usd": round(cost, 6), "note": note}


# --------------------------------------------------------------------------- #
# Watchdog — if an agent goes down, restart it; if that fails, an agent debugs #
# --------------------------------------------------------------------------- #
HEALTH_FILE = ROOT / ".aios" / "health_events.json"
WATCH = ["opencode", "hermes", "openclaw", "crewai", "claudecode"]
_wd = {"seen_up": {}, "last_restart": {}}


def _log_event(kind: str, svc: str, msg: str):
    ev = _load_json(HEALTH_FILE, [])
    ev.insert(0, {"ts": time.time(), "kind": kind, "service": svc, "message": str(msg)[:2000]})
    _save_json(HEALTH_FILE, ev[:60])


def _service_logs(svc: str, n: int = 40) -> str:
    return (run_aios("logs", svc, "-n", str(n)).get("out") or "")[-3000:]


def _diagnose(svc: str, logtail: str) -> str:
    """Ask a healthy agent to debug the crashed one."""
    q = (f"The AI OS service '{svc}' stopped responding and an automatic restart did not fix it.\n"
         f"Log tail:\n\n{logtail}\n\n"
         "In at most 3 bullets: the likely root cause, and the exact command to fix it.")
    try:
        helper = "opencode" if ping(PEERS.get("opencode", "")) else "brain"
        return route(helper, q)
    except Exception as e:
        return f"(diagnosis unavailable: {e})"


def _watchdog_loop():
    if os.environ.get("AIOS_WATCHDOG", "1") != "1":
        return
    interval = int(os.environ.get("AIOS_WATCHDOG_INTERVAL", "45"))
    time.sleep(20)  # let the stack finish booting before we judge it
    while True:
        try:
            for svc in WATCH:
                url = PEERS.get(svc)
                if not url:
                    continue
                if ping(url):
                    _wd["seen_up"][svc] = time.time()
                    continue
                # Only heal services we've actually seen alive (never auto-start disabled ones)
                if not _wd["seen_up"].get(svc):
                    continue
                if time.time() - _wd["last_restart"].get(svc, 0) < 180:
                    continue  # rate-limit: no restart storms
                _wd["last_restart"][svc] = time.time()
                _log_event("down", svc, f"{svc} stopped responding — auto-restarting…")
                run_aios("restart", svc)
                time.sleep(20)
                if ping(url):
                    _log_event("healed", svc, f"{svc} is back up (automatic restart).")
                else:
                    diag = _diagnose(svc, _service_logs(svc))
                    _log_event("failed", svc, f"Restart didn't fix {svc}. Agent diagnosis:\n{diag}")
        except Exception:
            pass
        time.sleep(interval)


# --------------------------------------------------------------------------- #
# Claude login from the dashboard (interactive CLI session over HTTP)          #
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Live dashboard customization — agents restyle the Control Room through an API, #
# never by editing dashboard.html. Overrides live server-side in one JSON doc    #
# the page applies on top of the active theme, so a bad instruction is undone    #
# with `reset` instead of a broken file. Panels are OpenUI: arbitrary agent HTML #
# rendered in the same sandboxed iframes the chat/canvas widgets use.            #
# --------------------------------------------------------------------------- #
DASH_FILE = ROOT / ".aios" / "dashboard.json"
DASH_DEFAULT = {"vars": {}, "css": "", "scale": 1.0, "density": "normal",
                "nav": {"hidden": [], "order": []}, "panels": [], "updated": 0}
DASH_SLOTS = ["top", "chat", "sidebar"]

_VAR_OK = re.compile(r"^--[A-Za-z0-9_-]{1,40}$")
# CSS can't execute script in a <style>, but it CAN beacon out via url(http…) and
# @import. Agents already own the machine, so this isn't a privilege boundary —
# it's to stop a careless instruction from silently phoning home.
_CSS_BAD = re.compile(r"</\s*style|@import|url\(\s*['\"]?\s*(https?:|//)", re.I)


def dashboard_cfg() -> dict:
    # deepcopy, not {**DASH_DEFAULT}: a shallow copy shares the nested `vars`/`nav`
    # dicts with the module-level default, so writing a var would mutate the
    # defaults themselves and `reset` would restore the very values it should clear.
    cfg = copy.deepcopy(DASH_DEFAULT)
    cfg.update(_load_json(DASH_FILE, {}))
    for k, v in DASH_DEFAULT.items():  # heal older/partial files
        cfg.setdefault(k, copy.deepcopy(v))
    return cfg


def _clean_var(k: str, v) -> tuple[str, str] | None:
    k = str(k).strip()
    if not k.startswith("--"):
        k = "--" + k.lstrip("-")
    if not _VAR_OK.match(k):
        return None
    val = str(v).strip()
    # A value containing } or < would break out of the rule we inject it into.
    if not val or len(val) > 200 or any(c in val for c in "}<>;{"):
        return None
    return k, val


def dashboard_update(payload: dict) -> dict:
    cfg = dashboard_cfg()
    op = (payload.get("op") or "set").lower()
    rejected = []

    if op == "reset":
        what = payload.get("what", "all")
        if what == "all":
            cfg = copy.deepcopy(DASH_DEFAULT)
        else:
            cfg[what] = copy.deepcopy(DASH_DEFAULT.get(what, ""))
    elif op == "set":
        for k, v in (payload.get("vars") or {}).items():
            cleaned = _clean_var(k, v)
            if cleaned:
                cfg["vars"][cleaned[0]] = cleaned[1]
            else:
                rejected.append(str(k))
        if "css" in payload:
            css = str(payload["css"] or "")[:20000]
            if _CSS_BAD.search(css):
                rejected.append("css (contains @import, remote url(), or </style>)")
            else:
                cfg["css"] = css
        if "scale" in payload:
            try:
                cfg["scale"] = max(0.7, min(1.6, float(payload["scale"])))
            except (TypeError, ValueError):
                rejected.append("scale")
        if payload.get("density") in ("normal", "compact", "comfortable"):
            cfg["density"] = payload["density"]
    elif op == "nav":
        if isinstance(payload.get("hidden"), list):
            cfg["nav"]["hidden"] = [str(x)[:40] for x in payload["hidden"]][:40]
        if isinstance(payload.get("order"), list):
            cfg["nav"]["order"] = [str(x)[:40] for x in payload["order"]][:40]
    elif op == "panel":
        act = (payload.get("action") or "add").lower()
        if act == "add":
            pid = payload.get("id") or f"p{int(time.time() * 1000) % 10**9}"
            panel = {"id": str(pid)[:40],
                     "title": str(payload.get("title", "panel"))[:80],
                     "html": str(payload.get("html", ""))[:200000],
                     "slot": payload.get("slot") if payload.get("slot") in DASH_SLOTS else "top",
                     "height": max(60, min(1200, int(payload.get("height", 220) or 220))),
                     "by": str(payload.get("by", "agent"))[:40]}
            cfg["panels"] = [p for p in cfg["panels"] if p["id"] != panel["id"]] + [panel]
            cfg["panels"] = cfg["panels"][-24:]
        elif act in ("del", "delete", "remove"):
            cfg["panels"] = [p for p in cfg["panels"] if p["id"] != str(payload.get("id"))]
        elif act == "clear":
            cfg["panels"] = []
    else:
        return {"ok": False, "error": f"unknown op '{op}'", "config": cfg}

    cfg["updated"] = time.time()
    _save_json(DASH_FILE, cfg)
    brain.audit(payload.get("by", "agent"), "dashboard." + op,
                json.dumps({k: v for k, v in payload.items() if k != "html"})[:400])
    return {"ok": True, "config": cfg, "rejected": rejected}


# --------------------------------------------------------------------------- #
# Supervised updates — watch every bundled project's upstream, have an AGENT     #
# review what changed, then apply only what's safe (and roll back if the         #
# service doesn't come back healthy).                                            #
# --------------------------------------------------------------------------- #
PENDING_FILE = ROOT / ".aios" / "pending_updates.json"


def _ask_agent(target: str, message: str, system: str) -> str:
    """Adapter so aios_updates can consult an agent without importing the hub."""
    if target == "opencode":
        return ask_opencode(f"{system}\n\n{message}")
    return llm_chat([{"role": "user", "content": message}], system=system)


def pending_updates() -> list:
    return _load_json(PENDING_FILE, [])


def _health_url_for(svc: str) -> str:
    return {"opencode": PEERS.get("opencode", ""), "hermes": PEERS.get("hermes", ""),
            "openclaw": PEERS.get("openclaw", ""), "crewai": PEERS.get("crewai", "") + "/health",
            "claudecode": PEERS.get("claudecode", "") + "/health"}.get(svc, "")


def scan_updates(auto: bool = True) -> list:
    """Check upstreams, get an agent verdict for anything behind, optionally apply."""
    found = []
    for u in updates.check_all():
        if not u.get("behind"):
            continue
        u["review"] = updates.review(u, _ask_agent)
        u["reviewed_at"] = time.time()
        v = u["review"]["verdict"]
        _log_event("update", u["name"],
                   f"{u['name']}: {u.get('ahead_by', '?')} commits behind — agent verdict {v}. "
                   f"{u['review']['why'][:180]}")
        # Content-tier projects (prompts/skills only, nothing executes) may self-apply
        # when an agent says SAFE. Service-tier always waits for you.
        auto_ok = (auto and v == "SAFE" and u["tier"] == "content"
                   and os.environ.get("AIOS_AUTO_APPLY", "1") == "1")
        if auto_ok:
            res = updates.apply(u["name"], health_url=_health_url_for(u["name"]),
                                log=lambda m: _log_event("update", u["name"], m))
            u["applied"] = res
            _log_event("healed" if res.get("ok") else "failed", u["name"],
                       f"auto-applied {u['name']} → {res.get('sha')}" if res.get("ok")
                       else f"auto-apply failed: {res.get('error')}")
            if res.get("ok"):
                tools._FAB_CACHE = None  # patterns may have changed
                continue  # applied — nothing left pending
        found.append(u)
    _save_json(PENDING_FILE, found)
    return found


def _updates_loop():
    if os.environ.get("AIOS_SUPERVISED_UPDATES", "1") != "1":
        return
    every = int(os.environ.get("AIOS_UPDATE_INTERVAL", "21600"))  # 6h
    time.sleep(90)  # let the stack settle before the first scan
    while True:
        try:
            scan_updates(auto=True)
            updates.prune_backups()
        except Exception as e:
            _log_event("failed", "updates", f"update scan error: {e}")
        time.sleep(every)


class _LoginSession:
    proc = None
    master = None
    out = ""
    lock = threading.Lock()


_login = _LoginSession()
_ANSI = __import__("re").compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r")


def _claude_bin():
    return shutil.which("claude") or shutil.which("claude.cmd")


def claude_login_start(mode: str = "setup-token") -> dict:
    claude = _claude_bin()
    if not claude:
        return {"ok": False, "error": "`claude` CLI not found on PATH."}
    if _login.proc and _login.proc.poll() is None:
        return {"ok": True, "already": True}
    with _login.lock:
        _login.out = ""
    args = [claude] + ([mode] if mode else [])
    try:
        if os.name != "nt":
            import pty
            m, s = pty.openpty()
            _login.master = m
            _login.proc = subprocess.Popen(args, stdin=s, stdout=s, stderr=s,
                                           env=dict(os.environ), close_fds=True)
            os.close(s)

            def _rd():
                while True:
                    try:
                        d = os.read(m, 4096)
                    except OSError:
                        break
                    if not d:
                        break
                    with _login.lock:
                        _login.out += d.decode(errors="replace")
            threading.Thread(target=_rd, daemon=True).start()
        else:
            _login.master = None
            _login.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, bufsize=1,
                                           env=dict(os.environ))

            def _rd():
                for line in _login.proc.stdout:
                    with _login.lock:
                        _login.out += line
            threading.Thread(target=_rd, daemon=True).start()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def claude_login_input(text: str) -> dict:
    if not (_login.proc and _login.proc.poll() is None):
        return {"ok": False, "error": "no login session running"}
    try:
        data = (text or "") + "\n"
        if _login.master is not None:
            os.write(_login.master, data.encode())
        else:
            _login.proc.stdin.write(data)
            _login.proc.stdin.flush()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def claude_login_state() -> dict:
    with _login.lock:
        raw = _login.out[-8000:]
    running = bool(_login.proc and _login.proc.poll() is None)
    urls = __import__("re").findall(r"https?://[^\s\"'<>]+", raw)
    return {"output": _ANSI.sub("", raw), "running": running,
            "exit": (_login.proc.poll() if _login.proc else None),
            "url": urls[-1] if urls else ""}


def claude_login_stop() -> dict:
    if _login.proc and _login.proc.poll() is None:
        try:
            _login.proc.kill()
        except Exception:
            pass
    return {"ok": True}


def claude_status() -> dict:
    """Is claude-code-api up, and is the Claude CLI actually authenticated?"""
    st = {"service_up": False, "version": "", "logged_in": False, "model": "", "error": ""}
    try:
        h = json.loads(urllib.request.urlopen(CLAUDECODE + "/health", timeout=6).read())
        st["service_up"] = True
        st["version"] = h.get("claude_version", "")
    except Exception as e:
        st["error"] = f"claude-code-api not reachable — run `aios start claudecode` ({e})"
        return st
    model = "claude-sonnet-4-5"
    try:
        ids = _models_from(CLAUDECODE + "/v1")
        if ids:
            model = next((i for i in ids if "sonnet" in i.lower()), ids[0])
    except Exception:
        pass
    st["model"] = model
    try:  # cold start of the claude CLI is slow — be generous
        b = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 16}).encode()
        rq = urllib.request.Request(CLAUDECODE + "/v1/chat/completions", data=b, method="POST",
                                    headers={"Content-Type": "application/json"})
        urllib.request.urlopen(rq, timeout=180)
        st["logged_in"] = True
    except Exception as e:
        st["error"] = f"Claude CLI not authenticated (or timed out): {str(e)[:200]}"
    return st


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


def migrate_schedules_once():
    """Fold the old .aios/schedules.json automations into the Task Brain."""
    if not SCHEDULES_FILE.exists():
        return
    try:
        for it in load_schedules():
            brain.task_add(name=it.get("prompt", "automation")[:60] or "automation",
                           kind="agent", target=it.get("target", "brain"),
                           prompt=it.get("prompt", ""),
                           every_minutes=int(it.get("every_minutes", 60)),
                           enabled=bool(it.get("enabled", True)))
        SCHEDULES_FILE.rename(SCHEDULES_FILE.with_suffix(".json.migrated"))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Task Brain — ONE scheduler for cron jobs, agent prompts, and background CLI   #
# processes, all backed by SQLite. Every run is recorded, so a task that fails  #
# at 3am leaves evidence instead of a silent gap.                              #
# --------------------------------------------------------------------------- #
def run_task(t: dict) -> tuple[str, str]:
    """Execute one Task Brain task. Returns (status, output)."""
    kind = (t.get("kind") or "agent").lower()
    if kind == "shell":
        r = tools.shell(t.get("command", ""), actor=f"task:{t['name']}")
        return ("ok" if r["ok"] else "error"), (r["out"] or r["err"])[:4000]
    if kind == "flow":
        fid = int(t.get("command") or 0)
        if not brain.flow_get(fid):
            return "error", f"flow {fid} not found"
        threading.Thread(target=run_flow, args=(fid,), daemon=True).start()
        return "ok", f"started flow {fid}"
    reply = route(t.get("target", "brain"), t.get("prompt", ""))
    return "ok", reply[:4000]


def _taskbrain_loop():
    while True:
        try:
            now = time.time()
            for t in brain.task_list():
                if not brain.task_due(t, now):
                    continue
                started = time.time()
                brain.task_update(t["id"], last_run=started)  # claim before running
                try:
                    status, output = run_task(t)
                except Exception as e:
                    status, output = "error", str(e)[:2000]
                brain.task_update(t["id"], last_status=status, last_output=output[:4000])
                brain.run_add(t["id"], started, status, output)
        except Exception:
            pass
        time.sleep(20)


# --------------------------------------------------------------------------- #
# TaskFlow — durable multi-step flows. State is committed after every step, so  #
# a flow interrupted by a crash or a restart resumes at its cursor instead of   #
# replaying (and re-billing) the work it already finished.                     #
# --------------------------------------------------------------------------- #
def run_flow(fid: int) -> dict:
    f = brain.flow_get(fid)
    if not f:
        return {"ok": False, "error": "flow not found"}
    steps, state, i = f["spec"], f["state"], f["cursor"]
    brain.flow_commit(fid, cursor=i, status="running", state=state, note="resumed" if i else "started")
    carry = state.get("_last", "")
    while i < len(steps):
        step = steps[i]
        agent = step.get("agent", "brain")
        prompt = step.get("prompt", "")
        if carry:
            prompt = f"{prompt}\n\nInput from the previous step:\n{carry}"
        try:
            out = route(agent, prompt)
        except Exception as e:
            brain.flow_commit(fid, cursor=i, status="error", state=state,
                              note=f"step {i} failed", error=str(e)[:500])
            _log_event("flow", "taskflow", f"Flow '{f['name']}' failed at step {i + 1}: {e}")
            return {"ok": False, "error": str(e), "step": i}
        carry = out
        state[f"step{i}"] = {"agent": agent, "output": out[:4000]}
        state["_last"] = out[:4000]
        i += 1
        # Commit after every step — this is what makes the flow durable.
        brain.flow_commit(fid, cursor=i, status="running" if i < len(steps) else "done",
                          state=state, note=f"step {i} of {len(steps)}")
    _log_event("flow", "taskflow", f"Flow '{f['name']}' completed ({len(steps)} steps).")
    return {"ok": True, "flow": fid, "steps": len(steps), "result": carry}


def resume_flows():
    """On boot, pick up whatever was in flight when the hub last died."""
    for fid in brain.flow_resumable():
        f = brain.flow_get(fid)
        if f and f["cursor"] < len(f["spec"]):
            _log_event("flow", "taskflow",
                       f"Resuming flow '{f['name']}' at step {f['cursor'] + 1}/{len(f['spec'])}.")
            threading.Thread(target=run_flow, args=(fid,), daemon=True).start()


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
        # Never `*`: full-control mode means a readable response is a readable machine.
        for k, v in sec.cors_headers(self.headers).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _gate(self) -> bool:
        """Authenticate before anything else. Loopback is trusted; everyone else
        brings a token; cross-origin always brings a token (CSRF)."""
        ok, why = sec.check(path=self.path, method=self.command,
                            client_ip=self.client_address[0], headers=self.headers)
        if not ok:
            brain.audit("http", "denied", f"{self.command} {self.path.split('?')[0]} "
                                          f"from {self.client_address[0]}: {why}", ok=False)
            self._send(401, {"error": "unauthorized", "reason": why})
        return ok

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        if not self._gate():
            return
        # Match on the path alone; the browser reaches the dashboard at /?token=…,
        # and a few endpoints carry ?id=… (read from self._query, stashed here).
        self._query = parse_qs(urlparse(self.path).query)
        self.path = urlparse(self.path).path
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
            self._send(200, {"memory": brain.mem_all(200), "fts5": brain.HAS_FTS})
        elif self.path == "/api/prompts":
            self._send(200, {"prompts": _load_json(PROMPTS_FILE, [])})
        elif self.path == "/api/usage":
            u = _load_json(USAGE_FILE, {})
            free = u.get("claudecode", 0)
            self._send(200, {"usage": u, "total": sum(u.values()), "free_requests": free})
        elif self.path == "/api/ui":
            self._send(200, {"widgets": _load_json(WIDGETS_FILE, [])})
        elif self.path == "/api/channels":
            self._send(200, {"channels": tools.channels()})
        elif self.path == "/api/skills":
            self._send(200, {"skills": tools.skills(), "learned": brain.skill_list()})
        elif self.path == "/api/fabric":
            self._send(200, {"patterns": tools.fabric_patterns(), "bin": bool(tools.fabric_bin())})
        elif self.path == "/api/modes":
            self._send(200, {"state": modes_state(), "modes": tools.agent_modes_meta()})
        elif self.path == "/api/dashboard":
            self._send(200, dashboard_cfg())
        elif self.path == "/api/updates":
            self._send(200, {"pending": pending_updates(), "pins": updates.pins(),
                             "reports": updates.reports()[:20],
                             "auto_apply": os.environ.get("AIOS_AUTO_APPLY", "1") == "1"})
        elif self.path == "/api/tasks":
            self._send(200, {"tasks": brain.task_list()})
        elif self.path == "/api/task_runs":
            tid = int(self._query.get("id", ["0"])[0] or 0)
            self._send(200, {"runs": brain.runs_for(tid)})
        elif self.path == "/api/flows":
            self._send(200, {"flows": brain.flow_list()})
        elif self.path == "/api/flow":
            fid = int(self._query.get("id", ["0"])[0] or 0)
            f = brain.flow_get(fid)
            self._send(200 if f else 404,
                       {"flow": f, "revisions": brain.flow_revisions(fid)} if f else {"error": "not found"})
        elif self.path == "/api/audit":
            self._send(200, {"audit": brain.audit_tail(150)})
        elif self.path == "/api/security":
            self._send(200, {
                "full_control": tools.full_control(),
                "guardrails": tools.guardrails_on(),
                "active_memory": active_memory_on(),
                "skill_learn": skill_learn_on(),
                "token_set": bool(sec.get_token()),
                "bind": os.environ.get("AIOS_HUB_HOST", "0.0.0.0"),
                "brain": brain.stats(),
            })
        elif self.path == "/api/health_events":
            self._send(200, {"events": _load_json(HEALTH_FILE, [])})
        elif self.path == "/api/claude_status":
            self._send(200, claude_status())
        elif self.path == "/api/claude_login":
            self._send(200, claude_login_state())
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
        if not self._gate():
            return
        self.path = urlparse(self.path).path  # tolerate ?token=… on POSTs too
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            payload = {}
        if self.path in ("/api/chat", "/api/relay"):
            target = payload.get("target") or payload.get("to") or "brain"
            message = payload.get("message", "")
            history = payload.get("history", [])
            # Inline mode toggles: /caveman [level|off], /ponytail [level|off]
            cmd = message.strip().lower()
            hit = next((n for n in tools.AGENT_MODES if cmd.startswith("/" + n)), None)
            if hit:
                meta = tools.AGENT_MODES[hit]
                arg = message.strip().split(None, 1)[1].strip().lower() if len(message.split()) > 1 else ""
                if arg in ("off", "stop", "normal"):
                    set_mode(hit, False)
                    reply = f"{meta['label']} mode **off**."
                else:
                    st = set_mode(hit, True, arg or modes_state()[hit]["level"])
                    reply = (f"{meta['icon']} {meta['label']} mode **on** · level "
                             f"**{st[hit]['level']}** — {meta['blurb']}. `/{hit} off` to stop.")
                self._send(200, {"target": target, "reply": reply, "ran": []})
                return
            # Inline fabric: /p <pattern> <text>  or  /pattern <name> <text>
            if cmd.startswith(("/p ", "/pattern ")):
                rest = message.split(None, 1)[1] if len(message.split()) > 1 else ""
                pat, _, txt = rest.partition(" ")
                reply = run_fabric(pat.strip(), txt.strip() or " ".join(m.get("content", "")
                                   for m in history if m.get("role") == "user")[-4000:])
                self._send(200, {"target": "fabric", "reply": reply, "ran": []})
                return
            reply = route(target, message, history)
            ran = commands_this_turn()
            remember_async(message, reply)      # Active Memory: learn from every turn
            learn_async(message, reply, ran)    # Curator: turn procedures into skills
            self._send(200, {"target": target, "reply": reply, "ran": ran})
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
                    urllib.request.urlopen(rq, timeout=180)  # claude CLI cold start is slow
                    logged_in = True
                except Exception as e:
                    detail = str(e)[:160]
            self._send(200, {
                "ok": True, "model": model, "reachable": authed, "logged_in": logged_in,
                "note": ("Connected — your Claude subscription is working." if logged_in else
                         "Pointed at claude-code, but the Claude CLI isn't logged in yet. Run "
                         "`aios claude-login` (or `claude setup-token`) in a terminal to authorize your "
                         "Pro/Max account, then chat.")})
        elif self.path == "/api/claude_login":
            op = payload.get("op", "start")
            if op == "start":
                self._send(200, claude_login_start(payload.get("mode", "setup-token")))
            elif op == "input":
                self._send(200, claude_login_input(payload.get("text", "")))
            elif op == "stop":
                self._send(200, claude_login_stop())
            else:
                self._send(400, {"error": "unknown op"})
        elif self.path == "/api/exec":
            # Full control, exposed. Any agent (or you) can drive the machine.
            r = tools.shell(payload.get("command", ""), actor=payload.get("actor", "hub"),
                            cwd=payload.get("cwd"), timeout=payload.get("timeout"))
            self._send(200, r)
        elif self.path == "/api/channels":
            # Configure a channel by writing its env vars; openclaw reads them on restart.
            updates = payload.get("env", {})
            write_env_updates(updates)
            if payload.get("restart", True):
                run_aios("restart", "openclaw", background=True)
            brain.audit("hub", "channel.configure", ",".join(updates.keys()))
            self._send(200, {"ok": True, "configured": list(updates.keys())})
        elif self.path == "/api/skills":
            op = payload.get("op", "install")
            if op == "install":
                self._send(200, tools.install_skill(payload.get("name", ""),
                                                    payload.get("content", "")))
            else:
                self._send(400, {"error": "unknown op"})
        elif self.path == "/api/fabric":
            out = run_fabric(payload.get("pattern", "summarize"), payload.get("input", ""),
                             target=payload.get("target", "brain"))
            self._send(200, {"pattern": payload.get("pattern"), "output": out})
        elif self.path == "/api/modes":
            st = set_mode(payload.get("mode", ""), payload.get("enabled", False),
                          payload.get("level", "full"))
            self._send(200, {"state": st})
        elif self.path == "/api/dashboard":
            self._send(200, dashboard_update(payload))
        elif self.path == "/api/updates":
            op = payload.get("op", "scan")
            if op == "scan":
                # Manual scan never auto-applies — you asked to look, not to change.
                self._send(200, {"pending": scan_updates(auto=False)})
            elif op == "apply":
                name = payload.get("project", "")
                res = updates.apply(name, health_url=_health_url_for(name),
                                    log=lambda m: _log_event("update", name, m))
                if res.get("ok"):
                    tools._FAB_CACHE = None
                    _save_json(PENDING_FILE, [u for u in pending_updates() if u["name"] != name])
                brain.audit("hub", "update.apply", f"{name}: {res}")
                self._send(200, res)
            elif op == "rollback":
                res = updates.rollback(payload.get("project", ""))
                brain.audit("hub", "update.rollback", str(res))
                self._send(200, res)
            elif op == "skip":
                name = payload.get("project", "")
                _save_json(PENDING_FILE, [u for u in pending_updates() if u["name"] != name])
                self._send(200, {"ok": True})
            else:
                self._send(400, {"error": "unknown op"})
        elif self.path == "/api/tasks":
            op = payload.get("op", "add")
            if op == "add":
                tid = brain.task_add(
                    name=payload.get("name", "task"), kind=payload.get("kind", "agent"),
                    target=payload.get("target", "brain"), prompt=payload.get("prompt", ""),
                    command=payload.get("command", ""), cron=payload.get("cron", ""),
                    every_minutes=int(payload.get("every_minutes", 0) or 0),
                    enabled=bool(payload.get("enabled", True)))
                self._send(200, {"ok": True, "id": tid})
            elif op == "delete":
                brain.task_delete(int(payload["id"]))
                self._send(200, {"ok": True})
            elif op == "toggle":
                t = brain.task_get(int(payload["id"]))
                brain.task_update(t["id"], enabled=0 if t["enabled"] else 1)
                self._send(200, {"ok": True, "enabled": not t["enabled"]})
            elif op == "run":
                t = brain.task_get(int(payload["id"]))
                started = time.time()
                status, output = run_task(t)
                brain.task_update(t["id"], last_run=started, last_status=status, last_output=output)
                brain.run_add(t["id"], started, status, output)
                self._send(200, {"ok": status == "ok", "status": status, "output": output})
            else:
                self._send(400, {"error": "unknown op"})
        elif self.path == "/api/flows":
            op = payload.get("op", "create")
            if op == "create":
                steps = payload.get("steps", [])
                if not steps:
                    self._send(400, {"error": "no steps"})
                    return
                fid = brain.flow_create(payload.get("name", "flow"), steps)
                if payload.get("start", True):
                    threading.Thread(target=run_flow, args=(fid,), daemon=True).start()
                self._send(200, {"ok": True, "id": fid})
            elif op == "run":
                threading.Thread(target=run_flow, args=(int(payload["id"]),), daemon=True).start()
                self._send(200, {"ok": True})
            elif op == "delete":
                brain.flow_delete(int(payload["id"]))
                self._send(200, {"ok": True})
            else:
                self._send(400, {"error": "unknown op"})
        elif self.path == "/api/dryrun":
            self._send(200, dry_run(payload.get("target", "brain"), payload.get("message", ""),
                                    payload.get("history", [])))
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
        elif self.path == "/api/ui":
            # Shared generative-UI canvas: any agent can add/remove widgets (HTML).
            items = _load_json(WIDGETS_FILE, [])
            op = payload.get("op", "add")
            if op == "add":
                items.insert(0, {"id": str(int(time.time() * 1000)),
                                 "title": (payload.get("title") or "widget")[:80],
                                 "by": (payload.get("by") or "agent")[:24],
                                 "html": payload.get("html", ""), "ts": time.time()})
                items = items[:40]
            elif op == "delete":
                items = [w for w in items if w.get("id") != payload.get("id")]
            elif op == "clear":
                items = []
            _save_json(WIDGETS_FILE, items)
            self._send(200, {"ok": True, "widgets": items})
        elif self.path == "/api/memory":
            op = payload.get("op", "add")
            if op == "add" and payload.get("text"):
                brain.mem_add(payload["text"], kind=payload.get("kind", "fact"), source="hub")
            elif op == "delete" and payload.get("id") is not None:
                brain.mem_delete(int(payload["id"]))
            elif op == "search":
                self._send(200, {"hits": brain.mem_search(payload.get("q", ""), k=10)})
                return
            elif op == "clear":
                for m in brain.mem_all(10000):
                    brain.mem_delete(m["id"])
            self._send(200, {"ok": True, "memory": brain.mem_all(200)})
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
    brain.db()                 # open/create .aios/aios.db (profile-aware)
    migrate_memory_once()      # memory.json  -> memory table
    migrate_schedules_once()   # schedules.json -> Task Brain

    threading.Thread(target=_taskbrain_loop, daemon=True).start()  # cron + intervals + CLI
    threading.Thread(target=_watchdog_loop, daemon=True).start()   # auto-heal downed agents
    threading.Thread(target=_updates_loop, daemon=True).start()    # agent-supervised updates
    resume_flows()                                                 # durable TaskFlow recovery

    # Bind all interfaces by default so the Windows browser can reach it over WSL.
    # That is only safe because sec.check() gates every non-loopback request on a token.
    host = os.environ.get("AIOS_HUB_HOST", "0.0.0.0")
    srv = ThreadingHTTPServer((host, PORT), Handler)
    print(f"AIOS Hub listening on http://{host}:{PORT}/  (dashboard + interconnect + Task Brain)")
    print(f"peers: {json.dumps(PEERS)}")
    fc = "ON — agents can run shell commands" if tools.full_control() else "off"
    gr = "on" if tools.guardrails_on() else "OFF"
    print(f"full control: {fc} | guardrails: {gr} | active memory: "
          f"{'on' if active_memory_on() else 'off'}")
    if host != "127.0.0.1" and not sec.get_token():
        print("⚠  bound to a public interface with no AIOS_HUB_TOKEN set. Remote requests "
              "will be REFUSED. Run `aios setup` to generate a token.", file=sys.stderr)
    elif host != "127.0.0.1":
        print(f"remote access requires a token — `aios url` prints the link. "
              f"(loopback needs none)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
