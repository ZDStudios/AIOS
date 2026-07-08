# BUILD PROMPT — "The AI OS": unify five agent projects into one orchestrated system

> Paste everything below the line into a capable coding agent (Claude Code, opencode, etc.)
> running **inside** `C:\Users\Zayn\Desktop\The AI OS`. It is self-contained.

---

## ROLE

You are a senior platform engineer. Inside this directory sit five independent open‑source
AI projects that were downloaded separately. Your job is to **integrate them into one coherent,
auto-configured, easy-to-run system** called **"The AI OS" (`aios`)** — with a single control
command, one shared config, unified testing and debugging, and a dashboard as the front door.

You will NOT literally concatenate five codebases into one file (they are three different
runtimes and package managers — that is impossible and would break everything). The deliverable
that satisfies "one file / everything working / auto-configured / easy setup" is:

- **one control script** (`aios`) that drives all five projects, and
- **one config file** (`aios.config.yaml`) + **one secrets file** (`.env`) as the single source of truth.

Correctness and "it actually launches" beat cleverness. Verify every step against the real files —
never invent a command; read each project's `package.json` / `pyproject.toml` / scripts first.

## THE FIVE PROJECTS (verify each real root — folders are double-nested `X-main/X-main`)

1. **opencode** — root: `opencode-dev/opencode-dev`
   - Bun `1.3.14` monorepo. Dev: `bun install` then `bun run dev` (→ `packages/opencode/src/index.ts`).
   - Has `packages/server`, `packages/sdk`, `packages/tui`, `packages/desktop`. Exposes an HTTP server + SDK.
   - Root `test` script intentionally errors ("do not run tests from root") — run tests per-package.
   - **Role: the coding-agent engine.** Expose its server so other components can call it.

2. **hermes-agent** — root: `hermes-agent-main/hermes-agent-main`
   - Python `>=3.11,<3.14`, managed with **uv**. Entry points: `cli.py`, `gateway/`, `cron/`.
   - Has `docker-compose.yml` + `docker-compose.windows.yml`, `setup-hermes.sh`, `hermes_bootstrap.py`.
   - Model-agnostic (OpenRouter / OpenAI / Nous Portal / custom endpoint). Built-in memory + skills + cron + multi-channel gateway.
   - **Role: the autonomous background operator** (persistent memory, scheduled automations, learning loop).

3. **openclaw** — root: `openclaw-main/openclaw-main`
   - Node, **pnpm** workspace. Bin: `openclaw` → `openclaw.mjs`. Build likely `pnpm install && pnpm build` (confirm via `package.json` scripts).
   - "Multi-channel AI gateway with extensible messaging integrations" (Telegram/Discord/Slack/etc.), plugin SDK, skills.
   - **Role: the messaging/channel gateway** and plugin host.

4. **openclaw-os** — root: `openclaw-os-main/openclaw-os-main`
   - Node `>=20`, **pnpm** (`claw-client`, `claw-plugin`). Scripts: `build`, `test`, `typecheck`, `lint`.
   - Generative-UI workspace + an OpenClaw plugin (OpenUI Lang). It is the **web dashboard** for openclaw.
   - **Role: the single pane of glass / front door UI** for the whole AI OS.

5. **LifeOS** — root: `LifeOS-main/LifeOS-main`
   - TypeScript/Bun. Contains `LifeOS/` (Skills, Workflows, Tools), `install/`, `Tools/*.ts`.
   - Personal-context + skills/workflows harness (Current State → Ideal State).
   - **Role: the shared identity/context + skills layer** mounted into the agents so they "know the user."

## TARGET ARCHITECTURE (how they connect)

```
                         ┌─────────────────────────────┐
                         │   openclaw-os (dashboard)    │  ← the single UI / front door
                         └───────────────┬─────────────┘
                                         │ plugin + HTTP
        ┌────────────────────────────────┼─────────────────────────────┐
        │                                │                              │
┌───────▼────────┐              ┌────────▼─────────┐          ┌─────────▼─────────┐
│   openclaw     │              │     hermes       │          │     opencode      │
│ channel gateway│              │ autonomous agent │          │  coding engine    │
│ (Telegram/…)   │              │ memory+cron+chan │          │  (server + SDK)   │
└───────┬────────┘              └────────┬─────────┘          └─────────┬─────────┘
        └────────────────────────────────┼──────────────────────────────┘
                                          │  reads shared context/skills
                                 ┌────────▼─────────┐
                                 │     LifeOS       │  ← shared context + skills mount
                                 └──────────────────┘

  Single source of truth:  aios.config.yaml  +  .env   (rendered into each project's config)
  Single control surface:  ./aios <command>
```

