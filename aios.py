#!/usr/bin/env python3
"""
The AI OS (aios) — one control surface for five agent projects.

Orchestrates: opencode (coding engine), hermes (autonomous agent + dashboard),
openclaw (channel gateway), openclaw-os (dashboard plugin / front door),
LifeOS (shared skills/context). Single source of truth: aios.config.yaml + .env.

Pure Python standard library — runs on any Python 3.9+ with zero setup.
Windows-first; POSIX parity. See README.aios.md.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".aios"
LOGS = STATE / "logs"
PIDS = STATE / "pids"
BACKUPS = STATE / "backups"
RENDERED = STATE / "rendered"
CONFIG_PATH = ROOT / "aios.config.yaml"
CONFIG_EXAMPLE = ROOT / "aios.config.example.yaml"
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

IS_WIN = os.name == "nt"

# --------------------------------------------------------------------------- #
# Terminal colour                                                             #
# --------------------------------------------------------------------------- #
def _enable_vt():
    if not IS_WIN:
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except Exception:
        pass


def _force_utf8():
    # Windows consoles default to cp1252 and crash on ✓/✗/—; force UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


_enable_vt()
_force_utf8()
_TTY = sys.stdout.isatty()


class C:
    R = "\033[0m" if _TTY else ""
    B = "\033[1m" if _TTY else ""
    RED = "\033[31m" if _TTY else ""
    GRN = "\033[32m" if _TTY else ""
    YEL = "\033[33m" if _TTY else ""
    BLU = "\033[34m" if _TTY else ""
    CYN = "\033[36m" if _TTY else ""
    GRY = "\033[90m" if _TTY else ""


def say(msg=""):
    print(msg)


def ok(msg):
    print(f"{C.GRN}✓{C.R} {msg}")


def warn(msg):
    print(f"{C.YEL}!{C.R} {msg}")


def err(msg):
    print(f"{C.RED}✗{C.R} {msg}")


def head(msg):
    print(f"\n{C.B}{C.CYN}{msg}{C.R}")


def die(msg, code=1):
    err(msg)
    sys.exit(code)


# --------------------------------------------------------------------------- #
# Minimal YAML reader (controlled subset: nested maps, scalars, lists)         #
# --------------------------------------------------------------------------- #
def _strip_comment(s: str) -> str:
    out, q, i = [], None, 0
    while i < len(s):
        c = s[i]
        if q:
            out.append(c)
            if c == q:
                q = None
        elif c in ('"', "'"):
            q = c
            out.append(c)
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip()


def _scalar(v: str):
    v = v.strip()
    if v == "" or v in ("~", "null", "Null", "NULL"):
        return None
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def parse_yaml(text: str):
    lines = []
    for raw in text.splitlines():
        s = _strip_comment(raw)
        if s.strip() == "":
            continue
        indent = len(s) - len(s.lstrip(" "))
        lines.append((indent, s.strip()))
    pos = [0]

    def block(min_indent):
        if pos[0] >= len(lines):
            return None
        indent, content = lines[pos[0]]
        if content.startswith("- "):
            lst = []
            while pos[0] < len(lines):
                indent, content = lines[pos[0]]
                if indent < min_indent or not content.startswith("- "):
                    break
                pos[0] += 1
                lst.append(_scalar(content[2:]))
            return lst
        d = {}
        while pos[0] < len(lines):
            indent, content = lines[pos[0]]
            if indent < min_indent or content.startswith("- "):
                break
            k, _, v = content.partition(":")
            key = k.strip()
            pos[0] += 1
            if v.strip() == "":
                if pos[0] < len(lines) and lines[pos[0]][0] > indent:
                    d[key] = block(indent + 1)
                else:
                    d[key] = None
            else:
                d[key] = _scalar(v)
        return d

    return block(0) or {}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return parse_yaml(CONFIG_PATH.read_text(encoding="utf-8"))
    if CONFIG_EXAMPLE.exists():
        return parse_yaml(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    return {}


def cfg_get(cfg: dict, path: str, default=None):
    cur = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur if cur is not None else default


# --------------------------------------------------------------------------- #
# .env handling                                                                #
# --------------------------------------------------------------------------- #
def load_env(path: Path) -> dict:
    d = {}
    if not path.exists():
        return d
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]  # quoted value: keep verbatim (may contain '#')
        elif " #" in v:
            v = v.split(" #", 1)[0].rstrip()  # strip inline comment (dotenv style)
        d[k.strip()] = v
    return d


def write_env(path: Path, data: dict, header: str = ""):
    lines = []
    if header:
        lines.append(f"# {header}")
    for k, v in data.items():
        lines.append(f"{k}={v}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask(v: str) -> str:
    if not v:
        return ""
    if len(v) <= 8:
        return "*" * len(v)
    return v[:4] + "…" + v[-4:]


# --------------------------------------------------------------------------- #
# Project roots (resolve double-nested X-main/X-main)                          #
# --------------------------------------------------------------------------- #
def resolve_root(*candidates) -> Path | None:
    for c in candidates:
        p = ROOT / c
        if p.exists():
            return p
    return None


PROJECTS = {
    "opencode": resolve_root("opencode-dev/opencode-dev", "opencode-dev", "opencode"),
    "hermes": resolve_root("hermes-agent-main/hermes-agent-main", "hermes-agent-main", "hermes-agent"),
    "openclaw": resolve_root("openclaw-main/openclaw-main", "openclaw-main", "openclaw"),
    "crewai": resolve_root("crewAI-main/crewAI-main", "crewAI-main", "crewai"),
    "claudecode": resolve_root("claude-code-api-main/claude-code-api-main", "claude-code-api-main", "claude-code-api"),
    # openclaw-os is the dashboard for openclaw (not a standalone agent).
    "openclaw_os": resolve_root("openclaw-os-main/openclaw-os-main", "openclaw-os-main", "openclaw-os"),
    "lifeos": resolve_root("LifeOS-main/LifeOS-main", "LifeOS-main", "LifeOS"),
}


# --------------------------------------------------------------------------- #
# Toolchain discovery                                                          #
# --------------------------------------------------------------------------- #
def find_tool(name: str) -> str | None:
    p = shutil.which(name)
    # On WSL the inherited Windows PATH leaks /mnt/c Windows binaries (Nodist
    # node/pnpm) that run the wrong runtime — ignore those and prefer native ones.
    if p and (IS_WIN or not p.replace("\\", "/").startswith("/mnt/")):
        return p
    home = Path.home()
    # Newest nvm-installed node bin dirs (for native node/npm/pnpm on Linux).
    nvm = home / ".nvm" / "versions" / "node"
    nvm_bins = sorted(nvm.glob("*/bin"), reverse=True) if nvm.exists() else []
    extra = {
        "bun": [home / ".bun/bin/bun.exe", home / ".bun/bin/bun"],
        "uv": [home / ".local/bin/uv.exe", home / ".local/bin/uv", home / ".cargo/bin/uv"],
        "pnpm": [home / "AppData/Roaming/npm/pnpm.cmd", home / ".local/share/pnpm/pnpm.exe",
                 home / ".local/share/pnpm/pnpm"] + [b / "pnpm" for b in nvm_bins],
        "node": [b / "node" for b in nvm_bins],
        "npm": [b / "npm" for b in nvm_bins],
    }
    for cand in extra.get(name, []):
        if Path(cand).exists():
            return str(cand)
    return None


def tool_version(path: str) -> str:
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return "?"


TOOLS = ["bun", "pnpm", "uv", "node", "git"]


def tool_map() -> dict:
    return {t: find_tool(t) for t in TOOLS}


def child_env(extra: dict | None = None) -> dict:
    """os.environ + tool bin dirs on PATH + provider/config overrides."""
    env = dict(os.environ)
    binds = []
    for t in TOOLS:
        p = find_tool(t)
        if p:
            binds.append(str(Path(p).parent))
    sep = ";" if IS_WIN else ":"
    env["PATH"] = sep.join(binds + [env.get("PATH", "")])
    if extra:
        env.update({k: str(v) for k, v in extra.items() if v is not None})
    return env


# --------------------------------------------------------------------------- #
# Provider mapping (unified .env -> per-project vars)                          #
# --------------------------------------------------------------------------- #
PROVIDER_VAR = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    # Claude Pro/Max via claude-code-api (OpenAI-compatible; auth is the Claude CLI login).
    "claudecode": "OPENAI_API_KEY",
}
PASSTHROUGH_KEYS = [
    "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY",
]
CHANNEL_KEYS = ["TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]


def provider_env(cfg: dict, secrets: dict) -> tuple[dict, str, str]:
    provider = (secrets.get("AIOS_LLM_PROVIDER") or cfg_get(cfg, "model.provider", "openrouter")).lower()
    var = PROVIDER_VAR.get(provider, "OPENROUTER_API_KEY")
    key = secrets.get("AIOS_LLM_API_KEY", "")
    env = {}
    if key:
        env[var] = key
    for k in PASSTHROUGH_KEYS:
        if secrets.get(k):
            env[k] = secrets[k]
    return env, provider, var


# --------------------------------------------------------------------------- #
# Service registry                                                             #
# --------------------------------------------------------------------------- #
def service_specs(cfg: dict) -> dict:
    oc = PROJECTS["opencode"]
    hm = PROJECTS["hermes"]
    cl = PROJECTS["openclaw"]
    specs = {}
    if oc:
        port = int(cfg_get(cfg, "services.opencode.port", 4096))
        host = cfg_get(cfg, "services.opencode.hostname", "127.0.0.1")
        specs["opencode"] = {
            "enabled": cfg_get(cfg, "services.opencode.enabled", True),
            "cwd": oc / "packages" / "opencode",
            "cmd": ["bun", "src/index.ts", "serve", "--port", str(port), "--hostname", host],
            "port": port,
            "health": cfg_get(cfg, "health.opencode", f"http://{host}:{port}/"),
            "tool": "bun",
        }
    if hm:
        port = int(cfg_get(cfg, "services.hermes.port", 9119))
        host = cfg_get(cfg, "services.hermes.hostname", "127.0.0.1")
        specs["hermes"] = {
            "enabled": cfg_get(cfg, "services.hermes.enabled", True),
            "cwd": hm,
            "cmd": ["uv", "run", "hermes", "dashboard", "--host", host, "--no-open"],
            "port": port,
            "health": cfg_get(cfg, "health.hermes", f"http://{host}:{port}/"),
            "tool": "uv",
        }
        if cfg_get(cfg, "services.hermes.gateway", False):
            specs["hermes-gateway"] = {
                "enabled": True,
                "cwd": hm,
                "cmd": ["uv", "run", "hermes", "gateway", "run"],
                "port": None,
                "health": None,
                "tool": "uv",
            }
    if cl:
        port = int(cfg_get(cfg, "services.openclaw.port", 18789))
        specs["openclaw"] = {
            "enabled": cfg_get(cfg, "services.openclaw.enabled", True),
            "cwd": cl,
            "cmd": ["node", "openclaw.mjs", "gateway"],
            "port": port,
            "health": cfg_get(cfg, "health.openclaw", f"http://127.0.0.1:{port}/"),
            "tool": "node",
            # Dedicated state dir → fresh, valid config; never touches the
            # user's own ~/.openclaw (which may hold unrelated prior setup).
            "env": openclaw_env(),
        }
    cr = PROJECTS["crewai"]
    if cr:
        port = int(cfg_get(cfg, "services.crewai.port", 4788))
        specs["crewai"] = {
            "enabled": cfg_get(cfg, "services.crewai.enabled", True),
            "cwd": ROOT,
            "cmd": ["uv", "run", "--project", str(cr), "python", str(ROOT / "services" / "crewai_service.py")],
            "port": port,
            "health": cfg_get(cfg, "health.crewai", f"http://127.0.0.1:{port}/health"),
            "tool": "uv",
            "env": {"AIOS_CREWAI_PORT": str(port)},
        }
    cc = PROJECTS["claudecode"]
    if cc:
        port = int(cfg_get(cfg, "services.claudecode.port", 8000))
        specs["claudecode"] = {
            "enabled": cfg_get(cfg, "services.claudecode.enabled", True),
            "cwd": cc,
            "cmd": ["uv", "run", "uvicorn", "claude_code_api.main:app", "--host", "127.0.0.1", "--port", str(port)],
            "port": port,
            "health": cfg_get(cfg, "health.claudecode", f"http://127.0.0.1:{port}/health"),
            "tool": "uv",
        }
    # Frame-stripping reverse proxies so openclaw + hermes control-UIs embed in the hub.
    if cl and cfg_get(cfg, "services.openclaw_proxy.enabled", True):
        pport = int(cfg_get(cfg, "services.openclaw_proxy.port", 8791))
        oport = int(cfg_get(cfg, "services.openclaw.port", 18789))
        specs["openclaw-proxy"] = {
            "enabled": True,
            "cwd": ROOT,
            "cmd": [sys.executable, str(ROOT / "aios_proxy.py")],
            "port": pport,
            "health": cfg_get(cfg, "health.openclaw_proxy", f"http://127.0.0.1:{pport}/"),
            "tool": "python",
            "env": {"AIOS_PROXY_PORT": str(pport), "AIOS_PROXY_TARGET": f"http://127.0.0.1:{oport}"},
        }
    if hm and cfg_get(cfg, "services.hermes_proxy.enabled", True):
        pport = int(cfg_get(cfg, "services.hermes_proxy.port", 8792))
        hp = int(cfg_get(cfg, "services.hermes.port", 9119))
        specs["hermes-proxy"] = {
            "enabled": True,
            "cwd": ROOT,
            "cmd": [sys.executable, str(ROOT / "aios_proxy.py")],
            "port": pport,
            "health": cfg_get(cfg, "health.hermes_proxy", f"http://127.0.0.1:{pport}/"),
            "tool": "python",
            "env": {"AIOS_PROXY_PORT": str(pport), "AIOS_PROXY_TARGET": f"http://127.0.0.1:{hp}"},
        }
    # The AIOS Hub — unified dashboard + interconnect. Always available (stdlib).
    hport = int(cfg_get(cfg, "services.hub.port", 8787))
    specs["hub"] = {
        "enabled": cfg_get(cfg, "services.hub.enabled", True),
        "cwd": ROOT,
        "cmd": [sys.executable, str(ROOT / "aios_hub.py")],
        "port": hport,
        "health": cfg_get(cfg, "health.hub", f"http://127.0.0.1:{hport}/health"),
        "tool": "python",
        "env": {
            "AIOS_HUB_PORT": str(hport),
            "AIOS_OPENCODE_DIR": str(oc / "packages" / "opencode") if oc else "",
            "AIOS_BUN": find_tool("bun") or "",
        },
    }
    return specs


START_ORDER = ["opencode", "hermes", "hermes-gateway", "hermes-proxy", "openclaw",
               "openclaw-proxy", "crewai", "claudecode", "hub"]


def openclaw_env() -> dict:
    """Isolate openclaw in an aios-managed state dir (non-destructive)."""
    d = STATE / "openclaw"
    d.mkdir(parents=True, exist_ok=True)
    return {"OPENCLAW_STATE_DIR": str(d)}


def interconnect_env(cfg: dict) -> dict:
    """Peer + hub URLs injected into every service so agents can reach each other."""
    ocp = cfg_get(cfg, "services.opencode.port", 4096)
    hmp = cfg_get(cfg, "services.hermes.port", 9119)
    clp = cfg_get(cfg, "services.openclaw.port", 18789)
    crp = cfg_get(cfg, "services.crewai.port", 4788)
    ccp = cfg_get(cfg, "services.claudecode.port", 8000)
    pxp = cfg_get(cfg, "services.openclaw_proxy.port", 8791)
    hxp = cfg_get(cfg, "services.hermes_proxy.port", 8792)
    hbp = cfg_get(cfg, "services.hub.port", 8787)
    return {
        "AIOS_ROOT": str(ROOT),
        "AIOS_DASHBOARD": str(ROOT / "docs" / "dashboard.html"),
        "AIOS_HUB_URL": f"http://127.0.0.1:{hbp}",
        "AIOS_HUB_PORT": str(hbp),
        "AIOS_OPENCODE_URL": f"http://127.0.0.1:{ocp}",
        "AIOS_HERMES_URL": f"http://127.0.0.1:{hmp}",
        "AIOS_OPENCLAW_URL": f"http://127.0.0.1:{clp}",
        "AIOS_CREWAI_URL": f"http://127.0.0.1:{crp}",
        "AIOS_CREWAI_PORT": str(crp),
        "AIOS_CLAUDECODE_URL": f"http://127.0.0.1:{ccp}",
        "AIOS_OPENCLAWPROXY_URL": f"http://127.0.0.1:{pxp}/",
        "AIOS_HERMESPROXY_URL": f"http://127.0.0.1:{hxp}/",
        "AIOS_OPENCLAWOS_URL": f"http://127.0.0.1:{clp}/plugins/openclawos/",
    }


# --------------------------------------------------------------------------- #
# Process helpers                                                              #
# --------------------------------------------------------------------------- #
def port_in_use(port, host="127.0.0.1") -> bool:
    if not port:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, int(port))) == 0


def pid_alive(pid: int) -> bool:
    if IS_WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pidfile(svc: str) -> Path:
    return PIDS / f"{svc}.json"


def read_pid(svc: str) -> dict | None:
    f = pidfile(svc)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            return None
    return None


def spawn(svc: str, spec: dict, cfg: dict, secrets: dict, extra_env: dict | None = None):
    LOGS.mkdir(parents=True, exist_ok=True)
    PIDS.mkdir(parents=True, exist_ok=True)
    logf = open(LOGS / f"{svc}.log", "ab")
    logf.write(f"\n===== {svc} started {time.ctime()} =====\n".encode())
    logf.flush()

    penv, _, _ = provider_env(cfg, secrets)
    penv.update(interconnect_env(cfg))  # peer + hub URLs (agents reach each other)
    # Raw AIOS_LLM_* passthrough so the hub + CrewAI can call the model directly.
    for k in ("AIOS_LLM_PROVIDER", "AIOS_LLM_API_KEY", "AIOS_LLM_BASE_URL", "AIOS_DEFAULT_MODEL"):
        if secrets.get(k):
            penv[k] = secrets[k]
    penv.setdefault("AIOS_DEFAULT_MODEL", cfg_get(cfg, "model.default", "anthropic/claude-opus-4.6"))
    if spec.get("env"):
        penv.update(spec["env"])
    if extra_env:
        penv.update(extra_env)
    env = child_env(penv)

    # Resolve the leading tool to an absolute path (Windows needs the ext).
    cmd = list(spec["cmd"])
    tool_path = find_tool(spec["tool"])
    if tool_path:
        cmd[0] = tool_path

    kwargs = dict(cwd=str(spec["cwd"]), stdout=logf, stderr=subprocess.STDOUT, env=env)
    if IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    pidfile(svc).write_text(json.dumps({
        "pid": proc.pid, "port": spec.get("port"), "started": time.time(),
        "cmd": " ".join(str(c) for c in spec["cmd"]),
    }))
    return proc


def kill_pid(pid: int):
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass


def wait_health(url: str | None, port, timeout=90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if url:
            try:
                urllib.request.urlopen(url, timeout=2)
                return True
            except urllib.error.HTTPError:
                return True  # server answered (even 401/404) => up
            except Exception:
                pass
        if port and port_in_use(port):
            return True
        time.sleep(1.5)
    return False


# --------------------------------------------------------------------------- #
# Commands                                                                     #
# --------------------------------------------------------------------------- #
def cmd_doctor(args):
    head("The AI OS — doctor")
    problems = 0

    say(f"{C.B}Toolchains{C.R}")
    needed = {"bun": "opencode + LifeOS", "pnpm": "openclaw + openclaw-os",
              "uv": "hermes", "node": "openclaw", "git": "updates"}
    for t, why in needed.items():
        p = find_tool(t)
        if p:
            ok(f"{t:5} {tool_version(p):22} ({why})  {C.GRY}{p}{C.R}")
        else:
            problems += 1
            fix = {
                "bun": 'powershell -c "irm bun.sh/install.ps1 | iex"',
                "pnpm": "npm i -g pnpm",
                "uv": 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"',
                "node": "nvm install 22  (WSL/Linux — native Node >=20) or https://nodejs.org",
                "git": "install Git from https://git-scm.com",
            }[t]
            err(f"{t:5} MISSING  ({why})  → fix: {C.B}{fix}{C.R}")

    say(f"\n{C.B}Projects{C.R}")
    for name, p in PROJECTS.items():
        if p:
            ok(f"{name:12} {C.GRY}{p.relative_to(ROOT)}{C.R}")
        else:
            problems += 1
            err(f"{name:12} NOT FOUND under {ROOT}")

    say(f"\n{C.B}Config & secrets{C.R}")
    if CONFIG_PATH.exists():
        ok(f"aios.config.yaml present")
    else:
        warn(f"aios.config.yaml missing → run: {C.B}aios setup{C.R} (falls back to example meanwhile)")
    secrets = load_env(ENV_PATH)
    if ENV_PATH.exists():
        cfg = load_config()
        _, provider, var = provider_env(cfg, secrets)
        if secrets.get("AIOS_LLM_API_KEY") or secrets.get(var):
            ok(f".env present — provider={provider}, {var}={mask(secrets.get('AIOS_LLM_API_KEY') or secrets.get(var,''))}")
        else:
            problems += 1
            err(f".env present but no model key set → add AIOS_LLM_API_KEY (run {C.B}aios setup{C.R})")
    else:
        problems += 1
        err(f".env missing → run: {C.B}aios setup{C.R}")

    say(f"\n{C.B}Dependency install state{C.R}")
    checks = {
        "opencode": (PROJECTS["opencode"], "node_modules"),
        "openclaw": (PROJECTS["openclaw"], "node_modules"),
        "openclaw_os": (PROJECTS["openclaw_os"], "node_modules"),
        "hermes": (PROJECTS["hermes"], ".venv"),
        "crewai": (PROJECTS["crewai"], ".venv"),
        "claudecode": (PROJECTS["claudecode"], ".venv"),
    }
    for name, (base, marker) in checks.items():
        if base and (base / marker).exists():
            ok(f"{name:12} deps installed ({marker})")
        elif base:
            warn(f"{name:12} deps NOT installed → run: {C.B}aios setup{C.R}")

    say(f"\n{C.B}Ports{C.R}")
    cfg = load_config()
    for svc, spec in service_specs(cfg).items():
        port = spec.get("port")
        if not port:
            continue
        rec = read_pid(svc)
        mine = rec and pid_alive(rec["pid"])
        if port_in_use(port):
            if mine:
                ok(f"{svc:12} :{port} in use by aios (pid {rec['pid']})")
            else:
                warn(f"{svc:12} :{port} in use by a FOREIGN process → free it or change port in aios.config.yaml")
        else:
            ok(f"{svc:12} :{port} free")

    say()
    if problems:
        err(f"doctor found {problems} problem(s). Fix the ✗ lines above, then re-run {C.B}aios doctor{C.R}.")
        sys.exit(1)
    ok("doctor: all green.")


def run_stream(cmd, cwd, env, title) -> int:
    print(f"{C.GRY}$ {' '.join(str(c) for c in cmd)}  (cwd={cwd}){C.R}")
    try:
        return subprocess.run(cmd, cwd=str(cwd), env=env).returncode
    except FileNotFoundError as e:
        err(f"{title}: command not found: {e}")
        return 127


def cmd_setup(args):
    head("The AI OS — setup")
    STATE.mkdir(exist_ok=True)
    for d in (LOGS, PIDS, BACKUPS, RENDERED):
        d.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore()

    # 1) config
    if not CONFIG_PATH.exists():
        if CONFIG_EXAMPLE.exists():
            shutil.copy(CONFIG_EXAMPLE, CONFIG_PATH)
            ok("created aios.config.yaml from example")
        else:
            warn("aios.config.example.yaml not found; continuing with defaults")
    cfg = load_config()

    # 2) secrets wizard
    _wizard_env(args)
    secrets = load_env(ENV_PATH)

    # 3) toolchains
    if not args.skip_tools:
        _ensure_tools(args)

    # 4) install deps
    if not args.skip_install:
        _install_all(cfg)

    # 5) render native config
    render_native(cfg, secrets)

    # 6) mount LifeOS skills
    if cfg_get(cfg, "lifeos.mount_skills", True):
        mount_lifeos(cfg)

    # 6b) mount OpenUI (generative UI) context into the agents
    if cfg_get(cfg, "openui.mount_context", True):
        mount_openui(cfg)

    # 6c) mount the bundled AI OS skills (skill-maker, mcp-maker, …) into the agents
    if cfg_get(cfg, "skills.mount", True):
        mount_aios_skills(cfg)

    # 7) wire openclaw-os plugin (best-effort; needs openclaw runnable)
    if cfg_get(cfg, "services.openclaw_os.enabled", True) and not args.skip_wire:
        wire_openclaw_os(quiet=True)

    # 8) offer to install the global `aios` command + autostart
    interactive = sys.stdin.isatty() and not args.non_interactive
    if interactive and not cli_installed():
        ans = input(f"\n  Make `aios` runnable from anywhere (add it to your PATH)? {C.GRY}[Y/n]{C.R}: ").strip().lower()
        if ans in ("", "y", "yes"):
            install_cli()
    if interactive and not autostart_status():
        ans = input(f"  Start The AI OS automatically on login/boot? {C.GRY}[y/N]{C.R}: ").strip().lower()
        if ans in ("y", "yes"):
            autostart_enable()

    hbp = int(cfg_get(cfg, "services.hub.port", 8787))
    say()
    say(f"{C.B}{C.GRN}  ✓ The AI OS is ready.{C.R}")
    say(f"\n  {C.B}aios start{C.R}   bring the whole stack up")
    say(f"  {C.B}aios url{C.R}     open the Control Room → {C.CYN}http://127.0.0.1:{hbp}/{C.R}")
    say(f"  {C.B}aios doctor{C.R}  check everything is healthy")
    if interactive:
        go = input(f"\n  Start it now? {C.GRY}[Y/n]{C.R}: ").strip().lower()
        if go in ("", "y", "yes"):
            cmd_start(argparse.Namespace(service=["all"], timeout=90))


def _ensure_gitignore():
    gi = ROOT / ".gitignore"
    want = [".aios/", ".env", "aios.config.yaml"]
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    add = [w for w in want if w not in existing]
    if add:
        with open(gi, "a", encoding="utf-8") as f:
            if existing and existing[-1].strip():
                f.write("\n")
            f.write("# The AI OS\n" + "\n".join(add) + "\n")
        ok(f"gitignore: added {', '.join(add)}")


def _wizard_env(args):
    secrets = load_env(ENV_PATH)
    if ENV_PATH.exists() and not args.force:
        if secrets.get("AIOS_LLM_API_KEY"):
            ok(".env already has a model key (use --force to re-run the wizard)")
            return
    if ENV_PATH.exists():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        bak = BACKUPS / f".env.{int(time.time())}.bak"
        shutil.copy(ENV_PATH, bak)
        ok(f"backed up existing .env → {bak.relative_to(ROOT)}")

    interactive = sys.stdin.isatty() and not args.non_interactive
    skip = getattr(args, "skip_keys", False)
    data = load_env(ENV_EXAMPLE) if ENV_EXAMPLE.exists() else {}
    data.update(secrets)  # keep existing values

    # Fill sane defaults for anything missing.
    for var, default in (("AIOS_LLM_PROVIDER", "openrouter"),
                         ("AIOS_LLM_API_KEY", ""),
                         ("AIOS_DEFAULT_MODEL", "anthropic/claude-opus-4.6")):
        data.setdefault(var, default)

    if interactive and not skip:
        head("Model setup")
        gate = input("  Set up your model provider + API key now? "
                     f"{C.GRY}(Enter=yes · type 'skip' to do it later){C.R} [Y/n/skip]: ").strip().lower()
        if gate in ("n", "no", "s", "skip"):
            skip = True

    if skip:
        warn("skipped model setup — the stack still runs, but agents need a key to answer.")
        say(f"  Add it any time: {C.B}aios setup --force{C.R}, edit {C.B}.env{C.R}, "
            f"or use the hub's {C.B}Settings{C.R} panel.")
    elif interactive:
        prov = input(f"  Provider [openrouter/anthropic/openai/gemini] ({data['AIOS_LLM_PROVIDER']}): ").strip().lower()
        if prov in ("skip", "none"):
            skip = True
        else:
            data["AIOS_LLM_PROVIDER"] = prov or data["AIOS_LLM_PROVIDER"]
            key = input(f"  API key ({mask(data.get('AIOS_LLM_API_KEY', ''))}): ").strip()
            if key:
                data["AIOS_LLM_API_KEY"] = key
            model = input(f"  Default model ({data['AIOS_DEFAULT_MODEL']}): ").strip()
            data["AIOS_DEFAULT_MODEL"] = model or data["AIOS_DEFAULT_MODEL"]
            say(f"  {C.GRY}Optional channel tokens (Enter to skip each):{C.R}")
            for ck in CHANNEL_KEYS:
                val = input(f"    {ck} ({mask(data.get(ck, ''))}): ").strip()
                if val:
                    data[ck] = val
    else:  # non-interactive: env-driven
        for var in ("AIOS_LLM_PROVIDER", "AIOS_LLM_API_KEY", "AIOS_DEFAULT_MODEL"):
            if os.environ.get(var):
                data[var] = os.environ[var]
        if not data.get("AIOS_LLM_API_KEY"):
            warn("non-interactive: wrote .env skeleton (add AIOS_LLM_API_KEY later)")

    ordered = {}
    for k in ["AIOS_LLM_PROVIDER", "AIOS_LLM_API_KEY", "AIOS_DEFAULT_MODEL"] + PASSTHROUGH_KEYS + \
             ["OPENCODE_SERVER_PASSWORD", "OPENCLAW_GATEWAY_TOKEN"] + CHANNEL_KEYS:
        if k in data:
            ordered[k] = data[k]
    for k, v in data.items():
        ordered.setdefault(k, v)
    write_env(ENV_PATH, ordered, "The AI OS secrets — DO NOT COMMIT")
    ok("wrote .env")


def _ensure_tools(args):
    head("Toolchains")
    for t in TOOLS:
        p = find_tool(t)
        if p:
            ok(f"{t} present ({tool_version(p)})")
            continue
        warn(f"{t} missing")
        if args.non_interactive:
            continue
        installers = {
            "bun": 'powershell -c "irm bun.sh/install.ps1 | iex"' if IS_WIN else "curl -fsSL https://bun.sh/install | bash",
            "uv": 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"' if IS_WIN else "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "pnpm": "npm i -g pnpm",
        }
        cmdline = installers.get(t)
        if not cmdline:
            err(f"install {t} manually (Node >=20 from nodejs.org, Git from git-scm.com)")
            continue
        ans = input(f"  install {t} now? [{cmdline}] (Y/n): ").strip().lower()
        if ans in ("", "y", "yes"):
            if IS_WIN and cmdline.startswith("powershell"):
                subprocess.run(["powershell", "-Command", cmdline.split("-c ", 1)[1].strip('"')])
            else:
                subprocess.run(cmdline, shell=True)
            if find_tool(t):
                ok(f"{t} installed")
            else:
                err(f"{t} still not found — open a new shell or install manually: {cmdline}")


def _install_all(cfg):
    head("Installing dependencies")
    # opencode: --ignore-scripts skips native postinstalls (tree-sitter-powershell,
    # node-pty) that need VS Build Tools on Windows and are unused by `serve`.
    jobs = [
        ("opencode", PROJECTS["opencode"], "bun", ["install", "--ignore-scripts"]),
        ("hermes", PROJECTS["hermes"], "uv", ["sync"]),
        # openclaw: --ignore-scripts avoids optional native postinstalls
        # (@matrix-org/matrix-sdk-crypto) that break under Node version managers
        # on Windows; the core gateway + openclaw-os dashboard run from source.
        ("openclaw", PROJECTS["openclaw"], "pnpm", ["install", "--ignore-scripts"]),
        ("openclaw_os", PROJECTS["openclaw_os"], "pnpm", ["install"]),
        # crewai: sync only the crewai package's env (avoids heavy optional extras).
        ("crewai", PROJECTS["crewai"], "uv", ["sync", "--package", "crewai"]),
        # claude-code-api: FastAPI OpenAI-compatible wrapper for Claude Code.
        ("claudecode", PROJECTS["claudecode"], "uv", ["sync"]),
    ]
    env = child_env()
    for name, base, tool, sub in jobs:
        if not base:
            warn(f"{name}: root missing, skipping")
            continue
        tp = find_tool(tool)
        if not tp:
            err(f"{name}: {tool} not available — skipping install")
            continue
        print(f"\n{C.B}» {name}{C.R} ({tool} {' '.join(sub)})")
        rc = run_stream([tp] + sub, base, env, name)
        if rc == 0:
            ok(f"{name}: dependencies installed")
        else:
            warn(f"{name}: install exited {rc} (see output above)")

    # openclaw needs a build (dist/entry.mjs) before its gateway can start.
    cl = PROJECTS["openclaw"]
    pnpm = find_tool("pnpm")
    if cl and pnpm and not (cl / "dist" / "entry.mjs").exists():
        heap = _node_heap_mb()
        benv = child_env({"NODE_OPTIONS": f"--max-old-space-size={heap}"})
        print(f"\n{C.B}» openclaw build{C.R} (heavy — NODE_OPTIONS=--max-old-space-size={heap})")
        rc = run_stream([pnpm, "build"], cl, benv, "openclaw-build")
        if rc == 0 and (cl / "dist" / "entry.mjs").exists():
            ok("openclaw: built (dist/entry.mjs)")
        else:
            warn(f"openclaw: build exited {rc}. Needs ~12GB free RAM. Retry: "
                 f'NODE_OPTIONS=--max-old-space-size={heap} pnpm build  (in {cl})')
    elif cl and (cl / "dist" / "entry.mjs").exists():
        ok("openclaw: already built")

    _build_openclaw_os()


def _build_openclaw_os():
    """Build the openclaw-os dashboard: UI bundle + plugin dist/index.js.

    bundle-ui uses shx (cross-platform); the plugin's own `build` script uses
    Unix `rm`, so we call esbuild directly with an argv list instead.
    """
    osrc = PROJECTS["openclaw_os"]
    pnpm = find_tool("pnpm")
    if not (osrc and pnpm):
        return
    plugin = osrc / "packages" / "claw-plugin"
    env = child_env({"NODE_OPTIONS": "--max-old-space-size=8192"})
    print(f"\n{C.B}» openclaw-os dashboard build{C.R}")
    rc = run_stream([pnpm, "--filter", "@openuidev/openclaw-os-plugin", "run", "bundle-ui"],
                    osrc, env, "openclaw-os-ui")
    if rc != 0:
        warn("openclaw-os: UI bundle failed (dashboard may be blank) — see output")
    # Plugin dist via esbuild directly (script's `rm -rf` is Unix-only).
    shutil.rmtree(plugin / "dist", ignore_errors=True)
    banner = "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);"
    esb = [pnpm, "exec", "esbuild", "src/index.ts", "--bundle", "--platform=node",
           "--target=node22", "--format=esm", "--outfile=dist/index.js",
           "--external:openclaw", "--external:openclaw/*", "--external:node:*",
           "--loader:.json=json", f"--banner:js={banner}"]
    rc = run_stream(esb, plugin, env, "openclaw-os-plugin")
    if rc == 0 and (plugin / "dist" / "index.js").exists():
        ok("openclaw-os: dashboard built (UI + plugin dist)")
    else:
        warn(f"openclaw-os: plugin build exited {rc}")


def _node_heap_mb() -> int:
    """Pick a Node heap size for openclaw's heavy build, scaled to physical RAM."""
    try:
        if IS_WIN:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = _MS()
            m.dwLength = ctypes.sizeof(m)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            gb = m.ullTotalPhys / (1024 ** 3)
        else:
            gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3)
    except Exception:
        gb = 16.0
    return int(min(12288, max(4096, gb * 0.6 * 1024)))


