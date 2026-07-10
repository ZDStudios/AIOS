#!/usr/bin/env python3
"""
AIOS Tools — the "body" half of the brain-and-body split.

Full-control mode (`security.full_control`, on by default) gives every agent the
machine: shell, filesystem, network, the lot. This module is the single choke
point those capabilities go through, so there is exactly one place that applies
the guardrails and writes the audit log.

Also home to two catalogs the hub renders:
  channels()  the 28 messaging channels OpenClaw can bridge (read from its own
              generated catalog, not a list I typed out by hand, so it stays
              correct when OpenClaw adds one).
  skills()    bundled SKILL.md packs + whatever the self-improving loop wrote.
"""
from __future__ import annotations

import io
import json
import os
import platform
import subprocess
import time
from pathlib import Path

import aios_brain as brain
import aios_sec as sec

ROOT = Path(os.environ.get("AIOS_ROOT", Path(__file__).resolve().parent))
IS_WIN = platform.system() == "Windows"


def full_control() -> bool:
    return os.environ.get("AIOS_FULL_CONTROL", "1") == "1"


def guardrails_on() -> bool:
    return os.environ.get("AIOS_GUARDRAILS", "1") == "1"


def exec_timeout() -> int:
    try:
        return int(os.environ.get("AIOS_EXEC_TIMEOUT", "120"))
    except ValueError:
        return 120


# --------------------------------------------------------------------------- #
# Shell — the capability that makes "full control" mean something              #
# --------------------------------------------------------------------------- #
def shell(cmd: str, actor: str = "brain", cwd: str | None = None,
          timeout: int | None = None) -> dict:
    """Run a command as the user who installed AIOS. Audited, guardrailed, bounded."""
    cmd = (cmd or "").strip()
    if not cmd:
        return {"ok": False, "code": -1, "out": "", "err": "empty command", "blocked": False}

    if not full_control():
        brain.audit(actor, "shell.denied", cmd, ok=False)
        return {"ok": False, "code": -1, "out": "", "blocked": True,
                "err": "full control is disabled (security.full_control: false in aios.config.yaml)"}

    allowed, why = sec.guard(cmd, enabled=guardrails_on())
    if not allowed:
        brain.audit(actor, "shell.blocked", f"{cmd}  [{why}]", ok=False)
        return {"ok": False, "code": -1, "out": "", "blocked": True,
                "err": f"blocked by guardrail: {why}. Disable with security.guardrails: false."}

    shell_cmd = (["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd] if IS_WIN
                 else ["/bin/bash", "-lc", cmd])
    started = time.time()
    try:
        p = subprocess.run(shell_cmd, cwd=cwd or str(ROOT), capture_output=True, text=True,
                           timeout=timeout or exec_timeout(), errors="replace")
        out, err, code = p.stdout or "", p.stderr or "", p.returncode
    except subprocess.TimeoutExpired:
        brain.audit(actor, "shell.timeout", cmd, ok=False)
        return {"ok": False, "code": -1, "out": "", "blocked": False,
                "err": f"timed out after {timeout or exec_timeout()}s"}
    except Exception as e:
        brain.audit(actor, "shell.error", f"{cmd} :: {e}", ok=False)
        return {"ok": False, "code": -1, "out": "", "err": str(e), "blocked": False}

    brain.audit(actor, "shell", f"$ {cmd}\n(exit {code}, {time.time()-started:.1f}s)", ok=code == 0)
    return {"ok": code == 0, "code": code, "out": out[-8000:], "err": err[-4000:], "blocked": False}


# --------------------------------------------------------------------------- #
# Channels — read OpenClaw's own generated catalog                             #
# --------------------------------------------------------------------------- #
# Channels built into OpenClaw core rather than shipped as plugin packages, so
# they never appear in dist/channel-catalog.json.
CORE_CHANNELS = [
    {"id": "telegram", "label": "Telegram", "blurb": "first-class Telegram bot tokens.",
     "envVars": ["TELEGRAM_BOT_TOKEN"], "docsPath": "/channels/telegram", "source": "core"},
    {"id": "imessage", "label": "iMessage", "blurb": "native macOS iMessage bridge (BlueBubbles optional).",
     "envVars": [], "docsPath": "/channels/imessage", "source": "core"},
]

_CATALOG_CACHE: list | None = None


def _catalog_path() -> Path:
    return ROOT / "openclaw-main" / "openclaw-main" / "dist" / "channel-catalog.json"


def channels() -> list[dict]:
    """Every messaging channel the gateway can bridge, with configured-state."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        out = [dict(c) for c in CORE_CHANNELS]
        p = _catalog_path()
        if p.exists():
            try:
                data = json.loads(io.open(p, encoding="utf-8").read())
                for e in data.get("entries", []):
                    ch = (e.get("openclaw") or {}).get("channel") or {}
                    if not ch.get("id"):
                        continue
                    out.append({
                        "id": ch["id"],
                        "label": ch.get("label") or ch["id"],
                        "blurb": ch.get("blurb", ""),
                        "envVars": list(ch.get("envVars") or []),
                        "docsPath": ch.get("docsPath", ""),
                        "source": e.get("source", "community"),
                        "package": e.get("name", ""),
                    })
            except Exception:
                pass
        out.sort(key=lambda c: c["label"].lower())
        _CATALOG_CACHE = out
    env = _env_all()
    return [{**c, "configured": bool(c["envVars"]) and all(env.get(v) for v in c["envVars"])}
            for c in _CATALOG_CACHE]


def _env_all() -> dict:
    d = dict(os.environ)
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                d.setdefault(k.strip(), v.strip())
    return d


# --------------------------------------------------------------------------- #
# Skills — bundled packs + what the self-improving loop taught itself           #
# --------------------------------------------------------------------------- #
def _read_skill(d: Path) -> dict | None:
    f = d / "SKILL.md"
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8", errors="replace")
    name, desc = d.name, ""
    if text.startswith("---"):
        end = text.find("---", 3)
        for line in text[3:end if end > 0 else 200].splitlines():
            if line.lower().startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.lower().startswith("description:"):
                desc = line.split(":", 1)[1].strip()
    if not desc:
        body = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
        desc = body[0][:160] if body else ""
    return {"name": name, "description": desc, "path": str(d.relative_to(ROOT)),
            "learned": "learned" in d.parts}


def skills() -> list[dict]:
    out = []
    for base in (ROOT / "skills", ROOT / "skills" / "learned"):
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and d.name != "learned":
                s = _read_skill(d)
                if s:
                    out.append(s)
    return out


def install_skill(name: str, content: str) -> dict:
    """ClawHub-style install: drop a SKILL.md into skills/<name>/ where every agent mounts it."""
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip().lower())[:60]
    if not slug:
        return {"ok": False, "error": "bad skill name"}
    d = ROOT / "skills" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    brain.audit("hub", "skill.install", slug)
    return {"ok": True, "slug": slug, "path": str(d.relative_to(ROOT))}


def learn_skill(name: str, content: str, task: str = "") -> dict:
    d = ROOT / "skills" / "learned" / "".join(
        ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip().lower())[:60]
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    brain.skill_add(name, str(d.relative_to(ROOT)), task)
    brain.audit("curator", "skill.learn", name)
    return {"ok": True, "path": str(d.relative_to(ROOT))}


if __name__ == "__main__":
    print(json.dumps({"full_control": full_control(), "guardrails": guardrails_on(),
                      "channels": len(channels()), "skills": len(skills())}, indent=2))
    for c in channels():
        print(f"  {'[x]' if c['configured'] else '[ ]'} {c['id']:<20} {c['blurb'][:60]}")
