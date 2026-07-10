#!/usr/bin/env python3
"""
AIOS Security — the gate in front of full-control mode.

The AI OS ships with `security.full_control: true`: every agent can run shell
commands, edit any file, and drive the machine it was installed on. That is the
whole point of an agent OS — and it is also exactly the "ambient authority"
posture that got OpenClaw a critical RCE (CVE-2026-25253). Handing agents the
machine and *also* leaving the control plane open on 0.0.0.0 with
`Access-Control-Allow-Origin: *` would reproduce that bug on purpose.

So full control is paired with a real gate:

  1. Loopback is trusted.  Requests from 127.0.0.1/::1 need no token, so the
     local browser keeps working with zero friction.
  2. Everything else needs a token.  `AIOS_HUB_TOKEN` (generated at setup) must
     arrive as `Authorization: Bearer <t>` or `?token=<t>`. This is what makes
     binding to 0.0.0.0 for WSL survivable.
  3. CSRF is closed.  A page on the internet can otherwise POST to
     http://127.0.0.1:8787/api/action and own the box, because loopback is
     trusted. Cross-origin requests are rejected unless they carry the token,
     and CORS no longer echoes `*`.
  4. DNS-rebinding is closed.  The Host header must be a literal IP or a
     known-local name, so `evil.com -> 127.0.0.1` can't reach the hub.
  5. Everything destructive is audited, and a small guardrail list refuses the
     handful of commands that destroy the host rather than the task.

Guardrails are `security.guardrails: true` by default and can be turned off in
one line. They are not a sandbox and they are not a security boundary against a
hostile model — they are a seatbelt against a confused one.
"""
from __future__ import annotations

import ipaddress
import os
import re
import secrets
from urllib.parse import urlparse, parse_qs

TOKEN_ENV = "AIOS_HUB_TOKEN"

# Endpoints that stay open even without a token (read-only, non-sensitive).
PUBLIC_PATHS = {"/health"}

# Local hostnames a browser legitimately uses to reach the hub.
_LOCAL_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "aios.local"}


def new_token() -> str:
    return "aios_" + secrets.token_urlsafe(24)


def get_token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr.strip("[]")).is_loopback
    except ValueError:
        return False


def _allowed_hosts() -> set[str]:
    extra = os.environ.get("AIOS_ALLOWED_HOSTS", "")
    return _LOCAL_NAMES | {h.strip().lower() for h in extra.split(",") if h.strip()}


def _host_ok(host_header: str) -> bool:
    """Reject DNS-rebinding: Host must be an IP or a known-local name."""
    if not host_header:
        return True  # HTTP/1.0 client; the loopback/token checks still apply
    host = host_header.rsplit(":", 1)[0] if not host_header.startswith("[") else \
        host_header.split("]")[0] + "]"
    if host.lower() in _allowed_hosts():
        return True
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True  # any literal IP is fine — no rebinding possible
    except ValueError:
        return False


def _origin_ok(origin: str, host_header: str) -> bool:
    """Same-origin (or no Origin at all) is fine; anything else must bring a token."""
    if not origin or origin == "null":
        return True
    try:
        u = urlparse(origin)
    except Exception:
        return False
    if u.hostname and (u.hostname.lower() in _LOCAL_NAMES or is_loopback(u.hostname)):
        return True
    return bool(host_header) and origin.split("://", 1)[-1] == host_header


def token_from_request(path: str, headers) -> str:
    auth = headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    hdr = headers.get("X-AIOS-Token", "").strip()
    if hdr:
        return hdr
    q = parse_qs(urlparse(path).query)
    return (q.get("token") or [""])[0].strip()


