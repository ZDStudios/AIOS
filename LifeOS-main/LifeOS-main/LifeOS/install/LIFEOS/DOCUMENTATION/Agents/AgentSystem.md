# LifeOS Agent System

> Agents are how the LifeOS parallelizes the hill-climb. One DA fronts the system (thesis: `../LifeOs/LifeOsThesis.md`), but closing a current→ideal-state gap often takes many hands — research fanned out, code written, work audited cross-vendor. The routing rules below exist so that fan-out stays deterministic and the right kind of worker handles each leg of the climb.

**Authoritative reference for agent routing in LifeOS. Three distinct systems exist—never confuse them.**

---

## 🚨 THREE AGENT SYSTEMS — CRITICAL DISTINCTION

LifeOS has three agent systems that serve different purposes. Confusing them causes routing failures.

| System | What It Is | When to Use | Has Unique Voice? |
|--------|-----------|-------------|-------------------|
| **Task Tool Subagent Types** | Pre-built agents in Claude Code (Explore, Plan, general-purpose, etc.) | Internal workflow use ONLY | No |
| **Named Agents** | Persistent identities with backstories and voices (your own personas) | Recurring work, voice output, relationships | Yes |
| **Custom Agents** | Dynamic agents composed via ComposeAgent from traits | When user says "custom agents" | Yes (trait-mapped) |

---

## 🚫 FORBIDDEN PATTERNS

> **Note:** `Architect`, `Designer`, and `Engineer` were retired as agent types. Don't reach for any static built-in `subagent_type` when the user asks for custom agents — compose via the Agents skill instead.

**When user says "custom agents":**

```typescript
// ❌ WRONG - a static built-in subagent_type is NOT a custom agent
//   (Architect/Designer/Engineer were retired; this was always the anti-pattern)
Task({ subagent_type: "<static built-in type>", prompt: "..." })

// ✅ RIGHT - Invoke the Agents skill for custom agents
Skill("Agents")  // → CreateCustomAgent workflow
// OR follow the workflow directly:
// 1. Run ComposeAgent with different trait combinations
// 2. Launch agents with the generated prompts
// 3. Each gets unique personality + voice

// ❌ WRONG - User says "specialized agents to brainstorm", you reach for static types
Task({ subagent_type: "<static built-in type>", prompt: "Brainstorm UI ideas..." })

// ✅ RIGHT - Use Agents skill for ANY user-requested specialized agents
Skill("Agents")  // → CreateCustomAgent workflow with unique traits per agent
// Each agent gets: unique name, unique voice, unique personality via ComposeAgent
```

---

## Routing Rules

### The Word "Custom" Is the Trigger

| User Says | Action | Implementation |
|-----------|--------|----------------|
| "**custom agents**", "spin up **custom** agents" | Invoke Agents skill | `Skill("Agents")` → CreateCustomAgent workflow |
| "agents", "**specialized agents**", "launch agents", "parallel agents" | Custom agents via Agents skill | `Skill("Agents")` → ComposeAgent → `Task({ subagent_type: "general-purpose" })` |
| "research X", "investigate Y" | Research skill | `Skill("Research")` → appropriate researcher agents |
| "use Remy", "get Ava to" | Named agent | Use appropriate researcher subagent_type |
| (Code implementation, standard) | `general-purpose` + senior-engineer/TDD brief | `Task({ subagent_type: "general-purpose", prompt: "Senior engineer, TDD. …" })` |
| (Production-grade code, E3+, "no shortcuts" directive, OR named "Forge") | Forge (cross-vendor, OpenAI-family GPT-5.5 via `codex exec`) | `Agent({ subagent_type: "Forge" })` |
| (Cross-vendor audit, MANDATORY at E4/E5 in VERIFY) | Forge in audit mode (read-only, OpenAI-family GPT-5.5) | `Agent({ subagent_type: "Forge", prompt: "MODE: audit\n…" })` |
| (Architecture/design) | `general-purpose` + system-design brief | `Task({ subagent_type: "general-purpose", prompt: "System design / distributed systems. …" })` |
| (Claude Code hooks, settings, commands, MCP, agents, API) | Claude Code Guide | `Task({ subagent_type: "claude-code-guide" })` — verify latest features before implementing |

