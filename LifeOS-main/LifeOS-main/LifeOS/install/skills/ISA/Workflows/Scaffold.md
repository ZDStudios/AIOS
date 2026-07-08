# Scaffold Workflow

Generate a fresh ISA from a prompt at a specified effort tier. The output is a populated ISA file at the canonical location with all required sections per tier.

## When to invoke

- The Algorithm at OBSERVE: `Skill("ISA", "scaffold from prompt: <user message> at tier <tier>")`
- User directly: `Skill("ISA", "scaffold from prompt: <prompt>")` — defaults tier to E3 if unspecified
- Ephemeral feature mode: `Skill("ISA", "extract feature <name> as ephemeral file from <master-isa-path>")`

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| prompt | yes | The user's request — verbatim or distilled |
| tier | yes | E1 / E2 / E3 / E4 / E5 |
| project | no | If task targets a known project from PROJECTS.md, the project ISA path is used; otherwise a task ISA at `MEMORY/WORK/{slug}/ISA.md` |
| ephemeral_feature | no | If set, scaffold a feature-file excerpt instead of a full ISA |

## Output

A markdown file at one of:
- `<project-root>/ISA.md` — when `project` is supplied (existing project ISA is read-extended, not overwritten)
- `~/.claude/LIFEOS/MEMORY/WORK/{slug}/ISA.md` — when no project (slug = `YYYYMMDD-HHMMSS_kebab-task-description`)
- `~/.claude/LIFEOS/MEMORY/WORK/{slug}/_ephemeral/<feature>.md` — when `ephemeral_feature` is set

## Procedure

### Step 1 — Voice notification

```bash
curl -s -X POST http://localhost:31337/notify \
  -H "Content-Type: application/json" \
  -d '{"message": "Running the Scaffold workflow in the ISA skill"}' \
  > /dev/null 2>&1 &
```

### Step 2 — Pick the canonical template

Always start by reading `~/.claude/skills/ISA/Examples/canonical-isa.md` for section headers and tone. For E1 reference, read `e1-minimal.md`. For E5 reference, read `e5-comprehensive.md`.

### Step 3 — Preserve principal-stated goal, then derive (revised v6.4.0)

**The canonical rule:** Step 3 must populate `principal_stated_goal` (frontmatter) AND the first quoted sentence of `## Goal` verbatim — both from the same byte-for-byte literal — BEFORE producing any derived section. Derivation (Out of Scope, Constraints, Principles, distilled Goal continuation, ISCs) follows the preservation, anchored to it. If detection does not fire, the preservation step is a no-op and derivation proceeds as today.

#### Step 3a — Detect and preserve the literal goal

Run the four-signal detector on the prompt:

| # | Signal | Pattern | Examples |
|---|--------|---------|----------|
| 1 | **Named metric + threshold** | quantitative target | "get p95 latency under 200ms" · "grow LinkedIn to 70k" · "open rate above 35%" |
| 2 | **Explicit outcome assertion** | "I want X" / "achieve X" / "do this" | "I want Pulse showing all four time horizons" |
| 3 | **Completion condition** | "until X" / "such that X" | "refactor until tests pass" · "ship such that Cato returns no critical findings" |
| 4 | **Structural/design directive** | explicit verb-object on the system | "design how ISA absorbs Codex /goal semantics" · "unify three skills into one" |

**Fail-closed minimum-content rule:** if a candidate literal is under 6 tokens OR contains no propositional content ("make it good", "do better", "refactor this"), set `principal_stated_goal: null` and log the candidate to a Decisions row. Better silent than anchoring against useless text.

**Multi-literal:** if multiple candidates ("do X and Y by Z"), **first wins as `principal_stated_goal:`**; others demote to derived Constraints with `derived_from: principal_stated_goal compound` annotation.

**Classifier handshake:** `TheRouter.hook.ts` may emit `GOAL_SIGNAL: <1|2|3|4|none>` in additionalContext. Trust as hint, re-validate via the detector above.