def render_native(cfg: dict, secrets: dict):
    head("Rendering native config from .env")
    RENDERED.mkdir(parents=True, exist_ok=True)
    penv, provider, var = provider_env(cfg, secrets)
    model = secrets.get("AIOS_DEFAULT_MODEL") or cfg_get(cfg, "model.default", "anthropic/claude-opus-4.6")
    rendered = []

    # hermes: .env + cli-config.yaml (model.default)
    hm = PROJECTS["hermes"]
    if hm:
        henv = {}
        if secrets.get(var) or secrets.get("AIOS_LLM_API_KEY"):
            henv[var] = secrets.get(var) or secrets["AIOS_LLM_API_KEY"]
        for k in PASSTHROUGH_KEYS:
            if secrets.get(k):
                henv[k] = secrets[k]
        _backup_and_write(hm / ".env", lambda p: write_env(p, henv, "rendered by aios — edit ../../.env instead"))
        (hm / "cli-config.yaml").write_text(f'model:\n  default: "{model}"\n', encoding="utf-8")
        rendered.append(f"hermes: .env ({var}), cli-config.yaml (model={model})")

    # openclaw: .env (token + provider + channels)
    cl = PROJECTS["openclaw"]
    if cl:
        cenv = {}
        tok = secrets.get("OPENCLAW_GATEWAY_TOKEN")
        if tok:
            cenv["OPENCLAW_GATEWAY_TOKEN"] = tok
        if secrets.get(var) or secrets.get("AIOS_LLM_API_KEY"):
            cenv[var] = secrets.get(var) or secrets["AIOS_LLM_API_KEY"]
        for k in PASSTHROUGH_KEYS + CHANNEL_KEYS:
            if secrets.get(k):
                cenv[k] = secrets[k]
        _backup_and_write(cl / ".env", lambda p: write_env(p, cenv, "rendered by aios — edit ../../.env instead"))
        # Minimal gateway config in the isolated state dir so a fresh openclaw
        # starts on loopback without the interactive `openclaw setup`.
        sd = STATE / "openclaw"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "openclaw.json").write_text(
            json.dumps({"gateway": {"mode": "local"}}, indent=2), encoding="utf-8")
        rendered.append(f"openclaw: .env ({var}, {sum(1 for k in CHANNEL_KEYS if secrets.get(k))} channel token(s)) + state/openclaw.json (mode=local)")

    # opencode: provider keys are injected at start via env (no file written,
    # so we never risk breaking opencode's config schema). Record intent.
    (RENDERED / "opencode.env").write_text(
        "\n".join(f"{k}={mask(v)}" for k, v in penv.items()) + "\n", encoding="utf-8")
    rendered.append(f"opencode: provider env injected at start ({var})")
    rendered.append("openclaw-os: uses openclaw's provider (served inside openclaw gateway)")

    for r in rendered:
        ok(r)


