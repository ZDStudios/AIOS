# The AI OS

One control surface — `aios` — that installs, configures, wires, runs, tests, and debugs five
independent agent projects as a single system, from one command and one config.

```
opencode  ·  hermes  ·  openclaw  ·  openclaw-os  ·  LifeOS
```

- **opencode** — the coding-agent engine (headless server on :4096)
- **hermes** — autonomous agent + web dashboard (:9119), memory, cron, learning loop
- **openclaw** — multi-channel messaging gateway (:18789) and plugin host
- **openclaw-os** — the **dashboard / front door**, served inside openclaw at `/plugins/openclawos/`
- **LifeOS** — shared skills/identity mounted into the agents

> "One file" in practice = **one control script** (`aios`) + **one config** (`aios.config.yaml`)
> + **one secrets file** (`.env`). You can't merge three runtimes into a single file; this is the
> faithful version — a single command that makes all five work together.

---

## 60-second quickstart (Windows / PowerShell)

```powershell
cd "C:\Users\Zayn\Desktop\The AI OS"

.\aios.ps1 setup      # install toolchains + deps, create .env, render config, build, wire
#   → the wizard asks for your model provider + API key

.\aios.ps1 start      # bring up all services
.\aios.ps1 url        # print the dashboard URL, then open it in your browser
```

POSIX / macOS / Linux / WSL / Git Bash:

```bash
./aios setup && ./aios start && ./aios url
```

cmd.exe: use `aios setup`, `aios start`, … (the `aios.cmd` shim).

When something is off, run **`aios doctor`** first — it names the problem and the exact fix.

---

## Architecture

```
                        ┌──────────────────────────────────────┐
                        │  openclaw-os  (dashboard / front door) │
                        │  http://127.0.0.1:18789/plugins/openclawos/
                        └───────────────────┬──────────────────┘
                                 served as a plugin inside
                        ┌───────────────────▼──────────────────┐
                        │  openclaw  gateway  :18789            │  channels + plugin host
                        └───────────────────────────────────────┘
        ┌───────────────────────────┐        ┌───────────────────────────┐
        │  hermes  dashboard  :9119 │        │  opencode  server  :4096  │
        │  autonomous + memory+cron │        │  coding engine (HTTP/SDK) │
        └───────────────────────────┘        └───────────────────────────┘
                        ┌───────────────────────────────────────┐
                        │  LifeOS — skills mounted into agents  │
                        └───────────────────────────────────────┘

  Single source of truth:  aios.config.yaml  +  .env   →  rendered into each project's native config
  Single control surface:  ./aios <command>            →  state kept under .aios/
```

