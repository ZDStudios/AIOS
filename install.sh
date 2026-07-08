#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# The AI OS — one-line installer for Linux / macOS / WSL
#
#   curl -fsSL https://raw.githubusercontent.com/ZDStudios/AIOS/main/install.sh | bash
#
# Clones the repo, installs the toolchains (uv, bun, pnpm, Node), then runs
# `aios setup` to install every project's deps, build, and wire it together.
#
# Env overrides:  AIOS_DIR=<path>   AIOS_BRANCH=<branch>   AIOS_NO_SETUP=1
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="https://github.com/ZDStudios/AIOS.git"
DIR="${AIOS_DIR:-$HOME/AIOS}"
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
                 Five AI agents. One operating system.
BANNER

# ── 1. base prerequisites ────────────────────────────────────────────────────
for t in git curl; do
  have "$t" || { err "$t is required — install it and re-run."; exit 1; }
done
PY=""
for p in python3 python; do have "$p" && { PY="$p"; break; }; done
[ -n "$PY" ] || { err "Python 3.9+ is required — install it and re-run."; exit 1; }
ok "prerequisites: git, curl, $PY"

# ── 2. clone or update ───────────────────────────────────────────────────────
if [ -d "$DIR/.git" ]; then
  c "Updating existing install at $DIR"
  git -C "$DIR" pull --ff-only || warn "could not fast-forward; keeping local state"
else
  c "Cloning The AI OS → $DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

# ── 3. toolchains (aios finds these even if not yet on PATH) ──────────────────
c "Installing toolchains…"
have uv   || { c "· uv";   curl -LsSf https://astral.sh/uv/install.sh | sh; }
have bun  || { c "· bun";  curl -fsSL https://bun.sh/install | bash; }
have pnpm || { c "· pnpm"; curl -fsSL https://get.pnpm.io/install.sh | SHELL="$(command -v bash)" sh -; }
if ! have node; then
  c "· node (via nvm)"
  export NVM_DIR="$HOME/.nvm"
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  # shellcheck disable=SC1090
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm install --lts >/dev/null 2>&1 || true
fi

# make freshly-installed tools visible to this shell (and to aios subprocesses)
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$HOME/.local/share/pnpm:$PATH"
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" 2>/dev/null || true

# ── 4. run aios setup (deps + build + wire) ──────────────────────────────────
if [ "${AIOS_NO_SETUP:-0}" = "1" ]; then
  ok "cloned; skipping setup (AIOS_NO_SETUP=1)"
else
  c "Running aios setup (installs deps, builds, wires — this takes a few minutes)…"
  "$PY" aios.py setup --non-interactive || warn "setup finished with warnings (run 'aios doctor')"
fi

# ── 5. done ──────────────────────────────────────────────────────────────────
echo
ok "The AI OS is installed at: $DIR"
echo
c "Next steps:"
echo "   cd \"$DIR\""
echo "   ./aios setup --force     # enter your model provider + API key"
echo "   ./aios start             # bring the whole stack up"
echo "   ./aios url               # open the dashboard"
echo