When detection fires + min-content passes, write the four frontmatter fields:

```yaml
principal_stated_goal: "the verbatim user quote, byte-for-byte"
principal_stated_goal_source: prompt   # prompt | conversation | explicit-revision
principal_stated_goal_signal: <1-4>
principal_stated_goal_locked: <ISO-8601>
```

Copy the verbatim quote into `## Goal` as the first sentence, in quotes, before any derived prose.

#### Step 3b — Derive the residue

Distill what remains:
- Explicit wants beyond the literal (these become Vision + derived Goal prose)
- Explicit not-wants (these become Out of Scope)
- Implied not-wants (industry/context inference — these become Out of Scope)
- Constraints implied by the domain (these become Constraints)
- Principles implied by the user's TELOS (responsiveness, information density, operator-first, etc. — these become Principles)

**The key inversion:** today's distillation runs first and loses the literal. The new rule preserves first, derives second — and derived content is anchored to the preserved literal via the `anchors_to` column in Test Strategy.

### Step 3.5 — Density preflight (v6.5.0 — MANDATORY at E3+; v6.7.0 — EXTENDED to E1/E2 with permissive thresholds)

**Stage 2 of the density × tier gate.** Stage 1 (eligibility) ran in `TheRouter.hook.ts`; this stage measures whether the prompt + recent conversation carry enough signal to scaffold the tier's required sections without speculation.

**v6.7.0 extension:** eligibility now extends to E1 and E2 with permissive thresholds. At E1, the section-fillability term is skipped (ISA at E1 is inline/optional — depending on the term would be circular); the score uses signals 1-6 (the prompt-derived signals) only.

#### Stage 1 → Stage 2 handoff (how Scaffold reads INTERVIEW_ELIGIBLE)

`TheRouter.hook.ts` emits a 4-line block into `additionalContext` on every UserPromptSubmit:

```
MODE: ALGORITHM | TIER: E4 | REASON: … | SOURCE: classifier
GOAL_SIGNAL: 2
GOAL_LITERAL: "verbatim user quote"
INTERVIEW_ELIGIBLE: true
```

The Algorithm-driven model reads this block at OBSERVE. When entering Scaffold Step 3.5 the model inspects the `INTERVIEW_ELIGIBLE` line from the most recent UserPromptSubmit emission:

