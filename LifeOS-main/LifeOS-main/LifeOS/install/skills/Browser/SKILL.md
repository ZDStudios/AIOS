---
name: Browser
description: "Headless browser automation via agent-browser — Rust CLI daemon with persistent auth profiles for fast, scriptable, parallel browser work. Batch commands, network interception, device emulation, per-site profile auth (one-time headed login, headless forever after), parallel isolated sessions via --session. Workflows: ReviewStories (fan out YAML user stories to parallel reviewer agents), Automate (parameterized recipe templates), Update. Delegates background parallel scraping to general-purpose agents; falls back to Interceptor if a site has bot detection. USE WHEN headless browser, batch scrape, fast screenshot, dev server test, parallel browser, background automation, extract data, review stories, automate recipe, batch screenshots, scrape multiple pages in parallel. NOT FOR deploy verification or UI confirmation with real Chrome (use Interceptor), simple single-URL fetching (use WebFetch), CAPTCHA or bot-detection bypass (use BrightData or Interceptor), or social platform actor-based scraping (use Apify)."
version: 10.0.0
effort: medium
---

## Customization

**Before executing, check for user customizations at:**
`~/.claude/LIFEOS/USER/CUSTOMIZATIONS/SKILLS/Browser/`

If this directory exists, load and apply any PREFERENCES.md, configurations, or resources found there. These override default behavior. If the directory does not exist, proceed with skill defaults.


## MANDATORY: Voice Notification (REQUIRED BEFORE ANY ACTION)

**You MUST send this notification BEFORE doing anything else when this skill is invoked.**

1. **Send voice notification**:
   ```bash
   curl -s -X POST http://localhost:31337/notify \
     -H "Content-Type: application/json" \
     -d '{"message": "Running the WORKFLOWNAME workflow in the Browser skill to ACTION"}' \
     > /dev/null 2>&1 &
   ```

2. **Output text notification**:
   ```
   Running the **WorkflowName** workflow in the **Browser** skill to ACTION...
   ```

**This is not optional. Execute this curl command immediately upon skill invocation.**

# Browser v10.0.0 — Browser Automation

## What It Does

Drives a headless browser from the command line through `agent-browser`, a Rust CLI daemon. Opens pages, clicks, fills forms, takes screenshots, runs JS, intercepts network, and emulates devices. Holds per-site auth profiles so you log in once and stay logged in for headless runs after that. Batches commands, runs sessions in parallel, and hands browser work to background agents.

## The Problem

Most browser automation is slow to script, leaks state between runs, and forces a fresh login every time. You either babysit a headed browser or fight a framework that re-authenticates on every call. When you need to screenshot ten pages, scrape a logged-in site, or run several scrapes at once, the per-run startup and auth cost dominates. This skill keeps a daemon warm, persists auth per site, and lets you fan work out to parallel sessions and agents.

## How It Works

**Tool:** `agent-browser` — headless Rust CLI daemon with persistent auth profiles.

**If agent-browser isn't working or a site has bot detection, use the Interceptor skill instead.** Interceptor is a Chrome extension with zero CDP fingerprint — passes all major bot detection checks.

### Does the site need auth?

Use `--profile ~/.agent-browser/profiles/<site>`. If profile exists, auth is automatic. If not, run `--headed` once for login, then headless forever.

---

## agent-browser

Native Rust daemon. Persistent profiles for auth. Headless by default.

### Quick One-Shot Commands

```bash
agent-browser open https://example.com && agent-browser screenshot /tmp/shot.png
agent-browser open https://example.com && agent-browser screenshot --full /tmp/full.png
agent-browser open https://example.com && agent-browser pdf /tmp/page.pdf
```

### Session-Based Interaction

```bash
# 1. OPEN
agent-browser open https://example.com

# 2. WORK
agent-browser snapshot                    # a11y tree with @eN refs (for AI)
agent-browser click @e12                  # click by ref
agent-browser fill @e15 "hello"           # fill input by ref
agent-browser screenshot /tmp/shot.png    # screenshot
agent-browser eval "document.title"       # run JS

# 3. CLOSE — when done
agent-browser close
```

### Authenticated Browsing (Per-Site Profiles)

**First-time setup (headed, one-time):**
```bash
# Close any running daemon first
agent-browser close --all

# Launch headed with persistent profile — log in manually
agent-browser --headed --profile ~/.agent-browser/profiles/<site> open https://example.com

# After login completes, all future runs reuse the profile headlessly
```

**Subsequent runs (headless, automatic):**
```bash
agent-browser --profile ~/.agent-browser/profiles/<site> open https://example.com
# Auth is automatic — cookies, IndexedDB, cache all persist
```

**To add a new site:** Close daemon, run `--headed --profile ~/.agent-browser/profiles/<name>` once, log in, done.

### Auth Vault (Alternative)

```bash
agent-browser auth save mysite --url https://example.com --username user --password-stdin
agent-browser auth login mysite    # auto-fills login form
agent-browser auth list            # show saved profiles
```

### Batch Execution

