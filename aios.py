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
    "openclaw_os": resolve_root("openclaw-os-main/openclaw-os-main", "openclaw-os-main", "openclaw-os"),
    "lifeos": resolve_root("LifeOS-main/LifeOS-main", "LifeOS-main", "LifeOS"),
}


# --------------------------------------------------------------------------- #
# Toolchain discovery                                                          #
# --------------------------------------------------------------------------- #
def find_tool(name: str) -> str | None:
    p = shutil.which(name)
    if p:
        return p
    home = Path.home()
    extra = {
        "bun": [home / ".bun/bin/bun.exe", home / ".bun/bin/bun"],
        "uv": [home / ".local/bin/uv.exe", home / ".local/bin/uv", home / ".cargo/bin/uv"],
        "pnpm": [home / "AppData/Roaming/npm/pnpm.cmd", home / ".local/share/pnpm/pnpm.exe",
                 home / ".local/share/pnpm/pnpm"],
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
    return specs


START_ORDER = ["opencode", "hermes", "hermes-gateway", "openclaw"]


def openclaw_env() -> dict:
    """Isolate openclaw in an aios-managed state dir (non-destructive)."""
    d = STATE / "openclaw"
    d.mkdir(parents=True, exist_ok=True)
    return {"OPENCLAW_STATE_DIR": str(d)}


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
                "node": "install Node >=20 from https://nodejs.org",
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

    # 7) wire openclaw-os plugin (best-effort; needs openclaw runnable)
    if cfg_get(cfg, "services.openclaw_os.enabled", True) and not args.skip_wire:
        wire_openclaw_os(quiet=True)

    say()
    ok("setup complete.")
    say(f"Next: {C.B}aios start{C.R}   then open the dashboard with {C.B}aios url{C.R}")


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
    data = load_env(ENV_EXAMPLE) if ENV_EXAMPLE.exists() else {}
    data.update(secrets)  # keep existing values

    if interactive:
        head("Secrets wizard (press Enter to keep current/blank)")
        prov = input(f"  Model provider [openrouter/anthropic/openai] "
                     f"({data.get('AIOS_LLM_PROVIDER','openrouter')}): ").strip()
        data["AIOS_LLM_PROVIDER"] = prov or data.get("AIOS_LLM_PROVIDER", "openrouter")
        key = input(f"  API key ({mask(data.get('AIOS_LLM_API_KEY',''))}): ").strip()
        if key:
            data["AIOS_LLM_API_KEY"] = key
        model = input(f"  Default model ({data.get('AIOS_DEFAULT_MODEL','anthropic/claude-opus-4.6')}): ").strip()
        data["AIOS_DEFAULT_MODEL"] = model or data.get("AIOS_DEFAULT_MODEL", "anthropic/claude-opus-4.6")
        say("  Optional channel tokens (Enter to skip):")
        for ck in CHANNEL_KEYS:
            cur = data.get(ck, "")
            val = input(f"    {ck} ({mask(cur)}): ").strip()
            if val:
                data[ck] = val
    else:
        for var, default in (("AIOS_LLM_PROVIDER", "openrouter"),
                             ("AIOS_LLM_API_KEY", ""),
                             ("AIOS_DEFAULT_MODEL", "anthropic/claude-opus-4.6")):
            envv = os.environ.get(var)
            if envv:  # explicit env var wins over example/blank
                data[var] = envv
            else:
                data.setdefault(var, default)
        if not data.get("AIOS_LLM_API_KEY"):
            warn("non-interactive: wrote .env skeleton (fill AIOS_LLM_API_KEY before start)")

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
    if not secrets.get("AIOS_LLM_API_KEY") and not any(secrets.get(v) for v in PROVIDER_VAR.values()):
        warn("no model API key in .env — agents may fail to answer. Run `aios setup`.")
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
        if rec and pid_alive(rec["pid"]):
            ok(f"{svc}: already running (pid {rec['pid']})")
            continue
        if spec.get("port") and port_in_use(spec["port"]):
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
    cfg = load_config()
    secrets = load_env(ENV_PATH)
    _install_all(cfg)
    render_native(cfg, secrets)
    if cfg_get(cfg, "lifeos.mount_skills", True):
        mount_lifeos(cfg)
    ok("update complete.")


def cmd_url(args):
    _print_urls(load_config())


def cmd_wire(args):
    wire_openclaw_os(quiet=False)


# --------------------------------------------------------------------------- #
# Helpers for commands                                                         #
# --------------------------------------------------------------------------- #
def _select(service, specs) -> list:
    if not service or service == "all":
        return [s for s in specs.keys()]
    if service not in specs:
        die(f"unknown service '{service}'. Known: {', '.join(specs)} (or 'all')")
    return [service]


def _openclaw_os_url(cfg) -> str | None:
    if not cfg_get(cfg, "services.openclaw_os.enabled", True):
        return None
    port = int(cfg_get(cfg, "services.openclaw.port", 18789))
    return cfg_get(cfg, "health.openclaw_os", f"http://127.0.0.1:{port}/plugins/openclawos/")


def _print_urls(cfg):
    say(f"{C.B}Front door (dashboard){C.R}")
    osurl = _openclaw_os_url(cfg)
    if osurl:
        say(f"  openclaw-os : {C.CYN}{osurl}{C.R}")
        say(f"  {C.GRY}pre-authenticated URL: run `node openclaw.mjs os url` in {PROJECTS['openclaw']}{C.R}"
            if PROJECTS["openclaw"] else "")
    hport = int(cfg_get(cfg, "services.hermes.port", 9119))
    say(f"  hermes dash : {C.CYN}http://127.0.0.1:{hport}/{C.R}")
    ocport = int(cfg_get(cfg, "services.opencode.port", 4096))
    say(f"  opencode API: {C.CYN}http://127.0.0.1:{ocport}/{C.R}")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(prog="aios", description="The AI OS — one control surface for five agent projects")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="install toolchains+deps, create .env/config, render + wire")
    s.add_argument("--force", action="store_true", help="re-run the secrets wizard / overwrite")
    s.add_argument("--non-interactive", action="store_true")
    s.add_argument("--skip-tools", action="store_true")
    s.add_argument("--skip-install", action="store_true", help="skip dependency install (fast config-only)")
    s.add_argument("--skip-wire", action="store_true")
    s.set_defaults(func=cmd_setup)

    sub.add_parser("bootstrap", help="alias for setup").set_defaults(
        func=cmd_setup, force=False, non_interactive=False, skip_tools=False, skip_install=False, skip_wire=False)

    s = sub.add_parser("start", help="start service(s)")
    s.add_argument("service", nargs="?", default="all")
    s.add_argument("--timeout", type=int, default=90)
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("stop", help="stop service(s)")
    s.add_argument("service", nargs="?", default="all")
    s.set_defaults(func=cmd_stop)

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

    sub.add_parser("update", help="reinstall deps + re-render config").set_defaults(func=cmd_update)
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