def _backup_and_write(path: Path, writer):
    if path.exists():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, BACKUPS / f"{path.parent.name}_{path.name}.{int(time.time())}.bak")
    writer(path)


def mount_lifeos(cfg: dict):
    head("Mounting LifeOS skills")
    life = PROJECTS["lifeos"]
    if not life:
        warn("LifeOS root not found; skipping")
        return
    src = None
    for c in ("LifeOS/install/skills", "LifeOS/skills", "LifeOS"):
        if (life / c).exists():
            src = life / c
            break
    if not src:
        warn("no LifeOS skills directory found; skipping")
        return
    targets = [
        Path.home() / ".openclaw" / "skills" / "lifeos",
        Path.home() / ".hermes" / "skills" / "lifeos",
        STATE / "skills" / "lifeos",
    ]
    for t in targets:
        try:
            if t.exists():
                shutil.rmtree(t)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, t)
            ok(f"mounted → {t}")
        except Exception as e:
            warn(f"could not mount to {t}: {e}")
    say(f"{C.GRY}Source: {src}{C.R}")


def mount_aios_skills(cfg: dict):
    """Copy the bundled AI OS skills (skills/) into each agent's skill directory."""
    head("Mounting AI OS skills")
    src = ROOT / "skills"
    if not src.exists():
        warn("skills/ not found; skipping")
        return
    names = [p.name for p in src.iterdir() if p.is_dir()]
    targets = [Path.home() / ".openclaw" / "skills", Path.home() / ".hermes" / "skills",
               STATE / "skills"]
    for t in targets:
        for name in names:
            try:
                dst = t / name
                if dst.exists():
                    shutil.rmtree(dst)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src / name, dst)
            except Exception as e:
                warn(f"could not mount {name} → {t}: {e}")
    ok(f"mounted {len(names)} skills: {', '.join(names)}")