### Custom Agent Creation Flow

When user requests custom agents:

1. **Invoke Agents skill** via `Skill("Agents")` or follow CreateCustomAgent workflow
2. **Run ComposeAgent** for EACH agent with DIFFERENT trait combinations
3. **Extract prompt and voice_id** from ComposeAgent output
4. **Launch agents** with Task tool using the composed prompts
5. **Voice results** using each agent's unique voice_id

```bash
# Example: 3 custom research agents
bun run ~/.claude/skills/Agents/Tools/ComposeAgent.ts --traits "research,enthusiastic,exploratory"
bun run ~/.claude/skills/Agents/Tools/ComposeAgent.ts --traits "research,skeptical,systematic"
bun run ~/.claude/skills/Agents/Tools/ComposeAgent.ts --traits "research,analytical,synthesizing"
```

---

## ⚠️ Task Tool Subagent Types — INTERNAL WORKFLOW USE ONLY

**These are NOT for user-requested custom/specialized agents.** When the user asks for specialized agents, custom agents, or agents with unique perspectives, ALWAYS use the Agents skill (ComposeAgent) instead. See Routing Rules above.

These are pre-built agents in the Claude Code Task tool. They are for **internal workflow use**, not for user-requested "custom agents."

| Subagent Type | Purpose | When Used |
|---------------|---------|-----------|
| `general-purpose` | Custom agents via ComposeAgent; code/design/architecture work with a role brief in the prompt | Parallel work with task-specific prompts (the `Architect`/`Designer`/`Engineer` types were retired — use this with a brief) |
| `Explore` | Codebase exploration | Finding files, understanding structure |
| `Plan` | Implementation planning | Plan mode |
| `Forge` | Cross-vendor coder + auditor (OpenAI-family GPT-5.5 via `codex exec`) — `MODE: build` writes production code, `MODE: audit` is the read-only E4/E5 VERIFY pass (folded in the former Cato agent) | Production-grade code at E3+; MANDATORY cross-vendor audit at E4/E5 in VERIFY |
| `claude-code-guide` | Claude Code knowledge (hooks, settings, slash commands, MCP, agent types, keybindings, IDE, Agent SDK, Claude API) | Any task involving Claude Code internals — freshness check before implementing |
| `ClaudeResearcher` | Claude-based research | Research skill workflows |
| `GeminiResearcher` | Gemini-based research | Research skill workflows |
| `GrokResearcher` | Grok-based research | Research skill workflows |

**These do NOT have unique voices or ComposeAgent composition.**

---

## Named Agents (Persistent Identities)

Named agents have rich backstories, personality traits, and mapped voices. They provide relationship continuity across sessions. **Compose your own named-agent roster** — the examples below are illustrative; every LifeOS user defines their own personas.

| Agent (example) | Role | Voice | Use For |
|-----------------|------|-------|---------|
| Architecture Lead | Architecture lead | Premium voice preset | Long-term architecture decisions |
| Senior Engineer | Senior engineer | Premium voice preset | Strategic technical leadership |
| Security Specialist | Offensive security | Enhanced voice preset | Red-team review, vulnerability hunting |
| Primary Researcher | Strategic research lead | Premium voice preset | Deep research + synthesis |
| Secondary Researcher | Multi-perspective research | Alternate voice preset | Comparative analysis |

**Full backstories and voice settings:** Individual `agents/*.md` files (persona frontmatter + body) — define your own.

---

## Custom Agents (Dynamic Composition)

Custom agents are composed on-the-fly from traits using ComposeAgent. Each unique trait combination maps to a different ElevenLabs voice.

### Trait Categories

**Expertise** (domain knowledge):
`security`, `legal`, `finance`, `medical`, `technical`, `research`, `creative`, `business`, `data`, `communications`

**Personality** (behavior style):
`skeptical`, `enthusiastic`, `cautious`, `bold`, `analytical`, `creative`, `empathetic`, `contrarian`, `pragmatic`, `meticulous`