Design decisions to implement:
- **openclaw-os is the default UI.** Everything the user launches surfaces here.
- **hermes and openclaw both provide "gateway/channel" features that overlap.** Do NOT try to merge
  their code. Run them as separate services on distinct ports, both reachable from the dashboard;
  document the overlap and let config enable/disable each. Default: openclaw = channels, hermes = autonomous jobs.
- **opencode runs in server mode** so hermes/openclaw/dashboard can delegate coding tasks to it via its SDK/HTTP.
- **LifeOS is the shared knowledge layer:** its skills/workflows/context files are symlinked or copied
  into the skill directories that hermes and openclaw already support (both reference the agentskills.io standard).
- **One model-provider config** (base URL + API key + default model) in `.env` is propagated to all four agents.

## DELIVERABLE 1 — the single control file `aios`

Create a cross-platform launcher at the repo root. Because hermes already requires Python, implement the
core as one Python file `aios.py`, plus thin wrappers `aios.ps1` (PowerShell, primary — the user is on
Windows 11) and `aios` (POSIX sh) so `./aios <cmd>` works everywhere. Subcommands:

- `aios setup` / `aios bootstrap` — idempotent first-run:
  1. Detect/install toolchains if missing: **bun**, **pnpm**, **uv**, Node ≥20 (print manual instructions if auto-install not possible; never silently fail).
  2. Install deps per project with the correct manager: opencode → `bun install`; LifeOS → `bun install`; openclaw + openclaw-os → `pnpm install`; hermes → `uv sync`.
  3. Run an interactive (and `--non-interactive`/env-driven) wizard to create `.env` and `aios.config.yaml`; never overwrite existing secrets without `--force` + a backup.
  4. Render each project's own config/env from the shared config (see Deliverable 2). Mount LifeOS skills into hermes/openclaw skill dirs.
- `aios start [service|all]` — start services with correct working dirs + env, allocate ports from config, wait on health checks, stream unified color-coded logs. Default `all` order: opencode(server) → hermes → openclaw → openclaw-os.
- `aios stop [service|all]` — graceful stop; clean up child processes/ports (Windows + POSIX).
- `aios status` — show each service: running?, port, health endpoint, pid.
- `aios doctor` — diagnose: tool versions, missing env vars, port conflicts, failed health checks, wrong Python/Node/Bun versions; print exact fix for each problem. Must exit non-zero on any hard failure.
- `aios test [service|all]` — run each project's real test suite (opencode: per-package `bun test`; LifeOS: `bun test`; openclaw/openclaw-os: `pnpm -r test`; hermes: `uv run pytest`). Aggregate a pass/fail summary; non-zero exit on failure.
- `aios debug [service]` — verbose launch: max log level, tail logs, dump resolved config + env (secrets masked), hit each health endpoint, print a component-by-component readiness report.
- `aios logs [service]` — tail unified logs from `.aios/logs/`.
- `aios update` — reinstall deps / re-render config after project updates.

Implementation rules for `aios.py`:
- Pure standard-library where possible (subprocess, argparse, pathlib, json). If you use a dep (e.g. `pyyaml`, `rich`), pin it and install it into hermes's uv env or a dedicated `.aios/venv`.
- All state under a single `.aios/` dir (logs, pids, rendered configs, backups). Add `.aios/` and `.env` to a repo-root `.gitignore`.
- Resolve the real (double-nested) project roots dynamically; fail loudly if a project is missing.
- Cross-platform process management: on Windows use PowerShell-friendly process handling; do not rely on POSIX-only signals.

## DELIVERABLE 2 — single source of truth: `aios.config.yaml` + `.env`