def mount_openui(cfg: dict):
    """Mount OpenUI (generative-UI) context into every agent's skill dir so any
    agent can respond with OpenUI Lang that the openclaw-os dashboard renders."""
    head("Mounting OpenUI context")
    src = ROOT / "docs" / "aios" / "openui-context.md"
    if not src.exists():
        warn("openui-context.md not found; skipping")
        return
    targets = [
        Path.home() / ".openclaw" / "skills" / "openui",
        Path.home() / ".hermes" / "skills" / "openui",
        STATE / "skills" / "openui",
    ]
    for t in targets:
        try:
            t.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, t / "OPENUI.md")
            ok(f"mounted → {t / 'OPENUI.md'}")
        except Exception as e:
            warn(f"could not mount to {t}: {e}")
    say(f"{C.GRY}OpenUI: https://www.openui.com — openclaw-os renders OpenUI Lang natively{C.R}")


def _stage_openclaw_os_plugin() -> Path | None:
    """Copy the built plugin to a clean dir WITHOUT node_modules.

    openclaw's install runs a supply-chain scan that rejects pnpm's symlinked
    node_modules (targets outside the install root). The plugin's dist/index.js
    is fully bundled, so a copy of the runtime files installs cleanly.
    """
    osrc = PROJECTS["openclaw_os"]
    if not osrc:
        return None
    plugin = osrc / "packages" / "claw-plugin"
    if not (plugin / "dist" / "index.js").exists():
        warn("openclaw-os plugin not built — run `aios setup` (or `aios update`) first")
        return None
    stage = STATE / "plugins" / "openclaw-os"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    for item in ("dist", "static", "skills", "prompts", "openclaw.plugin.json",
                 "package.json", "README.md"):
        src = plugin / item
        if not src.exists():
            continue
        dst = stage / item
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy(src, dst)
    # Strip build-time deps from the staged package.json so nothing is resolved.
    pj = stage / "package.json"
    if pj.exists():
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
            for k in ("dependencies", "devDependencies", "scripts"):
                data.pop(k, None)
            pj.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
    return stage