def check(*, path: str, method: str, client_ip: str, headers) -> tuple[bool, str]:
    """Returns (allowed, reason). Reason is safe to show the caller."""
    bare = urlparse(path).path
    if bare in PUBLIC_PATHS:
        return True, ""

    if not _host_ok(headers.get("Host", "")):
        return False, "bad Host header (DNS-rebinding guard)"

    token = get_token()
    supplied = token_from_request(path, headers)
    has_token = bool(token) and secrets.compare_digest(supplied, token)

    if has_token:
        return True, ""

    # A page on the internet can reach http://127.0.0.1:8787 from the user's own
    # browser. Loopback is trusted below, so without this check that page would
    # inherit full control. Cross-origin therefore always requires the token.
    origin = headers.get("Origin", "")
    if not _origin_ok(origin, headers.get("Host", "")):
        return False, "cross-origin request without a token"

    if is_loopback(client_ip):
        return True, ""

    if not token:
        return False, ("hub token is not set — run `aios setup` (or set AIOS_HUB_TOKEN) "
                       "before reaching the hub from another machine")
    return False, "missing or invalid token (send Authorization: Bearer <AIOS_HUB_TOKEN>)"


def cors_headers(headers) -> dict:
    """Never `*`. Echo only origins we already decided are same-origin/local."""
    origin = headers.get("Origin", "")
    if origin and _origin_ok(origin, headers.get("Host", "")):
        return {"Access-Control-Allow-Origin": origin,
                "Vary": "Origin",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-AIOS-Token",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS"}
    return {"Vary": "Origin"}


# --------------------------------------------------------------------------- #
# Exec guardrails — a seatbelt, not a sandbox.                                 #
# --------------------------------------------------------------------------- #
GUARDRAILS = [
    (r"--no-preserve-root", "rm --no-preserve-root"),
    (r"\bmkfs(\.\w+)?\b", "filesystem format"),
    (r"\bdd\b[^|;]*\bof=/dev/(sd|nvme|hd|disk)", "raw write to a block device"),
    (r">\s*/dev/(sd|nvme|hd|disk)\w*", "raw write to a block device"),
    (r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bchmod\s+-R\s+777\s+/\s*$", "world-writable /"),
    (r"\bDROP\s+DATABASE\b", "database drop"),
    (r"\bformat\s+[cC]:", "format C:"),
    (r"Remove-Item\s+.*-Recurse.*\s+[cC]:\\?\s*$", "recursive delete of C:\\"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "host shutdown/reboot"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), why) for p, why in GUARDRAILS]

# Paths whose recursive deletion wrecks the host rather than the workspace. Compared
# lowercased, with quotes and trailing slashes/backslashes stripped, so "/" -> "",
# "C:\" -> "c:" and "/home/" -> "/home".
_ROOT_TARGETS = {"", "/*", "~", "~/*", "$home", "${home}", "%userprofile%",
                 "/root", "/home", "/etc", "/usr", "/var", "/boot", "/bin", "/sbin",
                 "/lib", "/opt", "/sys", "/proc", "c:", "c:\\*", "/mnt/c"}


def _rm_wipes_root(cmd: str) -> bool:
    """`rm -rf /` and friends. A regex can't see past trailing flags like
    `--no-preserve-root`, so tokenize and inspect the actual arguments."""
    try:
        import shlex
        toks = shlex.split(cmd, posix=True)
    except ValueError:
        toks = cmd.split()
    for i, t in enumerate(toks):
        if t == "rm" or t.endswith("/rm"):
            recursive, targets = False, []
            for x in toks[i + 1:]:
                if x.startswith("--"):
                    if x in ("--recursive", "--force"):
                        recursive = recursive or x == "--recursive"
                    continue
                if x.startswith("-") and len(x) > 1:
                    if "r" in x.lower():
                        recursive = True
                    continue
                targets.append(x)
            if not recursive:
                continue
            for tgt in targets:
                norm = tgt.strip("'\"").rstrip("/\\").lower()
                if norm in _ROOT_TARGETS:
                    return True
    return False


def guard(cmd: str, enabled: bool = True) -> tuple[bool, str]:
    """(allowed, reason). Blocks commands that destroy the host rather than do the task."""
    if not enabled:
        return True, ""
    c = " ".join((cmd or "").split())
    if _rm_wipes_root(c):
        return False, "recursive delete of a root path"
    for rx, why in _COMPILED:
        if rx.search(c):
            return False, why
    return True, ""


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "token":
        print(new_token())
    else:
        print(json.dumps({"token_set": bool(get_token())}))
