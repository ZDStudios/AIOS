# AI OS — Project Inventory (Milestone 1)

Every command below was copied from a real file in each project (package.json / pyproject.toml /
.env.example / README / source), not assumed. Sources are cited per row.

Real project roots are double-nested (`X-main/X-main`). `aios` resolves them dynamically.

---

## 1. opencode — coding-agent engine

| Field | Value | Source |
|---|---|---|
| Root | `opencode-dev/opencode-dev` | fs |
| Runtime / PM | Bun `1.3.14` | `package.json` `packageManager` |
| Install | `bun install` (has `postinstall: fix-node-pty`) | `package.json` scripts |
| Run (CLI/TUI) | `bun run dev` → `bun run --cwd packages/opencode --conditions=browser src/index.ts` | `package.json` scripts.dev |
| **Serve (headless server)** | `bun run --cwd packages/opencode src/index.ts serve [--port 4096] [--hostname 127.0.0.1]` | `cli/cmd/serve.ts`, `index.ts:93` |
| Default port | **4096** (then any free port) | `server/server.ts:120`, `plugin/index.ts:143` |
| Test | per-package `bun test` (root `test` errors on purpose) | `package.json` scripts.test |
| Typecheck | `bun turbo typecheck` | `package.json` |
| Provider env | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` (opencode config/providers) | opencode providers |
| Server auth | optional `OPENCODE_SERVER_PASSWORD` (warns if unset) | `cli/cmd/serve.ts:15` |
| Base URL | `http://localhost:4096` | `plugin/index.ts:143` |

## 2. hermes-agent — autonomous background operator

| Field | Value | Source |
|---|---|---|
| Root | `hermes-agent-main/hermes-agent-main` | fs |
| Runtime / PM | Python `>=3.11,<3.14` via **uv** | `pyproject.toml` |
| Install | `uv sync` | pyproject / README |
| Entry point | `hermes` = `hermes_cli.main:main` (run: `uv run hermes …`) | `pyproject.toml:308` |
| Run gateway | `uv run hermes gateway run` | `docker-compose.yml` command |
| Run dashboard | `uv run hermes dashboard --host 127.0.0.1 --no-open` | `docker-compose.yml` command |
| Default port | **9119** (dashboard) | `docker-compose.yml` tunnel comment |
| TUI | `uv run hermes` | README |
| Setup wizard | `uv run hermes setup` / `uv run hermes model` | `cli-config.yaml.example` |
| Test | `uv run pytest` | pyproject (pytest) |
| Config files | `~/.hermes/config.yaml` (`model.default`), repo `.env`, `cli-config.yaml` | `.env.example`, `cli-config.yaml.example` |
| Provider env | `OPENROUTER_API_KEY` (default routing) + many optional providers | `.env.example` |
| Default model | `anthropic/claude-opus-4.6` | `cli-config.yaml.example` |

## 3. openclaw — messaging/channel gateway + plugin host

| Field | Value | Source |
|---|---|---|
| Root | `openclaw-main/openclaw-main` | fs |
| Runtime / PM | Node + **pnpm** workspace | `pnpm-workspace.yaml` |
| Install | `pnpm install` | fs / CONTRIBUTING |
| Build | `pnpm build` → `node scripts/build-all.mjs` | `package.json` scripts.build |
| Bin / entry | `openclaw` → `openclaw.mjs` | `package.json` bin |
| Run gateway | `node openclaw.mjs gateway` (a.k.a. `openclaw gateway`) | bin + README |
| Default port | **18789** (gateway) | openclaw-os README |
| Plugin install (local) | `openclaw plugins install -l <path>` | openclaw-os CONTRIBUTING |
| Dashboard URL | `openclaw os url` → `http://localhost:18789/plugins/openclawos` | openclaw-os README |
| Test | `pnpm -r test` | pnpm workspace |
| Config files | `~/.openclaw/openclaw.json`, repo `.env` or `~/.openclaw/.env` | `.env.example` |
| Gateway auth | `OPENCLAW_GATEWAY_TOKEN` (auto-generated on first start) | `.env.example:22` |
| State dir | `~/.openclaw` (`OPENCLAW_STATE_DIR`) | `.env.example:28` |
| Provider env | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` | `.env.example:48-51` |
| Channel env | `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | `.env.example:74-77` |

## 4. openclaw-os — dashboard (front door), an openclaw plugin

| Field | Value | Source |
|---|---|---|
| Root | `openclaw-os-main/openclaw-os-main` | fs |
| Runtime / PM | Node `>=20` + **pnpm** (`claw-client`, `claw-plugin`) | `package.json` engines |
| Install | `pnpm install` (links both packages) | CONTRIBUTING |
| Build | `pnpm -r build` (or `pnpm build`) | `package.json` scripts |
| Client dev (standalone) | `pnpm dev` → `http://localhost:18790` | CONTRIBUTING |
| **Integration path** | `openclaw plugins install -l ./packages/claw-plugin` (raw TS via jiti, no build) → served at `http://localhost:18789/plugins/openclawos` | CONTRIBUTING |
| Pre-auth URL | `openclaw os url` | README |
| Test | `pnpm -r test` (vitest `--passWithNoTests`) | claw-plugin `package.json` |
| CI (lint+fmt+types+build) | `pnpm ci` | `package.json` scripts.ci |
| Plugin package name | `@openuidev/openclaw-os-plugin` | claw-plugin `package.json` |