def wire_openclaw_os(quiet=False):
    if not quiet:
        head("Wiring openclaw-os plugin")
    cl = PROJECTS["openclaw"]
    node = find_tool("node")
    if not (cl and node):
        warn("openclaw or node missing; skipping plugin wire")
        return False
    stage = _stage_openclaw_os_plugin()
    if not stage:
        return False
    env = child_env(openclaw_env())
    cmd = [node, "openclaw.mjs", "plugins", "install", "-l", str(stage)]
    print(f"{C.GRY}$ {' '.join(cmd)}{C.R}")
    rc = subprocess.run(cmd, cwd=str(cl), env=env, capture_output=quiet, text=True).returncode
    if rc == 0:
        ok("openclaw-os plugin installed into openclaw gateway")
        return True
    warn(f"plugin install exited {rc} — retry with: aios wire")
    return False


def cmd_start(args):
    cfg = load_config()
    secrets = load_env(ENV_PATH)
    if cfg_get(cfg, "updates.auto_update", False):
        if _git_pull() is True:  # new commits arrived → refresh deps/config
            _install_all(cfg)
            render_native(cfg, secrets)
            cfg = load_config()
    elif cfg_get(cfg, "updates.check_on_start", True):
        _check_updates_notice()
    if not secrets.get("AIOS_LLM_API_KEY") and not any(secrets.get(v) for v in PROVIDER_VAR.values()):
        warn("no model API key set — the stack runs, but agents need a key to answer "
             "(add it in the hub Settings panel or `aios setup --force`).")
    specs = service_specs(cfg)
    targets = _select(args.service, specs)
    head(f"Starting: {', '.join(targets)}")
    for svc in START_ORDER:
        if svc not in targets:
            continue
        spec = specs[svc]
        if not spec.get("enabled", True):
            warn(f"{svc}: disabled in aios.config.yaml — skipping")
            continue
        rec = read_pid(svc)
        alive = rec and pid_alive(rec["pid"])
        force = getattr(args, "restart", False)
        # A tracked-but-alive process might be stale (old code) or hung — verify it
        # actually answers, and restart it if not (or if --restart was requested).
        if alive and not force:
            healthy = (not spec.get("health")) or wait_health(spec["health"], spec.get("port"), timeout=3)
            if healthy:
                ok(f"{svc}: already running (pid {rec['pid']})")
                continue
            warn(f"{svc}: process alive but not responding — restarting")
        if alive:  # reached only when forced or unhealthy → replace it
            kill_pid(rec["pid"])
            pidfile(svc).unlink(missing_ok=True)
            for _ in range(12):  # wait for the port to free
                if not (spec.get("port") and port_in_use(spec["port"])):
                    break
                time.sleep(0.5)
        elif spec.get("port") and port_in_use(spec["port"]):
            warn(f"{svc}: port {spec['port']} already in use (foreign process) — skipping")
            continue
        extra = {}
        if svc == "opencode" and secrets.get("OPENCODE_SERVER_PASSWORD"):
            extra["OPENCODE_SERVER_PASSWORD"] = secrets["OPENCODE_SERVER_PASSWORD"]
        print(f"{C.CYN}» starting {svc}…{C.R}")
        spawn(svc, spec, cfg, secrets, extra)
        if spec.get("health") or spec.get("port"):
            up = wait_health(spec.get("health"), spec.get("port"), timeout=args.timeout)
            if up:
                ok(f"{svc}: healthy on :{spec.get('port')}")
            else:
                warn(f"{svc}: not healthy within {args.timeout}s — check `aios logs {svc}`")
        else:
            ok(f"{svc}: launched (no health endpoint)")
    say()
    _print_urls(cfg)