- `.env` holds secrets only: `AIOS_LLM_BASE_URL`, `AIOS_LLM_API_KEY`, `AIOS_DEFAULT_MODEL`, plus per-channel tokens (Telegram/Discord/Slack), each optional.
- `aios.config.yaml` holds non-secret wiring: enabled services, ports, model routing per agent, LifeOS skill mount paths, log level, health-check URLs. Ship `aios.config.example.yaml` and `.env.example`.
- Provide a **renderer**: `aios setup` reads the shared config and writes each project's native config
  (opencode's config, hermes's `.env`/`cli-config.yaml`, openclaw's `.env`/config, openclaw-os env) — so the
  user edits ONE place and all four agents get the same provider + keys. Read each project's `.env.example`
  / config example to learn the exact variable names; do not guess them.

## DELIVERABLE 3 — testing & debugging harness

- A top-level `aios test all` that runs every suite and prints one summary table.
- A smoke-test flow `aios test smoke` that: boots all services, hits each health endpoint, sends one
  end-to-end request (dashboard → an agent → opencode server → response), asserts success, tears down.
- `aios doctor` as the first thing a user runs when something is broken; must catch the common failures
  (missing key, port in use, wrong runtime version, un-built openclaw dist, un-synced uv env).
- Structured logs per service under `.aios/logs/<service>.log` plus a merged `.aios/logs/aios.log`.

## DELIVERABLE 4 — one-command setup UX + docs

- After `aios setup`, a single `aios start` must bring the whole system up and print the dashboard URL.
- Write `README.aios.md` at the repo root: 60-second quickstart, architecture diagram (reuse the one above),
  the full command reference, a config reference, and a troubleshooting section keyed to `aios doctor` messages.
- Keep it Windows-first (PowerShell examples) with POSIX equivalents noted.

## EXECUTION PLAN (do it in order; each milestone has a verification gate — do not proceed until it passes)

1. **Recon.** Read every project's `package.json` / `pyproject.toml` / README / `.env.example` / existing config. Write `docs/aios/inventory.md` capturing each project's real build cmd, run cmd, test cmd, default port, and required env vars. **Gate:** inventory is complete and every command was copied from a real file, not assumed.
2. **Each project runs solo.** Get each of the five to install, build, and start on its own using its native tooling. Record exact steps. **Gate:** you have personally launched each one and seen it start (or documented the precise blocker + fix).
3. **Scaffold `aios`.** Implement `aios.py` + wrappers with `setup`, `doctor`, `status`, `logs` (no wiring yet). **Gate:** `aios doctor` runs and reports tool availability correctly.
4. **Config plumbing.** Implement `aios.config.yaml` + `.env` + the renderer that writes each project's native config. **Gate:** editing one key in `.env` provably changes all four agents' effective provider config.
5. **Start/stop orchestration.** Implement `start`/`stop`/`status` with health checks and unified logs. **Gate:** `aios start all` brings every enabled service up green; `aios stop all` cleans up with no orphan processes.
6. **Wire the integration.** openclaw-os → openclaw plugin; opencode server reachable by hermes/openclaw; LifeOS skills mounted. **Gate:** `aios test smoke` passes end-to-end.
7. **Testing + docs.** Implement `aios test all`, write `README.aios.md` + troubleshooting. **Gate:** fresh-clone dry run: `aios setup && aios start && aios test smoke` works from zero.

## HARD RULES

- **Never invent a command, env var, port, or file path** — read it from the project first. If unknown, inspect or run `--help`, don't guess.
- **Respect each package manager**: bun (opencode, LifeOS), pnpm (openclaw, openclaw-os), uv (hermes). Don't cross them.
- **Idempotent + non-destructive**: back up before overwriting; never clobber user secrets; safe to re-run `aios setup`.
- **Windows-first**: the user runs PowerShell on Windows 11. Test the Windows path; keep POSIX parity. Don't rely on POSIX-only signals or symlink perms without a Windows fallback (copy instead of symlink if needed).
- **Fail loudly with fixes**: every error message should say what broke and the exact command to fix it.
- **Secrets never logged**; mask them in `debug` output; `.env` is git-ignored.
- **Work incrementally and report** at each gate: what you changed, how you verified it, what's next. Do not mark a milestone done until its gate actually passes when you run it.

## ACCEPTANCE CRITERIA (definition of done)

- From a fresh state: `aios setup` → `aios start` brings up all five, dashboard URL printed and loads.
- `aios doctor` is green; `aios status` shows all services healthy.
- `aios test all` and `aios test smoke` pass.
- Changing the provider/model/key in ONE place (`.env`) reconfigures every agent.
- `README.aios.md` lets someone who has never seen this repo go from zero to running in one command.
