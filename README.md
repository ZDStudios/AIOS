<div align="center">

# 🧠 The AI OS

### Five open-source AI agents. One operating system.

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
  <img src="https://img.shields.io/badge/openclaw--os-dashboard-06B6D4?style=flat-square" alt="openclaw-os">
  <img src="https://img.shields.io/badge/LifeOS-shared_skills-8B5CF6?style=flat-square" alt="LifeOS">
</p>

**[Quickstart](#-60-second-quickstart)** · **[Architecture](#️-architecture)** · **[Commands](#️-command-reference)** · **[Full docs](README.aios.md)** · **[Website](docs/index.html)**

</div>

---

**The AI OS** takes five independent open-source agent projects and makes them work as **one auto-configured system** you drive from a single command: **`aios`**.

One control script. One config file. One `.env`. `aios setup` installs every toolchain, wires the projects together, and mounts your shared skills. `aios start` brings the whole stack up — with an interactive dashboard as the **front door**.

> You can't fuse three runtimes and five package managers into a single file — that would just break everything. So "one file" here means **one control surface** (`aios`) over five real, unmodified projects, not a Frankenstein merge. It installs, configures, wires, runs, tests, and debugs all of them.

<div align="center">

```
aios setup   →   aios start   →   aios url
```

</div>

## ✨ What you get

| | |
|---|---|
| **One command to rule them all** | `aios setup` installs bun / pnpm / uv / Node, installs every project's deps, builds what needs building, and wires it all together. Idempotent and safe to re-run. |
| **One key, every agent** | Set your model provider + API key **once** in `.env`. `aios` maps it into each project's own config, so all four agents share one key. Change it in one place. |
| **A dashboard as the front door** | The **openclaw-os** generative-UI workspace is served inside the gateway — sessions, live apps, charts, and forms in one pane of glass. |
| **Health-checked orchestration** | `aios start` waits until every service is actually up. `aios status` shows ports, PIDs, and health. `aios stop` kills the whole tree — no orphans. |
| **Doctor that tells you the fix** | `aios doctor` diagnoses toolchains, config, deps, and port conflicts — and prints the exact command to fix each one. |
| **Unified testing & debugging** | `aios test` runs every project's real suite. `aios test --smoke` drives the whole stack end-to-end. `aios debug` dumps resolved config with secrets masked. |
| **Windows-first, cross-platform** | Built and verified on Windows 11 (PowerShell), with POSIX / macOS / Linux / WSL parity. |
| **Nothing hidden** | Zero-dependency Python control script. Every project stays intact and upgradable. Your secrets never leave `.env`. |

## 🧩 The five projects

| Project | Role in The AI OS | Port | Upstream |
|---|---|---|---|
| **opencode** | Coding-agent engine (headless server + SDK) | `4096` | [opencode.ai](https://opencode.ai) |
| **hermes** | Autonomous agent — memory, cron, learning loop, dashboard | `9119` | [Nous Research](https://github.com/NousResearch/hermes-agent) |
| **openclaw** | Multi-channel messaging gateway + plugin host | `18789` | [openclaw.ai](https://github.com/openclaw/openclaw) |
| **openclaw-os** | The dashboard / front door (served inside openclaw) | `18789/plugins/openclawos/` | [thesys](https://github.com/thesysdev/openclaw-os) |
| **LifeOS** | Shared identity + skills mounted into the agents | — | [danielmiessler/LifeOS](https://github.com/danielmiessler/LifeOS) |

## ⚡ Install (one line)

**Linux / macOS / WSL:**

```bash
curl -fsSL https://raw.githubusercontent.com/ZDStudios/AIOS/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/ZDStudios/AIOS/main/install.ps1 | iex
```

The installer clones the repo to `~/AIOS`, installs the toolchains (**uv, bun, pnpm, Node**),
and runs `aios setup` — installing every project's deps, building, and wiring the dashboard.
Then finish setup with your key:

```bash
cd ~/AIOS
./aios setup --force     # enter your model provider + API key
./aios start             # bring the whole stack up
./aios url               # open the dashboard
```

> Override the target dir with `AIOS_DIR=/path`. Set `AIOS_NO_SETUP=1` to clone only.

## 🚀 Already have the folder?

If you already downloaded The AI OS, skip the installer and run it directly:

```powershell
# Windows (PowerShell)
.\aios.ps1 setup      # install toolchains + deps, create .env, render config, build, wire
.\aios.ps1 start      # bring up all services
.\aios.ps1 url        # print + open the dashboard URL
```

```bash
# macOS / Linux / WSL / Git Bash
./aios setup && ./aios start && ./aios url
```

Something off? Run **`aios doctor`** first — it names the problem and the exact fix.

## 🗺️ Architecture

```
                        ┌────────────────────────────────────────┐
                        │  openclaw-os  ·  dashboard / front door  │
                        │  http://127.0.0.1:18789/plugins/openclawos/
                        └────────────────────┬───────────────────┘
                                 served as a plugin inside
                        ┌────────────────────▼───────────────────┐
                        │  openclaw  gateway  :18789              │  channels + plugin host
                        └─────────────────────────────────────────┘
        ┌────────────────────────────┐         ┌────────────────────────────┐
        │  hermes  dashboard  :9119  │         │  opencode  server  :4096   │
        │  autonomous · memory · cron│         │  coding engine · HTTP/SDK  │
        └────────────────────────────┘         └────────────────────────────┘
                        ┌─────────────────────────────────────────┐
                        │  LifeOS — shared skills mounted in agents │
                        └─────────────────────────────────────────┘

  Single source of truth:  aios.config.yaml  +  .env   →  rendered into each project's config
  Single control surface:  ./aios <command>            →  state kept under .aios/
```

**hermes and openclaw** both do "gateway" work, so by design they run as **separate, toggleable**
services (9119 vs 18789) instead of being merged. Default split: openclaw = channels + dashboard,
hermes = autonomous jobs + memory + cron, opencode = the coding engine both can call.

## 🎛️ Command reference

| Command | What it does |
|---|---|
| `aios setup` | Install toolchains + deps, run the secrets wizard, render config, build, mount skills, wire the dashboard. Idempotent. |
| `aios start [svc\|all]` | Start service(s), wait on health checks, keep unified logs. |
| `aios stop [svc\|all]` | Stop service(s); kills the whole process tree (no orphans). |
| `aios status` | Table of each service: state, port, PID, health. |
| `aios doctor` | Diagnose tools, config, deps, ports — with exact fixes. |
| `aios test [svc\|all]` | Run each project's real test suite; aggregated summary. |
| `aios test --smoke` | Health-based end-to-end check across the stack. |
| `aios debug [svc]` | Dump resolved config, masked secrets, service state, logs. |
| `aios logs [svc] -n N` | Tail a service log from `.aios/logs/`. |
| `aios wire` | (Re)install the openclaw-os dashboard plugin into openclaw. |
| `aios update` | Reinstall deps + re-render config after project updates. |
| `aios url` | Print the dashboard + service URLs. |

## ⚙️ Configuration

- **`.env`** — secrets only (`AIOS_LLM_PROVIDER`, `AIOS_LLM_API_KEY`, `AIOS_DEFAULT_MODEL`, optional channel tokens). Git-ignored automatically.
- **`aios.config.yaml`** — non-secret wiring (enabled services, ports, model routing, health URLs). Copy from `aios.config.example.yaml`.

Edit one key in `.env`, run `aios setup`, and every agent is reconfigured. Full reference in **[README.aios.md](README.aios.md)**.

## 🙏 Built on

The AI OS is an integration layer. All the heavy lifting is done by these excellent open-source
projects — go star them:

- **[opencode](https://opencode.ai)** — the open-source AI coding agent
- **[hermes-agent](https://github.com/NousResearch/hermes-agent)** by Nous Research — the self-improving agent
- **[openclaw](https://github.com/openclaw/openclaw)** — the personal AI assistant gateway
- **[openclaw-os](https://github.com/thesysdev/openclaw-os)** by thesys — the generative-UI workspace
- **[LifeOS](https://github.com/danielmiessler/LifeOS)** by Daniel Miessler — the AI-powered life OS

Each project keeps its own license (all MIT / open source); their `LICENSE` files ship unmodified.

## 📄 License

The `aios` orchestrator and docs are released under the **MIT License**. Bundled projects retain
their own licenses. See [`LICENSE`](LICENSE).

<div align="center">
<sub>Built with <a href="https://claude.com/claude-code">Claude Code</a> · The AI OS</sub>
</div>