## 5. LifeOS — shared identity/context + skills layer

| Field | Value | Source |
|---|---|---|
| Root | `LifeOS-main/LifeOS-main` | fs |
| Runtime / PM | TypeScript via **bun** (tools are `.ts`) | `LifeOS/INSTALL.md` §1 |
| Install (AI-native, additive) | `bun Tools/DetectEnv.ts` → `ScanConflicts.ts` → `DeployCore.ts` → `ScaffoldUser.ts` → `LinkUser.ts` | `INSTALL.md` §2–5 |
| Server / port | **none** — it's a skills/context harness, not a service | INSTALL.md |
| Skill assets | `LifeOS/install/skills`, `LifeOS/install/LIFEOS`, `LifeOS/install/USER`, `SKILL.md` | fs |
| Role in aios | shared skills/context **mounted** into openclaw + hermes skill dirs | architecture |

---

## Consolidated wiring (what aios orchestrates)

| Service | Port | Health target | Start command (from root) |
|---|---|---|---|
| opencode (server) | 4096 | `GET http://127.0.0.1:4096/` | `bun run --cwd packages/opencode src/index.ts serve --port 4096 --hostname 127.0.0.1` |
| hermes (dashboard) | 9119 | `GET http://127.0.0.1:9119/` | `uv run hermes dashboard --host 127.0.0.1 --no-open` |
| hermes (gateway, optional) | n/a | process alive | `uv run hermes gateway run` |
| openclaw (gateway) | 18789 | `GET http://127.0.0.1:18789/` | `node openclaw.mjs gateway` |
| openclaw-os (dashboard/front door) | 18789 (via openclaw) | `GET http://127.0.0.1:18789/plugins/openclawos` | plugin installed into openclaw gateway |

**Front door** = openclaw gateway `:18789` with the openclaw-os plugin → `openclaw os url`.
**Shared model config** propagated to every agent from one `.env` (all four accept `OPENROUTER_API_KEY`
and/or `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`). LifeOS skills are copied/linked into openclaw + hermes.

### Overlap note (per prompt: run both, don't merge)
hermes and openclaw are both multi-channel gateways. They stay separate services on separate ports
(9119 vs 18789), each toggleable in `aios.config.yaml`. Default division of labor: **openclaw = channels +
dashboard**, **hermes = autonomous jobs + memory + cron**. opencode = coding engine both can call at :4096.

---

## 6. CrewAI — multi-agent orchestration (5th agent)

| Field | Value | Source |
|---|---|---|
| Root | `crewAI-main/crewAI-main` (uv workspace `crewai-workspace`) | fs |
| Runtime / PM | Python `>=3.10,<3.14` via **uv** | `pyproject.toml` |
| Package | `crewai` (`lib/crewai`), CLI `crewai_cli.cli:crewai` | `lib/*/pyproject.toml` |
| Install | `uv sync --package crewai` (avoids heavy optional extras) | aios |
| Runs as | `services/crewai_service.py` via `uv run --project crewAI-main/crewAI-main python …` | aios |
| Port | **4788** (`/chat`, `/health`) | aios |
| Interconnect | `ask_peer` tool → hub `POST /api/relay` to reach opencode/hermes/brain | `services/crewai_service.py` |
| Model | litellm string from `AIOS_DEFAULT_MODEL` + provider (e.g. `openrouter/…`) | service |

## 7. AIOS Hub — the Control Room + interconnect

| Field | Value | Source |
|---|---|---|
| File | `aios_hub.py` (Python stdlib, `http.server`) | this repo |
| Port | **8787** | aios |
| Serves | `docs/dashboard.html` at `/`; `GET /api/services`, `/api/peers`, `/health`; `POST /api/chat`, `/api/relay` | `aios_hub.py` |
| Chat targets | `brain` (direct LLM), `crewai` (service), `opencode` (`opencode run` CLI), `all` (broadcast) | `aios_hub.py` |
| Interconnect | every service gets `AIOS_*_URL` env; `/api/relay` routes agent→agent | `aios.py interconnect_env` |

## Updated wiring

| Service | Port | Health | Notes |
|---|---|---|---|
| opencode | 4096 | `/` | coding engine |
| hermes | 9119 | `/` | autonomous + dashboard |
| openclaw | 18789 | `/` | channels; hosts openclaw-os plugin |
| crewai | 4788 | `/health` | multi-agent crews |
| **hub** | **8787** | `/health` | **Control Room — front door** |
| openclaw-os | 18789/plugins/openclawos/ | — | openclaw's dashboard (embedded in the hub) |

**Front door is now the AIOS Hub (`:8787`).** openclaw-os is openclaw's dashboard (a plugin), embedded
as a tab in the Control Room — not a standalone agent. OpenUI context is mounted into every agent.
