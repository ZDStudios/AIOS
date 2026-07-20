#!/usr/bin/env python3
"""
AIOS Supervised Updates — the agents review upstream changes before they land.

The projects AIOS bundles (openclaw, hermes, opencode, CrewAI, fabric, caveman,
ponytail) move fast, and a bad upstream bump can take the whole stack down. So
updates here are *supervised*: AIOS watches each upstream repo, and when one moves
ahead it gathers the evidence (commit messages + changed files), hands it to an
AI OS agent, and asks for a verdict before anything is touched.

    check  → what moved upstream, and exactly which files
    review → an agent reads the diff summary and returns SAFE / RISKY / BLOCK
    apply  → back up, swap in, reinstall deps, health-check
    verify → if the service doesn't come back healthy, ROLL BACK automatically

Risk tiers decide how much autonomy this gets:
  content  markdown/prompt-only (fabric patterns, caveman/ponytail skills). Nothing
           executes, a bad one is cosmetic and instantly reversible → may auto-apply
           when an agent says SAFE.
  service  runtime code with dependency trees (openclaw, hermes, opencode, CrewAI).
           A bad bump breaks the stack, so these always wait for your approval
           unless you explicitly opt in.

Pure standard library.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("AIOS_ROOT", Path(__file__).resolve().parent))
STATE = ROOT / ".aios"
PINS_FILE = STATE / "versions.json"
REPORT_FILE = STATE / "update_reports.json"
BACKUP_DIR = STATE / "backups"

# repo=None means "upstream not published / unknown" — we pin it and never touch it.
SOURCES = {
    "opencode":   {"repo": "anomalyco/opencode",        "dir": "opencode-dev",         "tier": "service"},
    "hermes":     {"repo": "NousResearch/Hermes-Agent", "dir": "hermes-agent-main",    "tier": "service"},
    "openclaw":   {"repo": "openclaw/openclaw",         "dir": "openclaw-main",        "tier": "service"},
    "crewai":     {"repo": "crewAIInc/crewAI",          "dir": "crewAI-main",          "tier": "service"},
    "claudecode": {"repo": None,                        "dir": "claude-code-api-main", "tier": "service"},
    "fabric":     {"repo": "danielmiessler/fabric",     "dir": "fabric-main",          "tier": "content"},
    "caveman":    {"repo": "JuliusBrussee/caveman",     "dir": "caveman-main",         "tier": "content"},
    "ponytail":   {"repo": "DietrichGebert/ponytail",   "dir": "ponytail-main",        "tier": "content"},
}

# What each project is used for — given to the agent so its risk call is grounded
# in how *we* consume the project, not just what changed upstream.
INTEGRATION_NOTES = {
    "opencode": "Run as a headless server on :4096. AIOS calls its HTTP API for coding tasks.",
    "hermes": "Run as an agent + dashboard on :9119, embedded in the hub via a frame-stripping proxy.",
    "openclaw": "The messaging gateway on :18789; hosts the openclaw-os plugin and all 28 channels. "
                "AIOS sets its exec policy to `yolo` and reads dist/channel-catalog.json.",
    "crewai": "Imported by services/crewai_service.py, which wraps it in an HTTP service on :4788.",
    "claudecode": "Wraps the `claude` CLI as an OpenAI-compatible API on :8000.",
    "fabric": "AIOS reads data/patterns/*/system.md only (255 prompt files). No code from it executes.",
    "caveman": "AIOS reads skills/caveman/SKILL.md as a system-prompt overlay and mounts its skills.",
    "ponytail": "AIOS reads skills/ponytail/SKILL.md as a system-prompt overlay and mounts its skills.",
}


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def pins() -> dict:
    return _load(PINS_FILE, {})


def reports() -> list:
    return _load(REPORT_FILE, [])


def _log_report(rec: dict):
    items = reports()
    items.insert(0, {**rec, "ts": time.time()})
    _save(REPORT_FILE, items[:60])


# --------------------------------------------------------------------------- #
# GitHub                                                                       #
# --------------------------------------------------------------------------- #
def _gh(path: str, timeout: int = 20):
    url = "https://api.github.com" + path
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "AIOS-supervised-updates",
    })
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:  # lifts the 60/hr anonymous rate limit
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def latest_commit(repo: str, branch: str = "") -> dict | None:
    """One API call when we already know the branch — the anonymous GitHub limit is
    60/hr and a full scan touches every bundled project, so this matters."""
    try:
        if not branch:
            branch = _gh(f"/repos/{repo}").get("default_branch", "main")
        c = _gh(f"/repos/{repo}/commits/{branch}")
        return {"sha": c["sha"], "branch": branch,
                "date": (c.get("commit", {}).get("committer") or {}).get("date", ""),
                "message": (c.get("commit", {}).get("message") or "").split("\n")[0][:200]}
    except Exception:
        return None


def compare(repo: str, base: str, head: str) -> dict | None:
    try:
        return _gh(f"/repos/{repo}/compare/{base}...{head}")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Check                                                                        #
# --------------------------------------------------------------------------- #
def check_one(name: str) -> dict:
    src = SOURCES.get(name)
    if not src:
        return {"name": name, "error": "unknown project"}
    out = {"name": name, "repo": src["repo"], "tier": src["tier"], "behind": False}
    if not src["repo"]:
        out["status"] = "pinned"
        out["note"] = "upstream repo unknown — this copy is pinned and never auto-updated"
        return out
    if not (ROOT / src["dir"]).exists():
        out["status"] = "absent"
        return out

    p = pins()
    cur = (p.get(name) or {}).get("sha")
    live = latest_commit(src["repo"], (p.get(name) or {}).get("branch", ""))
    if not live:
        out["status"] = "unreachable"
        out["note"] = ("could not reach GitHub — offline, or the anonymous API limit (60/hr) "
                       "is exhausted. Set GITHUB_TOKEN in .env to raise it to 5000/hr.")
        return out

    out["latest"] = live["sha"][:12]
    out["latest_message"] = live["message"]
    out["latest_date"] = live["date"]

    if not cur:
        # First sight of this project: record a baseline instead of claiming it's behind.
        p[name] = {"sha": live["sha"], "pinned_at": time.time(), "branch": live["branch"]}
        _save(PINS_FILE, p)
        out["status"] = "baseline"
        out["current"] = live["sha"][:12]
        out["note"] = "baseline recorded — future upstream commits will be reported here"
        return out

    out["current"] = cur[:12]
    if cur == live["sha"]:
        out["status"] = "current"
        return out

    out["status"] = "behind"
    out["behind"] = True
    cmp_ = compare(src["repo"], cur, live["sha"])
    if cmp_:
        out["ahead_by"] = cmp_.get("ahead_by", 0)
        out["commits"] = [
            {"sha": c["sha"][:8],
             "message": (c.get("commit", {}).get("message") or "").split("\n")[0][:160]}
            for c in (cmp_.get("commits") or [])[-30:]
        ]
        files = cmp_.get("files") or []
        out["files"] = [{"path": f.get("filename", ""), "status": f.get("status", ""),
                         "changes": f.get("changes", 0)} for f in files[:60]]
        out["files_total"] = len(files)
    return out


def check_all(only: list[str] | None = None) -> list[dict]:
    names = only or list(SOURCES)
    return [check_one(n) for n in names]


# --------------------------------------------------------------------------- #
# Agent review — the gate the user asked for                                   #
# --------------------------------------------------------------------------- #
REVIEW_SYS = (
    "You are the AI OS release reviewer. You decide whether an upstream dependency update is "
    "safe to apply to a running multi-agent system. Be skeptical and concrete: your job is to "
    "protect a working install, not to cheer for new versions.\n\n"
    "Reply in EXACTLY this shape, nothing else:\n"
    "VERDICT: SAFE|RISKY|BLOCK\n"
    "WHY: <one or two sentences, concrete>\n"
    "WATCH: <what could break in our integration, or 'nothing'>\n\n"
    "SAFE  = routine changes (docs, tests, prompts, additive features) with no sign of breaking "
    "changes to anything we depend on.\n"
    "RISKY = touches something we integrate with (config schema, CLI flags, ports, APIs, deps) "
    "and deserves a human look.\n"
    "BLOCK = clear breaking change, removed/renamed API, major version bump, or a migration is "
    "required.")


def build_review_prompt(u: dict) -> str:
    lines = [f"Project: {u['name']}  (upstream: {u.get('repo')})",
             f"How The AI OS uses it: {INTEGRATION_NOTES.get(u['name'], 'bundled dependency')}",
             f"Currently pinned: {u.get('current')}   →   Upstream now: {u.get('latest')}",
             f"Commits ahead: {u.get('ahead_by', '?')}", ""]
    if u.get("commits"):
        lines.append("Commit messages:")
        lines += [f"  - {c['sha']} {c['message']}" for c in u["commits"][:25]]
        lines.append("")
    if u.get("files"):
        lines.append(f"Changed files ({u.get('files_total', len(u['files']))} total, showing up to 40):")
        lines += [f"  {f['status']:>8}  {f['path']}  (+/-{f['changes']})" for f in u["files"][:40]]
    return "\n".join(lines)


def parse_verdict(text: str) -> dict:
    v, why, watch = "RISKY", "", ""
    for line in (text or "").splitlines():
        s = line.strip()
        up = s.upper()
        if up.startswith("VERDICT:"):
            raw = up.split(":", 1)[1].strip()
            v = next((x for x in ("SAFE", "RISKY", "BLOCK") if x in raw), "RISKY")
        elif up.startswith("WHY:"):
            why = s.split(":", 1)[1].strip()
        elif up.startswith("WATCH:"):
            watch = s.split(":", 1)[1].strip()
    if not why:
        why = (text or "").strip()[:300]
    return {"verdict": v, "why": why, "watch": watch}


def review(u: dict, ask) -> dict:
    """`ask(target, message, system)` -> str. Prefer opencode (reads code well),
    fall back to the Brain."""
    if not u.get("behind"):
        return {"verdict": "SAFE", "why": "no upstream changes", "watch": ""}
    prompt = build_review_prompt(u)
    try:
        text = ask("opencode", prompt, REVIEW_SYS)
        if not text or text.strip().startswith("⚠️"):
            text = ask("brain", prompt, REVIEW_SYS)
    except Exception as e:
        return {"verdict": "RISKY", "why": f"agent review failed: {e}", "watch": ""}
    out = parse_verdict(text)
    out["raw"] = (text or "")[:2000]
    return out


# --------------------------------------------------------------------------- #
# Apply — back up, swap, reinstall, health-check, roll back on failure         #
# --------------------------------------------------------------------------- #
def _project_dir(name: str) -> Path:
    """The real project root, allowing for the doubly-nested zip layout."""
    base = ROOT / SOURCES[name]["dir"]
    inner = base / SOURCES[name]["dir"]
    return inner if inner.exists() else base


def _install_cmd(d: Path) -> list[str] | None:
    """Detect the package manager from lockfiles so we can reinstall deps."""
    if (d / "bun.lockb").exists() or (d / "bun.lock").exists():
        return [shutil.which("bun") or "bun", "install", "--ignore-scripts"]
    if (d / "pnpm-lock.yaml").exists():
        return [shutil.which("pnpm") or "pnpm", "install", "--ignore-scripts"]
    if (d / "package-lock.json").exists() or (d / "package.json").exists():
        return [shutil.which("npm") or "npm", "install", "--ignore-scripts"]
    if (d / "uv.lock").exists() or (d / "pyproject.toml").exists():
        uv = shutil.which("uv")
        return [uv, "sync"] if uv else None
    return None


def _download_tarball(repo: str, sha: str, dest: Path) -> Path | None:
    """Fetch the upstream tarball and extract it; returns the extracted root."""
    url = f"https://api.github.com/repos/{repo}/tarball/{sha}"
    req = urllib.request.Request(url, headers={"User-Agent": "AIOS-supervised-updates"})
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            members = tf.getnames()
            if not members:
                return None
            top = members[0].split("/")[0]
            # Refuse path traversal / absolute members before extracting anything.
            for m in tf.getmembers():
                mp = (dest / m.name).resolve()
                if not str(mp).startswith(str(dest.resolve())):
                    return None
            tf.extractall(dest)
        return dest / top
    except Exception:
        return None


def apply(name: str, sha: str | None = None, health_url: str = "",
          restart: bool = True, log=print) -> dict:
    """Swap in the upstream version, reinstall deps, verify, roll back on failure."""
    src = SOURCES.get(name)
    if not src or not src["repo"]:
        return {"ok": False, "error": "no upstream for this project"}

    live = latest_commit(src["repo"]) if not sha else {"sha": sha}
    if not live:
        return {"ok": False, "error": "could not reach upstream"}
    sha = live["sha"]

    target = _project_dir(name)
    if not target.exists():
        return {"ok": False, "error": f"{target} not found"}

    stamp = int(time.time())
    backup = BACKUP_DIR / f"{name}.{stamp}"
    staging = STATE / "staging" / f"{name}.{stamp}"

    log(f"[{name}] downloading {sha[:12]}…")
    extracted = _download_tarball(src["repo"], sha, staging)
    if not extracted:
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": "download/extract failed (or unsafe tar member)"}

    # Preserve installed deps so a reinstall is incremental rather than from scratch.
    log(f"[{name}] backing up → {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(target), str(backup))
        shutil.move(str(extracted), str(target))
        for keep in ("node_modules", ".venv", "dist"):
            oldp, newp = backup / keep, target / keep
            if oldp.exists() and not newp.exists():
                try:
                    shutil.copytree(oldp, newp, symlinks=True)
                except Exception:
                    pass
    except Exception as e:
        # Put it back exactly as we found it.
        if not target.exists() and backup.exists():
            shutil.move(str(backup), str(target))
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": f"swap failed: {e}"}
    shutil.rmtree(staging, ignore_errors=True)

    # --- verify: do the packages still install, and does the service come back? ---
    problems = []
    cmd = _install_cmd(target)
    if cmd and cmd[0]:
        log(f"[{name}] reinstalling deps: {' '.join(cmd[:2])}")
        try:
            r = subprocess.run(cmd, cwd=str(target), capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                problems.append(f"dependency install failed: {(r.stderr or r.stdout)[-600:]}")
        except Exception as e:
            problems.append(f"dependency install error: {e}")

    if not problems and restart and src["tier"] == "service":
        log(f"[{name}] restarting service…")
        try:
            subprocess.run(["python", str(ROOT / "aios.py"), "restart", name],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=300,
                           env={**os.environ, "AIOS_NO_UPDATE_CHECK": "1"})
        except Exception as e:
            problems.append(f"restart error: {e}")
        if health_url and not _wait_health(health_url, 90):
            problems.append(f"service did not become healthy at {health_url} within 90s")

    if problems:
        log(f"[{name}] FAILED verification — rolling back")
        try:
            shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(backup), str(target))
            if restart and src["tier"] == "service":
                subprocess.run(["python", str(ROOT / "aios.py"), "restart", name],
                               cwd=str(ROOT), capture_output=True, text=True, timeout=300,
                               env={**os.environ, "AIOS_NO_UPDATE_CHECK": "1"})
        except Exception as e:
            return {"ok": False, "rolled_back": False, "error": f"ROLLBACK FAILED: {e}. "
                    f"Your previous copy is at {backup}", "problems": problems}
        _log_report({"kind": "rolled_back", "project": name, "sha": sha[:12], "problems": problems})
        return {"ok": False, "rolled_back": True, "problems": problems,
                "error": "update verification failed — rolled back to the previous version"}

    p = pins()
    p[name] = {"sha": sha, "pinned_at": time.time(),
               "previous": (p.get(name) or {}).get("sha", ""), "backup": str(backup)}
    _save(PINS_FILE, p)
    _log_report({"kind": "applied", "project": name, "sha": sha[:12]})
    log(f"[{name}] updated to {sha[:12]} ✓")
    return {"ok": True, "sha": sha[:12], "backup": str(backup)}


def _wait_health(url: str, timeout: int) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except urllib.error.HTTPError:
            return True   # any HTTP response means it's listening
        except Exception:
            time.sleep(2)
    return False


def rollback(name: str) -> dict:
    """Restore the most recent backup for a project."""
    cands = sorted(BACKUP_DIR.glob(f"{name}.*"), reverse=True)
    if not cands:
        return {"ok": False, "error": "no backup found"}
    target = _project_dir(name)
    try:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(cands[0], target, symlinks=True)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _log_report({"kind": "manual_rollback", "project": name, "from": cands[0].name})
    return {"ok": True, "restored_from": cands[0].name}


def prune_backups(keep: int = 2):
    """Old project copies are big — keep only the most recent few per project."""
    if not BACKUP_DIR.exists():
        return
    for name in SOURCES:
        for old in sorted(BACKUP_DIR.glob(f"{name}.*"), reverse=True)[keep:]:
            shutil.rmtree(old, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        for u in check_all():
            print(json.dumps(u if "-v" in sys.argv else
                             {k: u.get(k) for k in ("name", "status", "current", "latest",
                                                    "ahead_by", "tier", "note")}, indent=2))
    else:
        print(json.dumps({"sources": list(SOURCES), "pins": pins()}, indent=2))