**Approach** (work style):
`thorough`, `rapid`, `systematic`, `exploratory`, `comparative`, `synthesizing`, `adversarial`, `consultative`

### Voice Mapping Examples

| Trait Combo | Voice | Why |
|-------------|-------|-----|
| contrarian + skeptical | Clyde (gravelly) | Challenging intensity |
| enthusiastic + creative | Jeremy (energetic) | High-energy creativity |
| security + adversarial | Callum (edgy) | Hacker character |
| analytical + meticulous | Charlotte (sophisticated) | Precision analysis |

**Full trait definitions and voice mappings:** `skills/Agents/Data/Traits.yaml`

---

## Model Selection

Always specify the appropriate model for agent work:

| Task Type | Model | Speed |
|-----------|-------|-------|
| Simple checks, grunt work | `haiku` | 10-20x faster |
| Standard analysis, implementation | `sonnet` | Balanced |
| Deep reasoning, architecture | `opus` | Maximum intelligence |

```typescript
// Parallel custom agents benefit from haiku/sonnet for speed
Task({ prompt: agentPrompt, subagent_type: "general-purpose", model: "sonnet" })
```

---

## Spotcheck Pattern

**Always launch a spotcheck agent after parallel work:**

```typescript
Task({
  prompt: "Verify consistency across all agent outputs: [results]",
  subagent_type: "general-purpose",
  model: "haiku"
})
```

---

## Knowledge Archive Access

Agents can query the **Knowledge Archive** (`~/.claude/LIFEOS/MEMORY/KNOWLEDGE/`) for accumulated knowledge organized by 4 entity types: People (human beings), Companies (organizations), Ideas (insights/theses/analyses), Research (longer-form research notes). Topic is a tag, not a domain. Managed by Algorithm LEARN phase (direct writes), `LIFEOS/TOOLS/KnowledgeHarvester.ts` (validation/maintenance), and the `/knowledge` skill. Particularly useful for research agents and custom agents composed with specialized traits.

---

## Managed Agents (Cloud API)

Anthropic's hosted agent service for long-horizon, unattended work. **Separate from Claude Code** — runs on Anthropic's cloud infrastructure with durable sessions and sandboxed execution.

**Status:** Beta. All API accounts have access. Beta header: `anthropic-beta: managed-agents-2026-04-01` (SDK handles automatically).
**Pricing:** Standard token costs + $0.08/active session-hour (pro-rated).
**Docs:** https://www.anthropic.com/engineering/managed-agents

### Architecture

Three decoupled components:
- **Brain** (Claude + harness) — stateless inference, restarts without data loss
- **Hands** (execution environments) — sandboxed containers, provisioned on-demand
- **Session** (durable event log) — append-only, survives crashes, resumes via `wake(sessionId)`

### API Surface

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/agents` | Create reusable agent blueprint (model, system, tools) |
| `POST /v1/environments` | Create container config (packages, networking, secrets) |
| `POST /v1/sessions` | Start a running instance from agent + environment |
| `POST /v1/sessions/{id}/events` | Send messages/tool results |
| `GET /v1/sessions/{id}/stream` | SSE event stream |

### When to Use

- Task runs for **hours unattended** (overnight security scans, content processing)
- Needs to **survive disconnects** (durable event log, not session-scoped)
- Requires **sandboxed execution** (untrusted code, credential isolation via vaults)
- Triggered by **CI/external event** (webhook-initiated, not interactive)

### When NOT to Use

- Interactive work (use Agent Teams or Custom Agents)
- Tasks under 30 minutes (coordination overhead exceeds benefit)
- Tasks needing LifeOS context (managed agents don't load CLAUDE.md or LifeOS skills)

### Example (TypeScript)

```typescript
import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic();

const agent = await client.beta.agents.create({
  name: "Security Scanner",
  model: "claude-sonnet-4-6",
  system: "You are a security auditor...",
  tools: [{ type: "agent_toolset_20260401" }],
});

const env = await client.beta.environments.create({
  name: "scanner-env",
  config: { type: "cloud", networking: { type: "unrestricted" } },
});

const session = await client.beta.sessions.create({
  agent: agent.id,
  environment_id: env.id,
});