**Model config flows one way:** you set the provider + key **once** in `.env`
(`AIOS_LLM_PROVIDER`, `AIOS_LLM_API_KEY`). `aios setup` maps it to each project's own variable
(`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) and injects it at start — so all
four agents share one key. Change it in one place, re-run `aios setup`, done.

**hermes and openclaw overlap** (both are gateways). By design they run as **separate** services
on separate ports, each toggleable in `aios.config.yaml`. Default division of labor:
openclaw = channels + dashboard, hermes = autonomous jobs + memory + cron, opencode = coding engine.

---

## Command reference

| Command | What it does |
|---|---|
| `aios setup` | Install toolchains + deps, run the secrets wizard, render native config, build openclaw + the dashboard, mount LifeOS skills, wire the dashboard plugin. Idempotent. |
| `aios setup --force` | Re-run the secrets wizard (backs up the old `.env`). |
| `aios setup --skip-install` | Fast config-only setup (no dependency install/build). |
| `aios setup --non-interactive` | No prompts; reads `AIOS_*` from the environment. |
| `aios start [svc\|all]` | Start service(s), wait on health checks, keep unified logs. |
| `aios stop [svc\|all]` | Stop service(s); kills the whole process tree (no orphans). |
| `aios status` | Table of each service: running/stopped/foreign, port, pid, health. |
| `aios doctor` | Diagnose tools, projects, config, deps, ports — with exact fixes. Non-zero on failure. |
| `aios test [svc\|all]` | Run each project's real test suite; aggregated summary. |
| `aios test --smoke` | Health-based end-to-end check across running services. |
| `aios debug [svc]` | Dump resolved config, masked secrets, provider mapping, service state, logs. |
| `aios logs [svc] [-n N]` | Tail a service log from `.aios/logs/`. |
| `aios wire` | (Re)install the openclaw-os dashboard plugin into openclaw. |
| `aios update` | Reinstall deps + re-render config + re-mount skills after project updates. |
| `aios url` | Print the dashboard + service URLs. |

Services: `opencode`, `hermes`, `openclaw` (and `hermes-gateway` if enabled). `openclaw-os` runs
as a plugin inside `openclaw`, so it has no separate process.

---

## Configuration

### `.env` (secrets — never committed; `.gitignore`d automatically)

| Key | Meaning |
|---|---|
| `AIOS_LLM_PROVIDER` | `openrouter` \| `anthropic` \| `openai` \| `gemini` |
| `AIOS_LLM_API_KEY` | the key for that provider — powers all four agents |
| `AIOS_DEFAULT_MODEL` | default model id (e.g. `anthropic/claude-opus-4.6`) |
| `OPENCODE_SERVER_PASSWORD` | optional auth for the opencode server |
| `OPENCLAW_GATEWAY_TOKEN` | optional; blank = openclaw auto-generates on start |
| `TELEGRAM_BOT_TOKEN` / `DISCORD_BOT_TOKEN` / `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | channels (optional) |

### `aios.config.yaml` (non-secret wiring)

Toggle services, change ports, set model routing, LifeOS mounting, and health URLs. Uses a small
YAML subset — 2-space indentation, simple `key: value` maps. See `aios.config.example.yaml`.
After editing, run `aios setup` (or `aios update`) to re-render.

State lives under **`.aios/`**: `logs/`, `pids/`, `backups/`, `rendered/`, `openclaw/` (isolated
openclaw state dir), `plugins/openclaw-os/` (staged dashboard plugin), `skills/lifeos/`.

---

## Troubleshooting (keyed to `aios doctor` / logs)

| Symptom | Fix |
|---|---|
| `bun MISSING` | `powershell -c "irm bun.sh/install.ps1 | iex"` then reopen the shell |
| `uv MISSING` | `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` |
| `.env missing` / `no model key` | `aios setup` (or `aios setup --force`) and enter your key |
| `<svc> not healthy within Ns` | `aios logs <svc>` — the tail shows the real error |
| opencode: `node-gyp` / `tree-sitter-powershell` fails | expected on Windows; aios installs opencode with `--ignore-scripts` (the server doesn't need those native modules) |
| openclaw: `missing dist/entry.(m)js` | openclaw needs a build; `aios setup` runs it. Needs ~12 GB free RAM (heap auto-sized). |
| openclaw build: `JS heap out of memory` | low RAM — close apps, or set `NODE_OPTIONS=--max-old-space-size=<MB>` and rerun `pnpm build` in the openclaw root |
| openclaw: `Invalid config … additional properties` | aios uses an **isolated** state dir (`.aios/openclaw`); your own `~/.openclaw` is never touched |
| openclaw: `Missing config … gateway.mode=local` | aios writes `.aios/openclaw/openclaw.json` with `gateway.mode=local` during render |
| plugin install: `code safety scan failed … node_modules symlink` | aios installs the dashboard from a **staged copy** without `node_modules` (`.aios/plugins/openclaw-os`) |
| port `:PORT` in use by a **foreign** process | free it, or change the port in `aios.config.yaml` |
| `pnpm run build` fails on `'rm' is not recognized` | Windows shell has no `rm`; aios calls esbuild directly instead of the plugin's script |

---

## What runs natively vs. what's skipped on Windows

- opencode is installed with `--ignore-scripts` — the **server** (what aios runs) works without the
  native TUI/LSP modules. If you want the full opencode TUI/desktop, install VS Build Tools and run
  `bun install` in `opencode-dev/opencode-dev` yourself.
- openclaw's optional `@matrix-org/matrix-sdk-crypto` native postinstall is skipped (needs a specific
  Node under a version manager). The core gateway, dashboard, and other channels work.

---

## Requirements

- **Windows 11** (primary) or macOS/Linux/WSL. Python 3.9+ (for `aios` itself — zero extra deps).
- Toolchains (auto-installed by `aios setup` where possible): **bun**, **pnpm**, **uv**, **Node ≥20**, **git**.
- ~12 GB free RAM for the one-time openclaw build; a few GB of disk for all dependencies.