def cmd_restart(args):
    """Restart (or start) services — forces a clean respawn to pick up new code."""
    cmd_start(argparse.Namespace(service=getattr(args, "service", ["all"]),
                                 timeout=getattr(args, "timeout", 90), restart=True))


def cmd_stop(args):
    cfg = load_config()
    specs = service_specs(cfg)
    targets = _select(args.service, specs)
    head(f"Stopping: {', '.join(targets)}")
    for svc in targets:
        rec = read_pid(svc)
        if not rec:
            ok(f"{svc}: not tracked")
            continue
        if pid_alive(rec["pid"]):
            kill_pid(rec["pid"])
            time.sleep(0.5)
            if pid_alive(rec["pid"]):
                warn(f"{svc}: pid {rec['pid']} still alive")
            else:
                ok(f"{svc}: stopped (pid {rec['pid']})")
        else:
            ok(f"{svc}: already stopped")
        pidfile(svc).unlink(missing_ok=True)


def cmd_status(args):
    cfg = load_config()
    head("The AI OS — status")
    specs = service_specs(cfg)
    print(f"  {'SERVICE':14}{'STATE':12}{'PORT':7}{'PID':8}HEALTH")
    for svc, spec in specs.items():
        rec = read_pid(svc)
        running = rec and pid_alive(rec["pid"])
        port = spec.get("port") or "-"
        pid = rec["pid"] if rec else "-"
        if running:
            state = f"{C.GRN}running{C.R}  "
        elif spec.get("port") and port_in_use(spec["port"]):
            state = f"{C.YEL}foreign{C.R}  "
        else:
            state = f"{C.GRY}stopped{C.R}  "
        health = "-"
        if spec.get("health"):
            health = f"{C.GRN}up{C.R}" if wait_health(spec["health"], spec.get("port"), timeout=2) else f"{C.GRY}down{C.R}"
        print(f"  {svc:14}{state:12}{str(port):7}{str(pid):8}{health}")
    say()
    _print_urls(cfg)


def cmd_logs(args):
    svc = args.service or "aios"
    f = LOGS / f"{svc}.log"
    if not f.exists():
        die(f"no log at {f} — has {svc} started?")
    text = f.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = text[-args.lines:]
    print("\n".join(tail))


def cmd_test(args):
    cfg = load_config()
    targets = args.service if args.service and args.service != "all" else None
    head("The AI OS — test")
    env = child_env()
    suites = []
    oc, hm, cl, os_ = (PROJECTS["opencode"], PROJECTS["hermes"],
                       PROJECTS["openclaw"], PROJECTS["openclaw_os"])
    if oc:
        suites.append(("opencode", oc / "packages" / "core", "bun", ["test"]))
    if hm:
        suites.append(("hermes", hm, "uv", ["run", "pytest", "-q"]))
    if cl:
        suites.append(("openclaw", cl, "pnpm", ["-r", "test"]))
    if os_:
        suites.append(("openclaw_os", os_, "pnpm", ["-r", "test"]))
    if args.smoke:
        return _smoke(cfg)
    results = []
    for name, base, tool, sub in suites:
        if targets and name != targets:
            continue
        tp = find_tool(tool)
        if not tp:
            results.append((name, "SKIP (tool missing)"))
            continue
        print(f"\n{C.B}» testing {name}{C.R}")
        rc = run_stream([tp] + sub, base, env, name)
        results.append((name, f"{C.GRN}PASS{C.R}" if rc == 0 else f"{C.RED}FAIL ({rc}){C.R}"))
    head("Test summary")
    fail = 0
    for name, res in results:
        print(f"  {name:14} {res}")
        if "FAIL" in res:
            fail += 1
    sys.exit(1 if fail else 0)


def _smoke(cfg):
    head("Smoke test (health of running services)")
    specs = service_specs(cfg)
    fail = 0
    for svc, spec in specs.items():
        if not spec.get("health"):
            continue
        up = wait_health(spec["health"], spec.get("port"), timeout=5)
        if up:
            ok(f"{svc}: {spec['health']} reachable")
        else:
            fail += 1
            err(f"{svc}: {spec['health']} unreachable — is it started? `aios start {svc}`")
    osurl = _openclaw_os_url(cfg)
    if osurl:
        up = wait_health(osurl, None, timeout=5)
        (ok if up else err)(f"openclaw-os front door: {osurl} {'reachable' if up else 'UNREACHABLE'}")
        if not up:
            fail += 1
    sys.exit(1 if fail else 0)