// Stream results
const stream = await client.beta.sessions.events.stream(session.id);
await client.beta.sessions.events.send(session.id, {
  events: [{ type: "user.message", content: [{ type: "text", text: "Audit the auth module" }] }],
});
```

---

## Agent System Preference Order

When the Algorithm needs to delegate work, use this priority:

| Priority | System | Trigger | Key Trait |
|----------|--------|---------|-----------|
| **1. DEFAULT** | Agent Teams | Any parallel work, task dependencies, coordination needed | Persistent, peer messaging, shared task list |
| **2. EXPLICIT** | Custom Agents | {{PRINCIPAL_NAME}} says "custom agents" | Unique personalities, voices, one-shot |
| **3. UNATTENDED** | Managed Agents | Overnight, CI, survives disconnects | Durable, sandboxed, cloud |
| **4. INTERNAL** | Built-in types | Algorithm routing, specific subagent type needed | Explore, Plan, general-purpose, etc. |

---

## Agent Watchdog (Background Agent Monitoring)

Background agents can hang or go silent with no visibility. The Pulse agent-guard hook automatically injects a Monitor watchdog reminder when `run_in_background: true` agents are spawned. The watchdog (`Tools/AgentWatchdog.ts`) monitors `tool-activity.jsonl` for silence — if no tool calls for 90 seconds while agents are active, it alerts via the Monitor tool's stdout notification mechanism. One persistent watchdog covers all background agents per session.

---

## Observer Team Archetype (Read-Only Oversight)

Distinct from functional teams (engineering, design, security, etc.). An Observer team watches what a primary agent DID — not what it said. Mythos-class autonomous agents can represent concealment and strategic manipulation in their activations, so chain-of-thought oversight is insufficient; audit-log oversight becomes load-bearing.

**Shape:**
- **Read-only** — observers never call write tools. Violations = immediate self-halt.
- **Fed the audit log** — consume `MEMORY/OBSERVABILITY/tool-activity.jsonl` (with `ground_truth` captured by `ToolActivityTracker.hook.ts`), not chat transcripts.
- **Vote** — continue / halt / escalate. Majority rule; any escalate bubbles to {{PRINCIPAL_NAME}} via Pulse.
- **Cost-justified by catastrophe prevention**, not feature velocity.

**Use ONLY when BOTH conditions hold:**
1. **Time is not a constraint** — observers add 30-second voting cycles and ~$0.10/primary-hour in Sonnet cost. They trade speed for safety.
2. **Auditability is the primary requirement** — when the goal is a defensible, verifiable trail of what the primary agent did (for compliance, post-incident review, or catastrophe prevention), not fast turnaround.

**Typical fit:** overnight / unattended autonomous runs, production deploys where post-hoc review matters, credential rotation, PATTERNS.yaml or security-hook edits, any work where "I want to be able to prove nothing dangerous happened" is the goal.

**Do NOT use for:** any time-sensitive work, interactive sessions where {{PRINCIPAL_NAME}} is watching, short reactive tasks (<5 tool calls), read-only analysis, or anything where preflight gates A/B/C/D already give sufficient guarantees.

**Invocation:** `Skill("Agents")` → `SPAWNOBSERVERS` workflow (`skills/Agents/Workflows/SpawnObservers.md`). Three observer instances spawn with specializations: policy-compliance, intent-drift, blast-radius.

---

## References

- **Master Architecture:** `~/.claude/LIFEOS/DOCUMENTATION/LifeosSystemArchitecture.md` — authoritative system-of-systems reference
- **Agents Skill:** `skills/Agents/SKILL.md` — Custom agent creation, workflows
- **ComposeAgent:** `skills/Agents/Tools/ComposeAgent.ts` — Dynamic composition tool
- **Traits:** `skills/Agents/Data/Traits.yaml` — Trait definitions and voice mappings
- **Agent Personalities:** Individual `agents/*.md` files — Named agent backstories and voice settings
- **Managed Agents:** https://www.anthropic.com/engineering/managed-agents — Anthropic cloud agent API

---

*Last updated: 2026-04-29*
