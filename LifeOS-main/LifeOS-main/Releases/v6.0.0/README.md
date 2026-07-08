<div align="center">

<img src="https://raw.githubusercontent.com/danielmiessler/LifeOS/main/images/lifeos-logo.png" alt="LifeOS" width="200">

# LifeOS 6.0.0

**One skill, one install.**

[![Skills](https://img.shields.io/badge/Skills-49-22C55E?style=flat)](../../LifeOS/install/skills/)
[![Algorithm](https://img.shields.io/badge/Algorithm-v6.23.0-D97706?style=flat)](../../LifeOS/install/LifeOS/ALGORITHM/)
[![Pulse](https://img.shields.io/badge/Pulse-included-3B82F6?style=flat)](../../LifeOS/install/LifeOS/PULSE/)

</div>

---

LifeOS 6.0.0 is the first release under the LifeOS name — the project was **PAI (Personal AI Infrastructure)** — and the release where the whole system becomes a single self-contained skill you install by handing it to your AI.

## What's new

### Skill-based distribution

This is the headline change. In v5 and earlier, a release was a complete `.claude/` directory: you cloned the repo, copied the folder into your home directory, and ran a wizard. In 6.0.0 the entire system ships as **one self-contained skill** (`LifeOS/`). That single directory carries the orchestrator (`SKILL.md`, workflows, tools) plus a full install payload: the system prompt, the Algorithm, 49 skills, hooks, agents, Pulse, the statusline, and the USER + MEMORY scaffolds. One directory, one install, nothing loose scattered across your config.

### Give it to your AI

The primary install method is now conversational. Paste the one-liner into Claude Code (or any AI coding harness) and say **"install this."** Your AI pulls the skill from GitHub, drops it into your harness, and runs the setup interview with your permission. No manual directory copying, no hunting for hidden folders.

### First release under the LifeOS name

Same system, new name. PAI becomes **LifeOS — the Life Operating System**. Everything you had is still here; this is the next version of it.

## What's different from v5

|  | v5.0.0 | v6.0.0 |
|---|---|---|
| **Distribution** | Full `.claude/` directory clone | One self-contained skill (`LifeOS/`) |
| **Install** | Copy the directory, run the wizard | Give it to your AI ("install this") |
| **Name** | Early Life Operating System (PAI) | LifeOS |
| **Algorithm** | v6.3.0 | v6.23.0 |
| **Footprint** | Loose files across `~/.claude` | One skill dir with a clean install payload |

Under the hood it's the same system v5 introduced: **Pulse** (the Life Dashboard on port 31337), the **DA** identity layer, the Algorithm's seven-phase loop, the **ISA** primitive, and structured memory. 6.0.0 changes how the system is packaged and installed — not what it is. If you ran v5, everything you relied on is still here.

## Install

**Give it to your AI.** Paste this into Claude Code and say **"install this"** — your AI does the whole setup for you.

```bash
curl -fsSL https://ourlifeos.ai/install.sh | bash
```

Prefer the terminal? Run the same command yourself. You'll need **Claude Code** and **bun**.

## What's included

One install lays down the whole system:

- **Current → Ideal State** and your **TELOS** — what you're working toward
- **The Algorithm** (v6.23.0) — the loop that turns a request into criteria and climbs until they hold
- **The ISA (Ideal State Artifact)** — one document capturing what "done" looks like as verifiable criteria; every Algorithm run climbs against it
- **49 skills**, the **hook system**, and the **router**
- **Pulse** — your Life Dashboard, with custom spinner verbs and tooltips
- **Memory**, **voice**, and a **USER template** you fill in with your own goals

See the **[Core Components](../../README.md#core-components)** overview for what each piece does.

## Upgrading from v5

Back up first — `cp -r ~/.claude ~/.claude-backup-$(date +%Y%m%d)` — then install. Your `USER/` customizations are never touched, and settings merge rather than overwrite, so your hooks, statusline, and custom config are preserved.

---

<div align="center">

New name, same system. If you ran PAI, this is the next version of it.

</div>
