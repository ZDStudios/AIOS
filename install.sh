#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# The AI OS — one-line installer for Linux / macOS / WSL
#
#   curl -fsSL https://raw.githubusercontent.com/ZDStudios/AIOS/main/install.sh | bash
#
# Asks for sudo ONCE at the start, then: installs system packages + toolchains,
# clones the repo, runs `aios setup` (deps, build, wire, full-control policy),
# puts `aios` on your PATH, and enables start-on-boot.
#
# Why not just run the whole thing as root? Because bun/uv/nvm install into
# $HOME. As root they'd land in /root and be root-owned, and every later
# non-root `aios` command would fail on them. So: root for the system bits,
# you for your own home. Both are set up in one pass.
#
# Env overrides:  AIOS_DIR=<path>  AIOS_BRANCH=<branch>  AIOS_NO_SETUP=1
#                 AIOS_NO_SUDO=1   AIOS_NO_AUTOSTART=1
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="https://github.com/ZDStudios/AIOS.git"
BRANCH="${AIOS_BRANCH:-main}"

c(){ printf '\033[1;36m%s\033[0m\n' "$*"; }
ok(){ printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m!\033[0m %s\n' "$*"; }
err(){ printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; }
have(){ command -v "$1" >/dev/null 2>&1; }

cat <<'BANNER'

  ████████ ██   ██ ███████     █████  ██     ██████  ███████
     ██    ██   ██ ██         ██   ██ ██    ██    ██ ██
     ██    ███████ █████      ███████ ██    ██    ██ ███████
     ██    ██   ██ ██         ██   ██ ██    ██    ██      ██
     ██    ██   ██ ███████    ██   ██ ██     ██████  ███████
                 Six AI agents. One operating system.
BANNER

# ── 0. privilege ─────────────────────────────────────────────────────────────
# The AI OS gives its agents full control of this machine, and wants to install
# a system-wide `aios` command plus a boot service. Get root once, up front,
# instead of dying halfway through a ten-minute build.
SUDO=""
KEEPALIVE_PID=""
cleanup(){ [ -n "$KEEPALIVE_PID" ] && kill "$KEEPALIVE_PID" 2>/dev/null || true; }
trap cleanup EXIT

if [ "$(id -u)" -eq 0 ]; then
  # `curl … | sudo bash`. Install toolchains into the *invoking* user's home,
  # then hand ownership back at the end.
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    TARGET_USER="$SUDO_USER"
    HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
    export HOME
    ok "running as root; installing for user '$TARGET_USER' (home: $HOME)"
  else
    TARGET_USER="root"
    warn "running as root with no SUDO_USER — installing everything as root"
  fi
else
  TARGET_USER="$(id -un)"
  if [ "${AIOS_NO_SUDO:-0}" = "1" ]; then
    warn "AIOS_NO_SUDO=1 — skipping system packages, global CLI and autostart"
  elif have sudo; then
    c "The AI OS installs system packages, a global \`aios\` command, and a boot"
    c "service — and its agents get full control of this machine. Requesting sudo:"
    if sudo -v; then
      SUDO="sudo"
      # Keep the sudo timestamp warm for the whole build so it never re-prompts.
      ( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null || exit; sleep 50; done ) &
      KEEPALIVE_PID=$!
      ok "sudo acquired"
    else
      warn "sudo declined — continuing without system packages/global CLI/autostart"
    fi
  else
    warn "no sudo on this system — continuing user-local only"
  fi
fi

DIR="${AIOS_DIR:-$HOME/AIOS}"

# ── 1. base prerequisites ────────────────────────────────────────────────────
for t in git curl; do
  have "$t" || { err "$t is required — install it and re-run."; exit 1; }
done
PY=""
for p in python3 python; do have "$p" && { PY="$p"; break; }; done
[ -n "$PY" ] || { err "Python 3.9+ is required — install it and re-run."; exit 1; }
ok "prerequisites: git, curl, $PY"

# ── 2. system packages (needs root; skipped cleanly without it) ───────────────
if [ -n "$SUDO" ] || [ "$(id -u)" -eq 0 ]; then
  c "Installing system packages…"
  if have apt-get; then
    $SUDO apt-get update -qq >/dev/null 2>&1 || true
    $SUDO apt-get install -y -qq build-essential python3-venv python3-pip \
      ca-certificates ripgrep unzip >/dev/null 2>&1 || warn "some apt packages failed"
  elif have dnf; then
    $SUDO dnf install -y -q gcc gcc-c++ make python3-pip ca-certificates ripgrep unzip \
      >/dev/null 2>&1 || warn "some dnf packages failed"
  elif have pacman; then
    $SUDO pacman -Sy --noconfirm --needed base-devel python-pip ripgrep unzip \
      >/dev/null 2>&1 || warn "some pacman packages failed"
  elif have brew; then
    brew install ripgrep >/dev/null 2>&1 || true   # brew must never run under sudo
  fi
  ok "system packages"
fi

# ── 3. clone or update ───────────────────────────────────────────────────────
if [ -d "$DIR/.git" ]; then
  c "Updating existing install at $DIR"
  git -C "$DIR" pull --ff-only || warn "could not fast-forward; keeping local state"
else
  c "Cloning The AI OS → $DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

# ── 4. toolchains ────────────────────────────────────────────────────────────
# WSL note: the inherited Windows PATH exposes Windows node/pnpm (under /mnt/c)
# to Linux. Those are the wrong binaries — we require a NATIVE Linux Node >=20
# and pnpm, and ignore anything resolving under /mnt/*.
c "Installing toolchains…"
have uv  || { c "· uv";  curl -LsSf https://astral.sh/uv/install.sh | sh; }
have bun || { c "· bun"; curl -fsSL https://bun.sh/install | bash; }

# Node >= 20 (Ubuntu/WSL default is often 18; openclaw + Next.js need >=20).
node_major=0
if have node; then
  case "$(command -v node)" in
    /mnt/*) node_major=0 ;;  # Windows node leaked into WSL → treat as absent
    *) node_major="$(node -v 2>/dev/null | sed 's/^v//; s/\..*//' | grep -E '^[0-9]+$' || echo 0)" ;;
  esac
fi
if [ "${node_major:-0}" -lt 20 ]; then
  c "· node >=20 (via nvm; found major '${node_major}')"
  export NVM_DIR="$HOME/.nvm"
  [ -s "$NVM_DIR/nvm.sh" ] || curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  # shellcheck disable=SC1090
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm install 22 >/dev/null 2>&1 && nvm use 22 >/dev/null 2>&1 || true
fi
# shellcheck disable=SC1090
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" 2>/dev/null && nvm use 22 >/dev/null 2>&1 || true

# pnpm — must be native (a /mnt/* pnpm runs the wrong Node).
native_pnpm(){ p="$(command -v pnpm 2>/dev/null || true)"; [ -n "$p" ] && case "$p" in /mnt/*) return 1 ;; *) return 0 ;; esac; return 1; }
if ! native_pnpm; then
  c "· pnpm (native Linux)"
  have npm && npm install -g pnpm >/dev/null 2>&1 || true
  native_pnpm || curl -fsSL https://get.pnpm.io/install.sh | SHELL="$(command -v bash)" sh -
fi

# make freshly-installed tools visible to this shell (and to aios subprocesses)
export PATH="$HOME/.local/share/pnpm:$HOME/.bun/bin:$HOME/.local/bin:$PATH"
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" 2>/dev/null && nvm use 22 >/dev/null 2>&1 || true

# ── 5. run aios setup (deps + build + wire + full-control policy) ────────────
if [ "${AIOS_NO_SETUP:-0}" = "1" ]; then
  ok "cloned; skipping setup (AIOS_NO_SETUP=1)"
else
  c "Running aios setup (deps, build, wire, exec policy — this takes a few minutes)…"
  "$PY" aios.py setup --non-interactive || warn "setup finished with warnings (run 'aios doctor')"
fi

# ── 6. global CLI + autostart (the parts that actually need root) ────────────
if [ -n "$SUDO" ] || [ "$(id -u)" -eq 0 ]; then
  if $SUDO ln -sf "$DIR/aios" /usr/local/bin/aios 2>/dev/null; then
    ok "installed \`aios\` → /usr/local/bin/aios (run it from anywhere)"
  else
    warn "could not symlink into /usr/local/bin; run './aios install-cli'"
  fi
  if [ "${AIOS_NO_AUTOSTART:-0}" != "1" ]; then
    "$PY" aios.py autostart enable >/dev/null 2>&1 && ok "start-on-boot enabled" \
      || warn "could not enable autostart (run 'aios autostart enable')"
  fi
else
  "$PY" aios.py install-cli >/dev/null 2>&1 || true
fi

# Hand everything back to the human if we built it as root on their behalf.
if [ "$(id -u)" -eq 0 ] && [ "${TARGET_USER}" != "root" ]; then
  c "Restoring ownership to $TARGET_USER…"
  chown -R "$TARGET_USER" "$DIR" "$HOME/.nvm" "$HOME/.bun" "$HOME/.local" 2>/dev/null || true
  ok "ownership restored"
fi

# ── 7. done ──────────────────────────────────────────────────────────────────
echo
ok "The AI OS is installed at: $DIR"
echo
warn "Full control is ON: every agent can run shell commands on this machine."
echo "   Guardrails still refuse rm -rf /, mkfs, fork bombs. Audit log: aios exec + hub → Audit."
echo "   Turn it off in aios.config.yaml → security.full_control: false"
echo
c "Next steps:"
echo "   aios setup --force     # enter your model provider + API key"
echo "   aios start             # bring the whole stack up"
echo "   aios url               # open the dashboard (prints the token URL for WSL)"
echo