```bash
# Send multiple commands in one shot (fewer tool calls = fewer tokens)
echo '[["open","https://example.com"],["snapshot"],["click","@e12"]]' | agent-browser batch
```

### Advanced Features

```bash
# Connect to already-running Chrome
agent-browser --auto-connect snapshot

# Network interception
agent-browser route "**/*.{png,jpg}" abort     # block images
agent-browser route "https://api.com/*" mock '{"data":"test"}'

# Device emulation
agent-browser --device "iPhone 15" open https://example.com

# Session persistence (cookies + localStorage by name)
agent-browser --session-name myapp open https://example.com
```

### agent-browser Rules

- **Daemon model** — first command starts daemon, subsequent commands connect instantly.
- **Refs use @eN syntax** — `@e12` not `e12`.
- **Profiles persist everything** — cookies, IndexedDB, cache, localStorage.
- **Close with `agent-browser close`** or `close --all` to kill daemon.

---

### Delegating Browser Work to Agents

When you need parallel or background browser work (scraping multiple pages, monitoring), spawn **general-purpose agents** with browser instructions. No dedicated browser agent type needed — this skill IS the expertise.

```
Agent(subagent_type="general-purpose", prompt="
  Use agent-browser CLI for all browser work.
  Commands: open <url>, snapshot, click @eN, fill @eN 'text', screenshot /path.
  For authenticated sites: --profile ~/.agent-browser/profiles/<site>
  Refs use @eN syntax from snapshots.
  [your specific task instructions here]
")
```

For parallel isolation, each agent uses `--session <name>`:
```
Agent 1: agent-browser --session scrape1 open https://site-a.com
Agent 2: agent-browser --session scrape2 open https://site-b.com
```

**Fallback:** If agent-browser fails or the site has bot detection, use the **Interceptor** skill instead.

**Legacy built-in agents — REMOVED 2026-06-10.** BrowserAgent and UIReviewer were Claude Code built-ins whose internals cannot be modified; they run browser automation that LifeOS no longer uses. Route all browser work through the **Interceptor** skill (verification, authenticated flows) or **agent-browser** (headless scraping).

---

## Workflow Routing

| Workflow | Trigger | File |
|----------|---------|------|
| ReviewStories | "review stories", "run stories", "ui review", "validate stories" — fan out YAML stories to parallel reviewer agents | `Workflows/ReviewStories.md` |
| Automate | "automate", "recipe", "template", or a recipe name — load and execute a parameterized recipe template | `Workflows/Automate.md` |
| Update | "update", "check version" — verify browser tools are current and working | `Workflows/Update.md` |

---

## Gotchas

- **SKIP-gate (check before anything else): task is deploy-verification or UI confirmation → STOP, route to Interceptor.** Machine-checkable precheck: scan the request for `deploy|verify|verification|confirm.*UI|UI.*confirm` — if the task is verifying a deploy or confirming a UI change, the LIFEOS_SYSTEM_PROMPT mandates Interceptor (real Chrome), not headless Browser. When this gate fires, announce the skip and why in the response ("Skipping Browser — deploy/UI verification routes to Interceptor per system-prompt mandate") — a silent skip is a failure.

---

## Stories — YAML User Story Validation

Define user stories in YAML and validate them in parallel with general-purpose reviewer agents.

**Directory:** `skills/Browser/Stories/`

```yaml
name: App Name
url: https://example.com
stories:
  - name: Story name
    steps:
      - action: click
        target: "LLM-readable description"
    assertions:
      - type: snapshot_contains
        text: "expected text"
```

Run with: `"review stories"` or `"run stories in HackerNews.yaml"`

---

## Recipes — Parameterized Templates

Reusable Markdown templates with `{PROMPT}` injection.

**Directory:** `skills/Browser/Recipes/`

| Recipe | Description | Tool |
|--------|-------------|------|
| `SummarizePage.md` | Extract content summary | ai-agent |
| `ScreenshotCompare.md` | Before/after comparison | agent-browser |
| `FormFill.md` | Fill form fields | agent-browser |

Run with: `"automate SummarizePage for https://example.com"`

---

## Examples

**Example 1: Batch screenshots of a dev server**
```
User: "screenshot the five main pages of the dev server"
→ agent-browser open + screenshot per page (batch mode, one daemon)
→ Saves PNGs, returns paths
```

**Example 2: Authenticated scrape**
```
User: "extract the data table from my dashboard"
→ Opens with --profile ~/.agent-browser/profiles/<site> (auth persists from one-time headed login)
→ snapshot + eval to pull the table, returns structured text
```

**Example 3: Story validation**
```
User: "review stories in HackerNews.yaml"
→ ReviewStories workflow: fans YAML stories out to parallel reviewer agents
→ Each agent runs steps + assertions, results aggregated
```

---

## Execution Log

After completing any workflow, append a single JSONL entry:

```bash
echo '{"ts":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","skill":"Browser","workflow":"WORKFLOW_USED","input":"8_WORD_SUMMARY","status":"ok|error","duration_s":SECONDS}' >> ~/.claude/LIFEOS/MEMORY/SKILLS/execution.jsonl
```
