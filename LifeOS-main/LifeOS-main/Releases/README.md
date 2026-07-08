<!--
  GENERATED FILE — do not hand-edit the release list below.
  Source of truth: Releases/releases.json
  Regenerate:      bun Tools/GenerateReleasesPage.ts
  A release dir with no manifest entry FAILS the build, so this text always
  matches the version directories GitHub shows above it.
-->
<div align="center">

<img src="releases-icon.png" alt="LifeOS Releases" width="220">

# LifeOS Releases

</div>

---

## What Are Releases?

LifeOS ships as a **single self-contained skill** — your AI installs it for you. Each release is a versioned snapshot of that skill. There's no `~/.claude/` directory to copy; installing the skill *is* the install.

**About the older releases.** LifeOS began as **PAI (Personal AI Infrastructure)**, and back then it shipped as a `~/.claude/` directory you installed into your home folder. Releases **v2.3–v5.0.0** are that era — kept here for history, not for new installs. **v6.0.0** is the first skill-based release and the current model. Same system, same lineage — just no longer a `.claude/` directory.

---

## Available Releases

### v6.0.5 — Rename in the Code, New Harvest Skill (Current)

Carries the PAI→LifeOS rename the rest of the way through the codebase, adds the Harvest skill, and sharpens the Algorithm's verification doctrine. Same system as 6.0.0, cleaner throughout.

- PAI→LifeOS rename reaches the code — identifiers and prose read LifeOS throughout; runtime-critical paths left byte-identical on purpose
- New Harvest skill — mine any URL, video, or article for what's useful to your LifeOS; report-only
- Algorithm v6.24.0 — motion verification: animation, transition, and multi-step-flow ISCs close on a frame-scrub gallery, not a single screenshot
- Installer fix — bootstrap install.sh now fetches the version it advertises

**[Get v6.0.5 →](v6.0.5/)**

---

### v6.0.3 — Comprehensive AI-native install

Makes the install doc comprehensive and gets the constitutional layer loading on its own.

- Comprehensive component menu — INSTALL.md lays out the full two-tier model: Core plus à-la-carte enhancements (hooks, statusline, tooltips, spinner verbs, agents, Pulse, background jobs)
- The `lifeos` launch alias wires `--append-system-prompt-file` so the constitutional layer actually loads
- One canonical INSTALL.md rendered at ourlifeos.ai/install for humans and AIs

**[Get v6.0.3 →](v6.0.3/)**

---

### v6.0.2 — .md-first AI-native install

Skill-only distribution with an AI-native, `.md`-first install.

- The whole system ships as one self-contained LifeOS/ skill
- The shipped install.sh pins v6.0.2 and points at danielmiessler/LifeOS
- Security-clean: 15/15 release gates plus emit-time contract, staleness, and payload gates

**[Get v6.0.2 →](v6.0.2/)**

---

### v6.0.0 — The Life Operating System

LifeOS ships as a single self-contained skill, not a `.claude/` copy — the full framework installs through your AI.

- Algorithm v6.23.0
- Two-tier core components: Current→Ideal, the Algorithm, Skills, Hooks, Router, Pulse, custom spinner verbs, and custom tooltips, plus the supporting subsystems (Memory, Agents, Voice, Learning, Security)
- Skill-only distribution via the LifeOS install skill
- Full Pulse Life Dashboard + menu bar app

**[Get v6.0.0 →](v6.0.0/)**

---

## Legacy Releases (`.claude/`-era)

These predate the skill model — they shipped as `~/.claude/` directories. Kept for history; **not** the current install path.

### v5.0.0 — Life Operating System

The release that reframed the whole system as a Life Operating System built around the move from current state to ideal state.

**[Get v5.0.0 →](v5.0.0/)**

---

### v4.0.3 — Community PR Patch

4 community-contributed fixes from open PRs.

- Inference: JSON parsing now handles arrays `[]` alongside objects `{}`
- Documentation: removed 29 dead references from CONTEXT_ROUTING.md
- Portability: WorldThreatModelHarness uses `$PAI_DIR` instead of hardcoded path
- Installer: migrates user context from v2.5/v3.0 paths on upgrade