def cmd_debug(args):
    head("The AI OS — debug dump")
    cfg = load_config()
    secrets = load_env(ENV_PATH)
    say(f"{C.B}Root{C.R}: {ROOT}")
    say(f"{C.B}Tools{C.R}:")
    for t, p in tool_map().items():
        say(f"  {t:6} {p or 'MISSING'}")
    say(f"{C.B}Resolved config{C.R}:")
    print(json.dumps(cfg, indent=2))
    say(f"{C.B}Secrets (masked){C.R}:")
    for k, v in secrets.items():
        say(f"  {k}={mask(v)}")
    say(f"{C.B}Provider mapping{C.R}:")
    penv, provider, var = provider_env(cfg, secrets)
    say(f"  provider={provider}  ->  {var}={mask(penv.get(var,''))}")
    say(f"{C.B}Services{C.R}:")
    for svc, spec in service_specs(cfg).items():
        rec = read_pid(svc)
        say(f"  {svc:14} port={spec.get('port')} running={bool(rec and pid_alive(rec['pid']))} "
            f"health={spec.get('health')}")
    if args.service:
        cmd_logs(argparse.Namespace(service=args.service, lines=60))


def cmd_update(args):
    head("The AI OS — update")
    if getattr(args, "check", False):
        _check_updates_notice()  # fetch + report only, no pull
        ok("check complete.")
        return
    cfg = load_config()
    secrets = load_env(ENV_PATH)
    changed = _git_pull()
    if changed is False and not getattr(args, "force", False):
        ok("already up to date — nothing to reinstall (use --force to reinstall anyway).")
    else:
        _install_all(cfg)
    render_native(cfg, secrets)
    if cfg_get(cfg, "lifeos.mount_skills", True):
        mount_lifeos(cfg)
    if cfg_get(cfg, "openui.mount_context", True):
        mount_openui(cfg)
    if cfg_get(cfg, "skills.mount", True):
        mount_aios_skills(cfg)
    # Restart any services that are currently running so the new code takes effect.
    specs = service_specs(cfg)
    running = [s for s in specs if (read_pid(s) and pid_alive(read_pid(s)["pid"]))]
    if running:
        head(f"Restarting running services to apply the update: {', '.join(running)}")
        cmd_start(argparse.Namespace(service=running, timeout=90, restart=True))
    ok("update complete.")


def _git_pull() -> bool | None:
    """Pull latest from the repo. Returns True if new commits arrived, False if
    already current, None if not a git checkout / offline."""
    git = find_tool("git")
    if not git or not (ROOT / ".git").exists():
        warn("not a git checkout — skipping repo update (installed via zip?).")
        return None
    env = child_env()
    before = subprocess.run([git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, env=env).stdout.strip()
    print(f"{C.GRY}$ git pull --ff-only{C.R}")
    rc = subprocess.run([git, "pull", "--ff-only"], cwd=ROOT, env=env).returncode
    if rc != 0:
        warn("git pull failed (local changes or offline?) — continuing with current code.")
        return None
    after = subprocess.run([git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, env=env).stdout.strip()
    if before and after and before != after:
        ok(f"updated {before[:7]} → {after[:7]}")
        return True
    ok("repo already up to date.")
    return False


def _check_updates_notice():
    """Quietly tell the user if the remote is ahead (called on start)."""
    git = find_tool("git")
    if not git or not (ROOT / ".git").exists():
        return
    env = child_env()
    try:
        subprocess.run([git, "fetch", "--quiet"], cwd=ROOT, env=env, timeout=15,
                       capture_output=True)
        counts = subprocess.run([git, "rev-list", "--count", "HEAD..@{u}"], cwd=ROOT,
                                capture_output=True, text=True, env=env, timeout=10).stdout.strip()
        if counts.isdigit() and int(counts) > 0:
            warn(f"{int(counts)} update(s) available on the repo → run {C.B}aios update{C.R}")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Autostart (run on login / boot)                                              #
# --------------------------------------------------------------------------- #
def _win_startup_cmd() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / \
        "Microsoft/Windows/Start Menu/Programs/Startup/aios.cmd"


def _systemd_unit() -> Path:
    return Path.home() / ".config/systemd/user/aios.service"


def _bashrc_marker() -> str:
    return "# >>> The AI OS autostart >>>"


def autostart_status() -> bool:
    if IS_WIN:
        return _win_startup_cmd().exists()
    if _systemd_unit().exists():
        return True
    rc = Path.home() / ".bashrc"
    return rc.exists() and _bashrc_marker() in rc.read_text(encoding="utf-8", errors="ignore")


def autostart_enable():
    py = sys.executable
    if IS_WIN:
        p = _win_startup_cmd()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'@echo off\ncd /d "{ROOT}"\n"{py}" "{ROOT / "aios.py"}" start all\n', encoding="utf-8")
        ok(f"autostart enabled → {p}")
        return
    # Linux: prefer a systemd user service; fall back to a ~/.bashrc hook (WSL).
    have_systemd = shutil.which("systemctl") and Path("/run/systemd/system").exists()
    if have_systemd:
        unit = _systemd_unit()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(
            "[Unit]\nDescription=The AI OS\nAfter=network-online.target\n\n"
            f"[Service]\nType=oneshot\nRemainAfterExit=yes\nWorkingDirectory={ROOT}\n"
            f"ExecStart={py} {ROOT / 'aios.py'} start all\n"
            f"ExecStop={py} {ROOT / 'aios.py'} stop all\n\n"
            "[Install]\nWantedBy=default.target\n", encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "aios.service"], capture_output=True)
        ok(f"autostart enabled (systemd user service) → {unit}")
        say(f"  {C.GRY}start now: systemctl --user start aios{C.R}")
    else:
        rc = Path.home() / ".bashrc"
        block = (f"\n{_bashrc_marker()}\n"
                 f'[ -z "$AIOS_STARTED" ] && command -v python3 >/dev/null && '
                 f'( curl -s -o /dev/null http://127.0.0.1:{8787} 2>/dev/null || '
                 f'python3 "{ROOT / "aios.py"}" start all >/dev/null 2>&1 & ) ; export AIOS_STARTED=1\n'
                 f"# <<< The AI OS autostart <<<\n")
        with open(rc, "a", encoding="utf-8") as f:
            f.write(block)
        ok(f"autostart enabled (~/.bashrc hook — WSL/no-systemd) → starts on first shell")


def autostart_disable():
    if IS_WIN:
        p = _win_startup_cmd()
        if p.exists():
            p.unlink()
            ok("autostart disabled (removed Startup shortcut).")
        else:
            ok("autostart was not enabled.")
        return
    removed = False
    if _systemd_unit().exists():
        subprocess.run(["systemctl", "--user", "disable", "aios.service"], capture_output=True)
        _systemd_unit().unlink()
        removed = True
    rc = Path.home() / ".bashrc"
    if rc.exists() and _bashrc_marker() in rc.read_text(encoding="utf-8", errors="ignore"):
        lines = rc.read_text(encoding="utf-8").splitlines()
        out, skip = [], False
        for ln in lines:
            if ln.strip() == _bashrc_marker():
                skip = True
            if not skip:
                out.append(ln)
            if ln.strip() == "# <<< The AI OS autostart <<<":
                skip = False
        rc.write_text("\n".join(out) + "\n", encoding="utf-8")
        removed = True
    ok("autostart disabled." if removed else "autostart was not enabled.")


def cmd_autostart(args):
    action = getattr(args, "action", "status")
    if action == "enable":
        autostart_enable()
    elif action == "disable":
        autostart_disable()
    else:
        say("autostart: " + (f"{C.GRN}enabled{C.R}" if autostart_status() else f"{C.GRY}disabled{C.R}"))


# --------------------------------------------------------------------------- #
# Global `aios` command (run from anywhere, no ./)                             #
# --------------------------------------------------------------------------- #
def _cli_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def install_cli():
    """Put an `aios` shim on PATH so it runs from any directory without ./."""
    d = _cli_bin_dir()
    d.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        shim = d / "aios.cmd"
        shim.write_text(f'@echo off\r\ncall "{ROOT / "aios.cmd"}" %*\r\n', encoding="utf-8")
        ps = d / "aios.ps1"
        ps.write_text(f'& "{ROOT / "aios.ps1"}" @args\r\n', encoding="utf-8")
        _win_add_path(str(d))
        ok(f"installed `aios` → {shim}")
        say(f"  {C.GRY}Open a NEW terminal, then run `aios` from anywhere.{C.R}")
    else:
        shim = d / "aios"
        shim.write_text(f'#!/usr/bin/env bash\nexec "{ROOT / "aios"}" "$@"\n', encoding="utf-8")
        os.chmod(shim, 0o755)
        ok(f"installed `aios` → {shim}")
        if str(d) not in os.environ.get("PATH", "").split(":"):
            _ensure_bashrc_path(d)
            say(f"  {C.GRY}Added {d} to PATH — run `source ~/.bashrc` or open a new shell, then `aios` works anywhere.{C.R}")
        else:
            say(f"  {C.GRY}`aios` now runs from any directory.{C.R}")