- Line present AND value `true` → run Stage 2 below.
- Line present AND value `false` → skip Stage 2; proceed to Step 4.
- Line absent (e.g., the prompt is a continuation in conversation-context-override mode and the hook didn't re-fire) → fall back to inferring eligibility from the running tier: `true` iff tier ≥ E3.

This handoff is explicit text-passing; no shared state, no subprocess IPC. The model is the carrier.

**Skip conditions (do not run Stage 2):**
- `INTERVIEW_ELIGIBLE` is absent OR `false` from `additionalContext` (the hook decided this is E1/E2/NATIVE/MINIMAL — fast-path preserved).
- The scaffold call has `ephemeral_feature` set (ephemeral mode operates on already-scaffolded master).

**When `INTERVIEW_ELIGIBLE: true`, compute the density score deterministically:**

| # | Signal | Computation | Contribution |
|---|--------|-------------|--------------|
| **base** | Section-fillability ratio | For each required section at this tier, can it be populated with at least one non-speculative sentence from prompt + last 5 conversation turns? `filled / required` | `0..1` (positive) |
| 1 | Content-token count of `principal_stated_goal` (or prompt if literal is null) after stopword removal | count tokens | `< 12` → `-0.125` |
| 2 | Named-artifact count | file paths, URLs, named systems, named files, named functions | `0` → `-0.125` |
| 3 | Measurable-criterion count | numeric thresholds, comparison operators, named metrics | `0` at E4+ → `-0.125` |
| 4 | Concrete-verb presence | "design/explore/figure out/think about/decide" = vague; "implement/rewrite/deploy/fix/extract/refactor" = concrete | vague-only → `-0.125`; concrete present → `0` |
| 5 | Out-of-Scope-implying language | "not", "without", "except", "instead of" | absent → `-0.125` |
| 6 | Constraint markers | "must", "cannot", "only", "exactly" | absent → `-0.125` |

**Formula:** `density_score = filled_sections / required_sections + Σ(deductions)`. Clamp to `[0, 1]`.

**Defensive guard:** if `required_sections.length === 0` (should never happen — every tier requires ≥1), set `density_score: 1.0` and skip Stage 2.

**Trip threshold (v6.7.0 tier-graduated):**

| Tier | Threshold | Notes |
|------|-----------|-------|
| **E1** | `< 0.10` | Signals 1-6 only (section-fillability skipped). Fires only on truly empty prompts; preserves <90s fast-path. Interview shape: NATIVE-flag form (one-line ambiguity flag prepended to response), NOT 3-question gate. |
| **E2** | `< 0.20` | Signals 1-6 plus optional section-fillability. Fires rarely. Interview shape: NATIVE-flag OR ≤1 mini-interview question with `proceed` override. |
| **E3** | `< 0.30` | Full 7-signal formula (v6.5.0 unchanged). Fires occasionally. Interview shape: ≤3 questions with `proceed`. |
| **E4** | `< 0.50` | Full 7-signal formula (v6.5.0 unchanged). Fires regularly on truly sparse prompts. ≤3 questions with `proceed`. |
| **E5** | `< 0.50` | Full 7-signal formula. Fires per gate AND the E5-mandatory Interview still runs (single invocation when gate fires; deeper walk when gate doesn't). |

Pre-v6.7.0 behavior preserved at E3-E5; new behavior added only at E1/E2.

#### Stage 2 fire — interview prompt format

When the gate trips, emit ONE message to the user before scaffolding any sections beyond Goal:

```
I have N questions before I scaffold this. The prompt is dense in X but thin on Y. Say `proceed` to scaffold on inference; otherwise answer one at a time:

1. <Q1 — chosen from the bounded shape library>
2. <Q2>
3. <Q3>
```

**Q-shape library (use 1-3 in priority order based on which sections are thinnest):**

| Thinnest section | Bounded question shape |
|---|---|
| Vision / Goal | "When this is done, what does the user feel? What would make them rate it 9-10?" |
| Out of Scope | "What would be tempting to add but distract from the core?" |
| Constraints | "What architectural mandates or things-that-must-not-change bound this work?" |
| Test Strategy | "How will you verify it worked? What probe or check would prove the goal landed?" |
| Goal (sparse) | "In one sentence, what's the smallest version of this that still counts as done?" |
| Features | "What are the major work units? What can run in parallel vs sequential?" |
| Principles | "What truths must this work respect regardless of how it's built?" |

Maximum 3 questions per fire. Each is one-question-per-turn; write answers back into the ISA before asking the next.

#### `proceed` semantics

The literal override is `proceed` — **whole-response match only**, trim + lowercase: `response.trim().toLowerCase() === 'proceed'`. Substring matches ("I want to proceed with X") are NOT the override and route to question-1's answer.

#### Logging the gate result (in ISA frontmatter)

Add four optional fields when Stage 2 ran:

```yaml
density_score: 0.42                    # computed 0..1
interview_invoked: true                # whether Stage 2 fired
divergence_risk: medium                # low (skipped) | medium (partial-fill or 1-2 answers) | high (proceed override or fully aborted)
density_gate_acknowledged: true        # always true on E3+ ISAs once Stage 2 has been decided one way or the other
context_checks_fired: [observe-density, observe-sufficiency, plan-refresh]   # NEW v6.7.0 — list of which Context Sufficiency checks ran
context_sufficient: true               # NEW v6.7.0 — final boolean after all OBSERVE checks; null if no check ran
```

| Path | `density_score` | `interview_invoked` | `divergence_risk` |
|---|---|---|---|
| Stage 2 skipped (eligible=false) | (omit) | (omit) | (omit) |
| Stage 2 ran, `score ≥ 0.5` (gate didn't fire) | 0.5-1.0 | false | low |
| Stage 2 fired, user answered all questions | 0.0-0.5 | true | low |
| Stage 2 fired, user answered some + `proceed` | 0.0-0.5 | true | medium |
| Stage 2 fired, user said `proceed` immediately | 0.0-0.5 | true | high |
| Stage 2 fired, user aborted mid-interview | 0.0-0.5 | true | high |

#### Logging on `proceed` override

When user invokes `proceed` after seeing the questions:
1. Append a Decisions row: `YYYY-MM-DD HH:MM: density gate fired (score=N), user invoked proceed — divergence_risk: <medium|high>`
2. Set frontmatter `divergence_risk: high` (or `medium` if some questions were answered)
3. VERIFY phase surfaces this as a known risk in `## Verification` rather than a surprise.

### Step 3.6 — Sufficiency Check (NEW v6.7.0 — MANDATORY at all ALGORITHM tiers when Density Gate passes)

The Density Gate measures structural-sparsity. The Sufficiency Check measures **semantic ambiguity** — a prompt can be dense (named artifacts, measurable criteria) yet still admit multiple equally-plausible builds. Sufficiency Check runs *only when Density Gate passed* — they're ordered, not parallel.

**Deterministic inspection (no LLM call):**

| Fork signal | What it looks like |
|-------------|-------------------|
| Compound clauses | "X and Y", "X or Y" — multiple objects, ambiguous which is primary |
| Abstract verbs without object specificity | "design", "improve", "modernize", "secure" with no constraint |
| Missing principal-preference markers | UI work with no design hint, color, framework |
| Undisclosed constraint markers | architecture work with no cost/time/team-size |

**Decision:**
- **0 fork candidates** → write `context_sufficient: true`. Proceed to Step 4.
- **≥1 fork candidate at E1/E2** → prepend NATIVE-form ambiguity flag to eventual response: `⚠️ Picking X over Y because R; redirect if wrong.` Write `context_sufficient: false`, append `observe-sufficiency` to `context_checks_fired`.
- **≥1 fork candidate at E3+** → fire ≤3-question interview, `proceed` override available. Write each answer back into the ISA section. Same emission contract as Density Gate interview.

**Output line:** `🧭 SUFFICIENCY CHECK: [passed | flag-emitted ("X vs Y") | interview-fired]`

### Step 3.7 — PLAN-Entry Context-Sufficiency Refresh (NEW v6.7.0 — invoked from Algorithm PLAN phase, not Scaffold)

This sub-step is invoked **from the Algorithm PLAN phase**, not from Scaffold OBSERVE. Documented here for canonical location.

When Algorithm enters PLAN, before the planning block, ask:
*"In THINK, did any premortem, riskiest-assumption, or capability output surface information that — if I'd had it at OBSERVE — would have changed the Goal, Vision, or Out-of-Scope sections?"*

- **No** → output `🔁 PLAN REFRESH: passed`. No frontmatter change.
- **Yes** → log a Decisions row naming the surface and implied goal-shift, set `divergence_risk: medium`, append `plan-refresh` to `context_checks_fired`. **Do not block phase transition.**

Soft-gate teeth: EXECUTE opens with a flag acknowledgment line; VERIFY surfaces it in completion summary. Without those, the gate is decorative.

### Step 4 — Write frontmatter

```yaml
---
task: "8 word task description"
slug: YYYYMMDD-HHMMSS_kebab-description
project: <name>            # only when targeting a known project
effort: <tier>
effort_source: <auto|explicit|gate-floor>
phase: observe
progress: 0/<isc-count>
mode: interactive
started: <ISO-8601>
updated: <ISO-8601>
# v6.4.0 — only when goal-signal detection fired + min-content rule passed
principal_stated_goal: "verbatim quote"
principal_stated_goal_source: prompt
principal_stated_goal_signal: 2
principal_stated_goal_locked: <ISO-8601>
# v6.5.0 — only when Stage 2 of the density × tier gate ran (E3+)
density_score: 0.42
interview_invoked: true
divergence_risk: medium
density_gate_acknowledged: true
---
```

### Step 5 — Write required sections per tier

| Tier | Required Sections |
|------|-------------------|
| E1 | Goal, Criteria |
| E2 | Problem, Goal, Criteria, Test Strategy |
| E3 | Problem, Vision, Out of Scope, Constraints, Goal, Criteria, Features, Test Strategy |
| E4 | All twelve sections |
| E5 | All twelve sections + run Interview workflow before BUILD |

**Project ISA override:** if `<project>/ISA.md` is the target, require E3+ sections regardless of the active task's tier.

### Step 6 — Apply the Splitting Test to every ISC

Each ISC must satisfy the granularity rule: one binary tool probe per criterion.

| Test | Split when... |
|------|--------------|
| "And"/"With" | Joins two verifiable things |
| Independent failure | Part A can pass while B fails |
| Scope words | "all", "every", "complete" → enumerate |
| Domain boundary | Crosses UI/API/data/logic → one per boundary |
| **No nameable probe** | You can't say which tool would verify it |

### Step 7 — Anti-criteria reminder

Before finishing, ask: **what must NOT happen?** At least one `Anti:` ISC is required. Anti-criteria typically derive from the Out of Scope section + regression-prevention concerns.

### Step 8 — Antecedent (when goal is experiential)

If the goal is experiential — art, design, content, anything that has to "land" — at least one `Antecedent:` ISC is required. The antecedent names a precondition that reliably produces the target experience.

### Step 9 — Run CheckCompleteness

Before returning, invoke `Workflows/CheckCompleteness.md` against the new ISA at the requested tier. If any required section is missing, fill it before declaring the scaffold complete.

### Step 10 — Return the path

Output the absolute path of the created ISA file. Algorithm OBSERVE consumes this path.

## Ephemeral feature mode

When `ephemeral_feature` is set:

1. Read the master ISA at `master_isa_path`.
2. Locate the feature in `## Features` matching `name == ephemeral_feature`.
3. Extract:
   - `## Vision` and `## Goal` from master (read-only context)
   - `## Constraints` filtered to those relevant to this feature
   - `## Criteria` ISCs whose IDs appear in the feature's `satisfies:` list, with stable IDs preserved
   - `## Test Strategy` entries matching those ISCs
   - `## Decisions` filtered to entries mentioning this feature's ISC IDs (optional)
   - Empty `## Verification` section ready to populate
4. Write to `MEMORY/WORK/{slug}/_ephemeral/<feature>.md`.
5. Add a header comment: `<!-- EPHEMERAL FEATURE FILE — derived from <master-isa-path>. Reconcile via Skill("ISA", "reconcile <this-path> → <master-path>"). Do not hand-edit master from this file. -->`

## Failure modes

- **Tier mismatch:** caller asks for E1 sections but request is clearly E4 work. Surface the mismatch; let the Algorithm decide the correct tier.
- **Missing required section:** CheckCompleteness blocks the return until filled.
- **ISC count under tier floor:** at E2+, the ISC count must meet the soft floor (E2 ≥16, E3 ≥32, E4 ≥128, E5 ≥256). If under, either keep splitting or document the under-decomposition in `## Decisions`.
- **ID collision in ephemeral mode:** if the feature's ISC IDs don't exist in master, abort and surface the inconsistency — this is a master-ISA error, not a Scaffold error.