**[Get v4.0.3 →](v4.0.3/)**

---

### v4.0.2 — Bug Fix Patch

13 surgical fixes — no new features, no breaking changes.

- Linux compatibility: cross-platform OAuth token extraction, GNU coreutils `tr` fix
- Installer: correct alias path, shell detection (bash/fish/zsh), headless CLI fallback
- Statusline: width cache, algorithmVersion field, cross-platform OAuth
- Hooks: inference guard (~15s savings), lineage tracking, dead code removal, exit codes, voice config

**[Get v4.0.2 →](v4.0.2/)**

---

### v4.0.1 — Upgrade Path & Preferences

Patch release addressing community feedback on upgrade difficulties and missing preferences.

- Upgrade path documentation with backup, merge, and post-upgrade checklist
- Configurable temperature unit (Fahrenheit/Celsius) in statusline
- Installer prompts for temperature preference during setup
- Statusline fixes: dynamic timezone, context fallback, startup estimate, f-string syntax (PRs #762, #780, #806)
- FAQ fixes (removed stale Python reference, improved recovery guidance)

**[Get v4.0.1 →](v4.0.1/)**

---

### v4.0.0 — Lean and Mean

38 flat skill directories compressed into 12 hierarchical categories. Dead systems removed. Context footprint cut in half.

- 63 Skills, 21 Hooks, 180 Workflows
- Algorithm v3.5.0
- CLAUDE.md template system with BuildCLAUDE.ts + SessionStart hook
- Comprehensive security sanitization (33+ files cleaned)
- ~19% context at startup (down from ~38%)

**[Get v4.0.0 →](v4.0.0/)**

---

### v3.0.0 — The Algorithm Matures

The Algorithm reaches v1.4.0 with constraint extraction, build drift prevention, persistent PRDs, and parallel loop execution.

- 38 Skills, 20 Hooks, 162 Workflows
- Algorithm v1.4.0
- Full installer with GUI wizard
- 10 new skills
- Agent teams/swarm
- Voice personality system
- PRD system

**[Get v3.0 →](v3.0/)**

---

### v2.5.0 — Think Deeper, Execute Faster

The Algorithm learns metacognition — thinking about how it thinks — and parallel execution.

- 28 Skills, 17 Hooks, 356 Workflows
- Two-pass capability selection with ISC validation
- Thinking tools with justify-exclusion principle
- Parallel-by-default execution for independent tasks
- 7 named composition patterns for capability orchestration

**[Get v2.5 →](v2.5/)**

---

### v2.4.0 — The Algorithm

Our first attempt at a general problem solver built into PAI to pursue Euphoric Surprise.

- 29 Skills, 15 Hooks, 331 Workflows
- 7-phase problem-solving with ISC tracking
- Improved installation wizard
- Voice notifications via ElevenLabs

**[Get v2.4 →](v2.4/)**

---

### v2.3.0 — Continuous Learning

The release that introduced persistent learning and sentiment capture.

- 20 Skills, session continuity
- Implicit/explicit rating capture
- Memory system with WORK, STATE, LEARNING directories

**[Get v2.3 →](v2.3/)**

---

## Installation

LifeOS installs as a skill — give it to your AI. Paste this into any capable harness (Claude Code, Cursor, Codex, …):

> **Read https://ourlifeos.ai/install and install LifeOS for me.**

Or the one-line shortcut for Claude Code on macOS/Linux:

```bash
curl -fsSL https://ourlifeos.ai/install.sh | bash
```

The install asks for your name, AI name, timezone, temperature unit, and optional voice preferences.

**Legacy releases (v2–v5)** installed the old way — as a `~/.claude/` directory with their own `install.sh`. That's no longer how LifeOS works; if you specifically need an old version, follow that release's own README. New installs use the skill above.

See the [main README](../README.md) for more.

---

## Troubleshooting

**Install didn't take?** Re-run it — just ask your AI to install LifeOS again from [ourlifeos.ai/install](https://ourlifeos.ai/install).

**Hooks not firing?** Restart your harness after installation.

---

**Questions?** See the main [LifeOS README](../README.md).
