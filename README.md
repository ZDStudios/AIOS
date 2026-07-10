<div align="center">

# 🧠 The AI OS

### Five open-source AI agents. One operating system. One Control Room.

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-8B5CF6?style=for-the-badge" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/Windows-first-0A84FF?style=for-the-badge&logo=windows&logoColor=white" alt="Windows first">
  <img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Node-%E2%89%A520-339933?style=for-the-badge&logo=nodedotjs&logoColor=white" alt="Node">
  <img src="https://img.shields.io/badge/Bun-1.3-000000?style=for-the-badge&logo=bun&logoColor=white" alt="Bun">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/opencode-coding_engine-EC4899?style=flat-square" alt="opencode">
  <img src="https://img.shields.io/badge/hermes-autonomous_agent-F59E0B?style=flat-square" alt="hermes">
  <img src="https://img.shields.io/badge/openclaw-channel_gateway-EF4444?style=flat-square" alt="openclaw">
  <img src="https://img.shields.io/badge/CrewAI-multi--agent_crews-06B6D4?style=flat-square" alt="CrewAI">
  <img src="https://img.shields.io/badge/LifeOS-shared_skills-8B5CF6?style=flat-square" alt="LifeOS">
  <img src="https://img.shields.io/badge/+_openclaw--os-dashboard-64748B?style=flat-square" alt="openclaw-os">
  <img src="https://img.shields.io/badge/+_OpenUI-generative_UI-10B981?style=flat-square" alt="OpenUI">
</p>