def uninstall_cli():
    for name in ("aios", "aios.cmd", "aios.ps1"):
        p = _cli_bin_dir() / name
        if p.exists():
            p.unlink()
    ok("removed the global `aios` shim.")


def _ensure_bashrc_path(d: Path):
    line = f'export PATH="{d}:$PATH"'
    marker = "# >>> The AI OS PATH >>>"
    for rc in (Path.home() / ".bashrc", Path.home() / ".profile"):
        try:
            txt = rc.read_text(encoding="utf-8") if rc.exists() else ""
            if marker in txt:
                continue
            with open(rc, "a", encoding="utf-8") as f:
                f.write(f"\n{marker}\n{line}\n# <<< The AI OS PATH <<<\n")
        except Exception:
            pass


def _win_add_path(d: str):
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$p=[Environment]::GetEnvironmentVariable('Path','User');"
                        f"if($p -notlike '*{d}*'){{[Environment]::SetEnvironmentVariable('Path',($p.TrimEnd(';')+';{d}'),'User')}}"],
                       capture_output=True)
    except Exception:
        say(f"  {C.YEL}Add this folder to your PATH manually: {d}{C.R}")


def cli_installed() -> bool:
    return (_cli_bin_dir() / ("aios.cmd" if IS_WIN else "aios")).exists()


def cmd_install_cli(args):
    if getattr(args, "action", "install") == "uninstall":
        uninstall_cli()
    else:
        install_cli()


def cmd_claude_login(args):
    """Log the Claude Code CLI into your Pro/Max account (OAuth browser + code)."""
    claude = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude:
        die("`claude` CLI not found. It ships with claude-code-api / Claude Code — install it, "
            "then re-run.  (npm i -g @anthropic-ai/claude-code)")
    head("Claude login (Pro / Max)")
    say(f"{C.GRY}This opens your browser to authorize your Claude subscription. "
        f"Approve it (or paste the code back here).{C.R}\n")
    sub = "setup-token" if getattr(args, "token", False) else None
    cmd = [claude, sub] if sub else [claude]
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass
    say(f"\n{C.B}Done? Restart so agents pick up the login:{C.R} aios restart claudecode hub")


def cmd_url(args):
    _print_urls(load_config())


def cmd_wire(args):
    wire_openclaw_os(quiet=False)


# --------------------------------------------------------------------------- #
# Helpers for commands                                                         #
# --------------------------------------------------------------------------- #
def _select(service, specs) -> list:
    # Accept a string, a list of names, "all", or None.
    if not service or service == "all" or service == ["all"]:
        return list(specs.keys())
    names = [service] if isinstance(service, str) else list(service)
    if names == ["all"]:
        return list(specs.keys())
    out = []
    for n in names:
        if n == "all":
            return list(specs.keys())
        if n not in specs:
            die(f"unknown service '{n}'. Known: {', '.join(specs)} (or 'all')")
        out.append(n)
    return out


def _openclaw_os_url(cfg) -> str | None:
    if not cfg_get(cfg, "services.openclaw_os.enabled", True):
        return None
    port = int(cfg_get(cfg, "services.openclaw.port", 18789))
    return cfg_get(cfg, "health.openclaw_os", f"http://127.0.0.1:{port}/plugins/openclawos/")


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text(errors="ignore").lower()
    except Exception:
        return bool(os.environ.get("WSL_DISTRO_NAME"))


def _wsl_ip() -> str | None:
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
        return out[0] if out else None
    except Exception:
        return None


def _print_urls(cfg):
    hbp = int(cfg_get(cfg, "services.hub.port", 8787))
    say(f"{C.B}★ Control Room — talk to everything{C.R}")
    say(f"  {C.CYN}http://127.0.0.1:{hbp}/{C.R}   (the AIOS Hub dashboard)")
    if _is_wsl():
        ip = _wsl_ip()
        if ip:
            say(f"  {C.B}{C.YEL}WSL → open THIS in your Windows browser: http://{ip}:{hbp}/{C.R}")
            say(f"  {C.GRY}(127.0.0.1 may not forward from Windows to WSL — the IP above always works){C.R}")
    say(f"\n{C.B}Individual surfaces{C.R}")
    osurl = _openclaw_os_url(cfg)
    if osurl:
        say(f"  openclaw-os : {C.CYN}{osurl}{C.R}  (openclaw's dashboard)")
    hport = int(cfg_get(cfg, "services.hermes.port", 9119))
    say(f"  hermes dash : {C.CYN}http://127.0.0.1:{hport}/{C.R}")
    ocport = int(cfg_get(cfg, "services.opencode.port", 4096))
    say(f"  opencode API: {C.CYN}http://127.0.0.1:{ocport}/{C.R}")
    crp = int(cfg_get(cfg, "services.crewai.port", 4788))
    say(f"  crewai API  : {C.CYN}http://127.0.0.1:{crp}/{C.R}")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(prog="aios", description="The AI OS — one control surface for five agent projects")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="install toolchains+deps, create .env/config, render + wire")
    s.add_argument("--force", action="store_true", help="re-run the secrets wizard / overwrite")
    s.add_argument("--non-interactive", action="store_true")
    s.add_argument("--skip-keys", action="store_true", help="skip the model API-key wizard (add it later)")
    s.add_argument("--skip-tools", action="store_true")
    s.add_argument("--skip-install", action="store_true", help="skip dependency install (fast config-only)")
    s.add_argument("--skip-wire", action="store_true")
    s.set_defaults(func=cmd_setup)

    sub.add_parser("bootstrap", help="alias for setup").set_defaults(
        func=cmd_setup, force=False, non_interactive=False, skip_keys=False,
        skip_tools=False, skip_install=False, skip_wire=False)

    s = sub.add_parser("start", help="start service(s): opencode hermes openclaw crewai hub (or all)")
    s.add_argument("service", nargs="*", default=["all"])
    s.add_argument("--timeout", type=int, default=90)
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("stop", help="stop service(s)")
    s.add_argument("service", nargs="*", default=["all"])
    s.set_defaults(func=cmd_stop)

    s = sub.add_parser("restart", help="restart service(s) — forces a clean respawn (new code)")
    s.add_argument("service", nargs="*", default=["all"])
    s.add_argument("--timeout", type=int, default=90)
    s.set_defaults(func=cmd_restart)

    sub.add_parser("status", help="show service status").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="diagnose environment").set_defaults(func=cmd_doctor)

    s = sub.add_parser("test", help="run test suites")
    s.add_argument("service", nargs="?", default="all")
    s.add_argument("--smoke", action="store_true", help="health-based end-to-end smoke test")
    s.set_defaults(func=cmd_test)

    s = sub.add_parser("debug", help="dump resolved config/env/services")
    s.add_argument("service", nargs="?")
    s.set_defaults(func=cmd_debug)

    s = sub.add_parser("logs", help="tail a service log")
    s.add_argument("service", nargs="?")
    s.add_argument("-n", "--lines", type=int, default=40)
    s.set_defaults(func=cmd_logs)

    s = sub.add_parser("update", help="git pull + reinstall deps + re-render config")
    s.add_argument("--check", action="store_true", help="only report whether updates are available")
    s.add_argument("--force", action="store_true", help="reinstall even if already up to date")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("autostart", help="run The AI OS on login/boot")
    s.add_argument("action", nargs="?", choices=["enable", "disable", "status"], default="status")
    s.set_defaults(func=cmd_autostart)

    s = sub.add_parser("install-cli", help="put `aios` on your PATH so it runs from anywhere")
    s.add_argument("action", nargs="?", choices=["install", "uninstall"], default="install")
    s.set_defaults(func=cmd_install_cli)

    s = sub.add_parser("claude-login", help="log the Claude Code CLI into your Pro/Max account")
    s.add_argument("--token", action="store_true", help="use `claude setup-token` (long-lived token)")
    s.set_defaults(func=cmd_claude_login)

    sub.add_parser("url", help="print dashboard URLs").set_defaults(func=cmd_url)
    sub.add_parser("wire", help="(re)install the openclaw-os plugin into openclaw").set_defaults(func=cmd_wire)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\ninterrupted")
        sys.exit(130)
    except BrokenPipeError:
        # output was piped into head/Select-Object -First etc.; not an error
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.exit(0)
