<div align="center">

<img src="https://raw.githubusercontent.com/danielmiessler/LifeOS/main/images/lifeos-logo.png" alt="LifeOS" width="200">

# LifeOS 6.0.5

**The LifeOS rename lands in the code — plus a new Harvest skill.**

[![Skills](https://img.shields.io/badge/Skills-50-22C55E?style=flat)](../../LifeOS/install/skills/)
[![Algorithm](https://img.shields.io/badge/Algorithm-v6.24.0-D97706?style=flat)](../../LifeOS/install/LifeOS/ALGORITHM/)
[![Pulse](https://img.shields.io/badge/Pulse-included-3B82F6?style=flat)](../../LifeOS/install/LifeOS/PULSE/)

</div>

---

LifeOS 6.0.5 is a maintenance release that carries the PAI→LifeOS rename the rest of the way through the system, adds the new **Harvest** skill, and sharpens the Algorithm's verification doctrine. Same system as 6.0.0, cleaner throughout.

## What's new

### The rename reaches the code

6.0.0 renamed the project. 6.0.5 renames the *code* — class-by-class, deliberately. Code identifiers and documentation prose now read "LifeOS" throughout, while behavioral code (paths, regexes, labels the system depends on at runtime) was left byte-identical on purpose. A blind find-and-replace across running code is how you corrupt a working system; the rename was scoped so the prose is clean and nothing breaks.

### New skill — Harvest

**Harvest** mines a single piece of content — a URL, a YouTube video, an article, raw text — for anything genuinely useful to your LifeOS, judged against your whole system. It fetches the content, pulls out candidate ideas and techniques, tags each with a prior status (new / partial / done), ranks by usefulness, and reports where each one maps. It's report-only: adopting anything is always a separate, explicit step.

### Algorithm v6.24.0 — motion gets verified

Verification doctrine gains one clause: an ISC whose subject is *motion* — an animation, a transition, a drag, a multi-step flow — now closes only on a frame-scrub gallery, never a single screenshot. One still can't capture motion, so the doctrine stops pretending it can. Static renders still close on one screenshot; the rule is keyword-triggered so it doesn't tax every task.

### Installer fix

The bootstrap `install.sh` pinned the wrong release tarball. It now fetches the version it advertises. If you install from the one-liner, you get 6.0.5.

## What's different from 6.0.0

|  | v6.0.0 | v6.0.5 |
|---|---|---|
| **Naming** | Renamed in docs and product | Renamed through code identifiers + prose |
| **Skills** | 49 | 50 (adds Harvest) |
| **Algorithm** | v6.23.0 | v6.24.0 (motion verification) |
| **Installer** | Pinned tarball could lag | Fetches the advertised version |

Everything 6.0.0 introduced is still here: one self-contained skill, install-by-prompt, full Pulse on first boot, the seven-phase Algorithm, the ISA primitive, structured memory. This release refines; it doesn't change what the system is.

## Install

**Give it to your AI.** Paste this into Claude Code and say **"install this"** — your AI does the whole setup.

```bash
curl -fsSL https://ourlifeos.ai/install.sh | bash
```

Prefer the terminal? Run the same command yourself. You'll need **Claude Code** and **bun**.

## Upgrading

Back up first — `cp -r ~/.claude ~/.claude-backup-$(date +%Y%m%d)` — then install. Your `USER/` customizations are never touched, and settings merge rather than overwrite.

---

<div align="center">

Same system, cleaner throughout.

</div>