**[Install](#-install-one-line)** · **[Control Room](#-the-control-room)** · **[Architecture](#️-architecture)** · **[Commands](#️-command-reference)** · **[Full docs](README.aios.md)** · **[Website](https://zdstudios.github.io/AIOS/)**

</div>

---

**The AI OS** takes five independent open-source AI agents and makes them work as **one auto-configured
system** you drive from a single command — **`aios`** — and a single web **Control Room** where you can
**talk to everything and have the agents talk to each other**.

One control script. One config. One `.env`. `aios setup` installs every toolchain, wires the projects
together, mounts your shared skills, and adds **OpenUI** generative-UI context to every agent.
`aios start` brings the whole stack up behind the **Control Room** dashboard.

> You can't fuse three runtimes and multiple package managers into a single file — that would just break
> everything. So "one file" here means **one control surface** (`aios`) + **one dashboard** (the Hub) over
> five real, unmodified projects. It installs, configures, wires, runs, tests, and debugs all of them.

<div align="center">

```
aios setup   →   aios start   →   aios url        (opens the Control Room)
```

</div>

## ⚡ Install (one line)

**Linux / macOS / WSL:**

```bash
curl -fsSL https://raw.githubusercontent.com/ZDStudios/AIOS/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/ZDStudios/AIOS/main/install.ps1 | iex
```

The installer clones the repo to `~/AIOS`, installs the toolchains (**uv, bun, pnpm, Node**), and runs
`aios setup` — installing every agent's deps, building, and wiring the Control Room. Then add your key:

```bash
cd ~/AIOS
./aios install-cli       # so `aios` runs from anywhere (no ./)
aios setup --force       # enter your model provider + API key (or skip)
aios start               # bring the whole stack up
aios url                 # open the Control Room
```

> `aios install-cli` adds `aios` to your PATH (`~/.local/bin`), so after that you can run
> `aios update`, `aios start`, etc. from any directory. `aios setup` also offers to do this.

## 💬 The Control Room

`aios start` launches the **AIOS Hub** — a single web dashboard at **`http://127.0.0.1:8787/`** where you can:

- **Talk to everything** — chat with the **Brain** (orchestrator), **CrewAI** (multi-agent crews),
  **opencode** (coding), or **broadcast to all** at once.
- **See everything live** — real-time health of every service.
- **Use every agent's UI** — the hermes and openclaw-os dashboards are embedded as tabs.
- **Let agents reach each other** — the Hub is the interconnect bus; each agent is given every other
  agent's endpoint, and CrewAI ships an `ask_peer` tool to call them.
- **Render generative UI (OpenUI) in the hub** — any agent can emit a ```ui``` block (self-contained HTML) that the hub renders **live and interactive** in chat (sandboxed, theme-aware). openclaw-os also renders OpenUI Lang natively.
- **Shared Canvas any agent can edit** — agents `POST /api/ui` (CrewAI has a `build_dashboard_ui` tool) to pin widgets to a **Canvas** everyone sees. This is how "all agents edit the dashboard."

## 🧩 The five agents

| Agent | Role in The AI OS | Port | Upstream |
|---|---|---|---|
| **opencode** | Coding-agent engine (headless server + SDK) | `4096` | [opencode.ai](https://opencode.ai) |
| **hermes** | Autonomous agent — memory, cron, learning loop, dashboard | `9119` | [Nous Research](https://github.com/NousResearch/hermes-agent) |
| **openclaw** | Multi-channel messaging gateway + plugin host | `18789` | [openclaw.ai](https://github.com/openclaw/openclaw) |
| **CrewAI** | Multi-agent orchestration — role-based crews | `4788` | [crewaiinc/crewai](https://github.com/crewaiinc/crewai) |
| **claude-code** | Claude Code as an OpenAI-compatible API | `8000` | [codingworkflow/claude-code-api](https://github.com/codingworkflow/claude-code-api) |
| **LifeOS** | Shared identity + skills mounted into the agents | — | [danielmiessler/LifeOS](https://github.com/danielmiessler/LifeOS) |

Plus two integrations that glue it together:

| | Role | Upstream |
|---|---|---|
| **AIOS Hub** | The Control Room — unified dashboard + interconnect (`:8787`) | *(this repo)* |
| **openclaw-os** | openclaw's generative-UI **dashboard** (a plugin, not an agent) | [thesys](https://github.com/thesysdev/openclaw-os) |
| **OpenUI** | Generative-UI standard, mounted into every agent | [openui.com](https://www.openui.com) |

## 🗺️ Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │   💬  AIOS Hub — the Control Room  :8787      │  talk to everything
                    │   chat · broadcast · live status · interconnect
                    └───────┬───────────┬───────────┬──────────┬────┘
              ┌─────────────┘     ┌─────┘       ┌───┘      ┌───┘
     ┌────────▼───────┐  ┌────────▼──────┐  ┌───▼──────┐  ┌▼──────────────┐
     │ opencode :4096 │  │ hermes  :9119 │  │ openclaw │  │ CrewAI  :4788 │
     │ coding engine  │  │ autonomous    │  │  :18789  │  │ multi-agent   │
     └────────────────┘  └───────────────┘  └────┬─────┘  └───────────────┘
            every agent gets every other's URL   │  hosts
            (agents call each other via the Hub) │
                                        ┌─────────▼──────────┐
                                        │ openclaw-os (OpenUI) │  dashboard
                                        └──────────────────────┘
     ┌──────────────────────────────────────────────────────────────────┐
     │ LifeOS skills + OpenUI context — mounted into every agent          │
     └──────────────────────────────────────────────────────────────────┘

  Single source of truth:  aios.config.yaml  +  .env   →  rendered into each project's config
  Single control surface:  ./aios <command>            →  state kept under .aios/
```

## ✨ What you get

| | |
|---|---|
| **One Control Room** | Talk to every agent — or all at once — from one dashboard, and watch them talk to each other. |
| **One command to rule them all** | `aios setup` installs bun / pnpm / uv / Node, every agent's deps, builds what needs building, and wires it together. Idempotent. |
| **One key, every agent** | Set your provider + API key once in `.env`; `aios` maps it into all five. |
| **Agents that reach each other** | The Hub is a shared bus; each agent knows every peer's endpoint. CrewAI ships an `ask_peer` tool. |
| **Generative UI everywhere** | OpenUI context is mounted into every agent; openclaw-os renders the results as live apps. |
| **Doctor + smoke tests** | `aios doctor` prints the exact fix for any problem; `aios test --smoke` drives the whole stack. |
| **Windows-first, cross-platform** | Built and verified on Windows 11 (PowerShell), with POSIX / macOS / Linux / WSL parity. |

## 🎛️ Command reference

| Command | What it does |
|---|---|
| `aios setup` | Guided install: toolchains + deps, key wizard (or `--skip-keys`), render, build, mount, wire. Offers autostart + "start now". |
| `aios setup --skip-keys` | Skip the API-key wizard entirely — the stack still runs; add keys later in the hub **Settings** panel. |
| `aios start [svc…\|all]` | Start service(s) (`opencode hermes openclaw crewai hub`), wait on health checks. Accepts multiple names. |
| `aios stop [svc…\|all]` | Stop service(s); kills the whole process tree — no orphans. |
| `aios restart [svc…\|all]` | Force a clean respawn (picks up new code after an update). `aios update` does this automatically. |
| `aios status` | Table of each service: state, port, PID, health. |
| `aios doctor` | Diagnose tools, config, deps and ports — with the exact fix for each. |
| `aios update [--check]` | `git pull` + reinstall changed deps + re-render. `--check` just reports if updates exist (also auto-checked on start). |
| `aios autostart enable\|disable` | Run The AI OS on login/boot (Startup shortcut on Windows, systemd/`.bashrc` on Linux/WSL). |
| `aios test --smoke` | Run test suites, or drive the whole stack end-to-end. |
| `aios logs [svc]` | Tail a service log from `.aios/logs/`. |
| `aios url` | Print the Control Room + service URLs. |

**In the Control Room** (`http://127.0.0.1:8787/`) you can:
- **Chat** with any agent (Brain, CrewAI, opencode, claude-code) or broadcast to **All**.
- **✦ Team** — one assistant that orchestrates the whole team: the Brain plans, delegates subtasks to the specialist agents, and synthesizes one answer (the practical "merge").
- **Configure openclaw AND hermes fully inside the hub** — both control-UIs are embedded via frame-stripping proxies, so you get channels, **connectors**, model providers, **MCP servers**, skills, plugins, **automations/cron**, and sessions right in the hub (they normally block embedding).
- **Automations** — schedule prompts to run against any agent every N minutes (daily digests, checks).
- **Connect your Claude account (Pro/Max)** — first run `aios claude-login` (opens the browser OAuth for your subscription), then one click in **Settings → "Use my Claude subscription"** routes the Brain/Team/crews through **claude-code** (no API key, no per-token cost). The button tests a real completion and tells you if you still need to log in.
- **Settings** — edit provider/key/model, channel tokens, and `aios.config.yaml`; it re-renders into every agent, no terminal needed.
- **Themes** — Light, Dark, Midnight, Slate, Rose. Chat renders markdown (headers, bullets, code blocks).

**Auto-updates:** `aios start` now auto-runs `git pull` + reinstalls changed deps when the repo has updates (`updates.auto_update: true`). Turn it off in `aios.config.yaml`.

## ✨ 10 things no single-agent tool can do

Because The AI OS runs **six agents wired through one hub**, it can do multi-agent things nothing else can:

1. **🎯 Auto-router** — the hub reads your message and *automatically picks the best agent* (code → opencode, research → CrewAI…), and tells you which it chose.
2. **⚖️ Agent Arena** — send one prompt to **two agents side-by-side** and compare their answers.
3. **🏛️ Council** — ask several agents, then a chair agent **synthesizes a consensus** and flags where they disagree.
4. **⛓ Pipelines** — **chain agents**: research (CrewAI) → build (opencode) → summarize (Brain), each step feeding the next.
5. **🧠 Shared memory** — facts you save are injected into **every** agent's context, so they all know you.
6. **📚 Prompt library + slash commands** — save prompts, type `/name` in chat to expand them.
7. **🎙️ Voice in/out** — talk to the hub and have replies read aloud (browser-native, no cloud).
8. **⌘K command palette** — jump anywhere or ask any agent instantly.
9. **📊 Usage + subscription-savings meter** — counts requests per agent and shows how many ran **free on your Claude subscription**.
10. **⬇️ Export & saved conversations** — full conversation history (pinned/today/earlier), export any chat to Markdown.

**AIOS API (OpenAI-compatible):** the hub is itself an API you can POST to. Point any OpenAI client/SDK at `http://<host>:8787/v1`. The "models" are the agents/targets: `brain`, `team`, `opencode`, `crewai`, `claudecode`, `all`.

```bash
curl http://127.0.0.1:8787/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"team","messages":[{"role":"user","content":"build a todo app and research frameworks"}]}'

curl http://127.0.0.1:8787/v1/models         # list targets
# or the simple form:  POST /api/chat {"target":"brain","message":"hi"}
```

**Model picker:** in **Settings**, click **↻ fetch my models** to pull the live model list from your provider (e.g. all your Claude models) and pick one.

**Chat is now a 3-column workspace** — conversation history (pinned / today / earlier) · transcript · live agent panel — with saved conversations.

**`/dry` cost estimator:** type `/dry <your message>` in chat to estimate the **tokens and cost** before running — using live per-model pricing (and $0 when on your Claude subscription). Multi-agent modes (Arena/Council/Pipeline) account for the extra calls.

**Refined theming + theme store:** the default is a warm, classical **Hermes** theme (charcoal + gold, serif headings) — plus **OpenClaw** (coral), **Olympus** (light), **Obsidian**, **Forest**, and **Rose**. **Settings → Theme store** lets you preview and apply any theme, or **install your own** by pasting a JSON of CSS variables.

**Skills & system prompt:** 10 skills ship built-in (skill-maker, mcp-maker, web-search, web-browse, image-gen, code-review, summarize, research, data-analyst, task-scheduler) and mount into every agent. Edit the Brain/Team **system prompt** live in the hub → **Settings**.

**On WSL?** `127.0.0.1:8787` often won't reach WSL from your Windows browser (localhost-forwarding is flaky). `aios start`/`aios url` now print your **WSL IP** URL — use that (e.g. `http://172.31.x.x:8787/`). The hub binds `0.0.0.0` so the WSL IP always works.

## ⚙️ Configuration

- **`.env`** — secrets only (`AIOS_LLM_PROVIDER`, `AIOS_LLM_API_KEY`, `AIOS_DEFAULT_MODEL`, optional channel tokens). Git-ignored.
- **`aios.config.yaml`** — non-secret wiring (enabled services, ports incl. `crewai: 4788` and `hub: 8787`, model routing, OpenUI/LifeOS mounting, health URLs). Copy from `aios.config.example.yaml`.

Edit one key in `.env`, run `aios setup`, and every agent — and the Hub, and CrewAI — is reconfigured.
Full reference in **[README.aios.md](README.aios.md)**.

## 🙏 Built on

The AI OS is an integration layer. All the heavy lifting is done by these open-source projects — go star them:

- **[opencode](https://opencode.ai)** — the open-source AI coding agent
- **[hermes-agent](https://github.com/NousResearch/hermes-agent)** by Nous Research — the self-improving agent
- **[openclaw](https://github.com/openclaw/openclaw)** — the personal AI assistant gateway
- **[CrewAI](https://github.com/crewaiinc/crewai)** — framework for orchestrating role-playing, autonomous AI agents
- **[LifeOS](https://github.com/danielmiessler/LifeOS)** by Daniel Miessler — the AI-powered life OS
- **[openclaw-os](https://github.com/thesysdev/openclaw-os)** by thesys — the generative-UI dashboard
- **[OpenUI](https://www.openui.com)** — the open standard for LLM-generated interfaces

Each project keeps its own license (all MIT / open source); their `LICENSE` files ship unmodified.

## 📄 License

The `aios` orchestrator, Hub, and docs are released under the **MIT License**. Bundled projects retain
their own licenses. See [`LICENSE`](LICENSE).

<div align="center">
<sub>Built with <a href="https://claude.com/claude-code">Claude Code</a> · The AI OS</sub>
</div>
