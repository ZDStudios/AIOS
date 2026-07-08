# CheckCompleteness Workflow

Score an existing ISA against the tier completeness gate and return a structured pass/fail + gap report. Drives the hard tier gate at all tiers.

## When to invoke

- Algorithm at end of OBSERVE: confirm the scaffolded ISA meets tier requirements.
- Algorithm at start of VERIFY: confirm the ISA is still complete after any structural changes.
- User directly: `Skill("ISA", "check completeness of <isa-path> at tier <tier>")`
- Internal call from Scaffold or Interview workflows.

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| isa_path | yes | Path to the ISA to score |
| tier | yes | The completeness bar to score against (E1 / E2 / E3 / E4 / E5) |
| strict | no | Default true. If false, downgrade hard fails to soft warnings. |

## Output

```yaml
status: pass | fail
tier: E4
required_sections:
  Problem: present
  Vision: present
  Out of Scope: missing
  Principles: thin       # ≤ 1 sentence
  Constraints: present
  Goal: present
  Criteria: present
  Test Strategy: present
  Features: present
  Decisions: present
  Changelog: missing
  Verification: empty    # acceptable until VERIFY phase
gaps:
  - section: Out of Scope
    severity: hard
    reason: required at E4, missing entirely
  - section: Principles
    severity: hard
    reason: thin — only one bullet
  - section: Changelog
    severity: hard
    reason: required at E4, missing entirely
isc_quality:
  total: 24
  tier_floor: 128
  under_floor: true
  granularity_violations: 0
  anti_criteria_count: 2
  antecedent_present: true
  id_stability_violations: 0
```

## Procedure

### Step 1 — Voice notification

```bash
curl -s -X POST http://localhost:31337/notify \
  -H "Content-Type: application/json" \
  -d '{"message": "Running the CheckCompleteness workflow in the ISA skill"}' \
  > /dev/null 2>&1 &
```

### Step 2 — Read the ISA

Load `isa_path`. Parse frontmatter and section headers.

### Step 3 — Look up tier requirements

| Tier | Required Sections |
|------|-------------------|
| E1 | Goal, Criteria |
| E2 | Problem, Goal, Criteria, Test Strategy |
| E3 | Problem, Vision, Out of Scope, Constraints, Goal, Criteria, Features, Test Strategy |
| E4 | All twelve sections |
| E5 | All twelve sections + Interview workflow ran before BUILD |

Project ISA (`<project>/ISA.md`) — bump tier to max(declared-tier, E3).

### Step 4 — Classify each required section

For each required section:

| Classification | Test |
|----------------|------|
| `present` | Section header exists and body is ≥ 2 sentences (or ≥ 3 bullets) |
| `thin` | Section header exists but body is ≤ 1 sentence (or ≤ 2 bullets) |
| `missing` | Section header doesn't exist |
| `empty` | Section header exists, body is whitespace only — only acceptable for `Verification` before VERIFY phase |

### Step 5 — Audit ISC quality

Walk every ISC in `## Criteria`:

- **Granularity** — every ISC names a single binary tool probe (or has one inferable from its phrasing). Compound "and/with" criteria fail.
- **Tier floor** — at E2+, total ISC count meets the floor (E2 ≥16, E3 ≥32, E4 ≥128, E5 ≥256). Soft fail if under.
- **Anti-criteria** — at least one ISC has the `Anti:` prefix.
- **Antecedent** — when the goal is experiential, at least one ISC has the `Antecedent:` prefix.
- **ID stability** — every ISC has a unique sequential ID. No collisions, no gaps from renumbering. Tombstones (e.g., `ISC-7: [DROPPED — see Decisions 2026-04-15]`) are valid.
- **Anchoring (NEW v6.4.0)** — when frontmatter `principal_stated_goal:` is set, every ISC must have an `anchors_to` value in Test Strategy (either `literal` or `derived: <sub-claim>`). Orphan ISCs (no traceable anchor) are a hard failure.

### Step 5a — Goal-Signal Mismatch Check (NEW v6.4.0)

**Backwards-compat guard:** this check fires ONLY when the ISA frontmatter explicitly contains a `principal_stated_goal` key (any value, including empty string or `null`). ISAs scaffolded under Algorithm v6.3.0 and earlier — which never carry this key — are not subject to the check. The presence of the key is the v6.4.0+ marker.

If invoked during OBSERVE-end or VERIFY AND the ISA is v6.4.0+ scaffolded:

- If session additionalContext contains `GOAL_SIGNAL: <1|2|3|4>` (non-`none`) AND `principal_stated_goal:` in ISA frontmatter is empty/null → hard failure: "literal capture missed — classifier detected goal-signal but Scaffold did not preserve."
- If `principal_stated_goal:` is set to a non-null string but the string is < 6 tokens or fails the minimum-content rule → hard failure: "literal violates minimum-content rule — should have been `null`."

### Step 5b — Artifact-Presence Check (NEW v6.4.0 — Cato 2026-05-11 lesson)

**Backwards-compat guard:** this check fires ONLY when the ISA frontmatter explicitly contains a `principal_stated_goal` key (any value). v6.3.0-era ISAs without the key are not subject to the check, preserving their existing close path.

At E4+ AND v6.4.0+ scaffolded, for every ISC marked `[x]` in `## Criteria` that claims a named design surface (e.g., "the proposal includes X", "the design names Y", "a table appears"), scan the ISA body for that surface textually:

- If the surface is asserted complete by an `[x]` but no textual evidence appears in the ISA body → hard failure: "ISC claims surface that does not exist in artifact (system-of-record violation)."
- The ISA artifact must contain its own design surface, not reference ephemeral chat context. The system-of-record identity (one of the five) requires this.

### Step 5c — Density Gate Acknowledged Check (NEW v6.5.0)

**Backwards-compat guard:** this check fires ONLY when the ISA frontmatter explicitly contains the `density_score` key (any value, including `null` or empty string — **presence**, not truthiness). v6.4.0-era ISAs and earlier — which never carry this key — are not subject to the check. Key-presence IS the version marker, mirroring the v6.4.0 `principal_stated_goal` pattern. Implementation note: parsers must check `'density_score' in frontmatter` (or YAML key-set membership), NOT `frontmatter.density_score !== undefined && frontmatter.density_score !== null` — the latter would spuriously skip the check when a user authors an ISA with `density_score:` and no value.

At E3+ AND v6.5.0+ scaffolded:

- If `interview_invoked` is missing or `density_gate_acknowledged` is missing → hard failure: "v6.5.0 ISA lacks density-gate acknowledgment (Stage 2 of OBSERVE preflight was never recorded)."
- If `divergence_risk: high` AND no Decisions row mentions `density gate fired` or `proceed override` → hard failure: "high divergence risk asserted but no audit trail in Decisions."
- If `interview_invoked: true` AND `density_score` is not a number in `[0, 1]` → hard failure: "density_score out of range."

This gate is the self-enforcing arm of v6.5.0: every future E3+ ISA carries the audit trail of its OBSERVE density decision, or fails the completeness gate.

### Step 6 — Compose the report

Emit the structured YAML output above. Set `status: pass` only when zero hard severity gaps. `strict: false` downgrades hard severity to warnings (used during interview when the user is mid-stream).

### Step 7 — Block phase: complete on hard gaps

When invoked from VERIFY-phase doctrine, hard gaps block the `phase: complete` transition. The Algorithm must fill the gaps before declaring done.

## Severity table

| Gap | Severity at E1 | E2 | E3 | E4 | E5 |
|-----|----------------|----|----|----|----|
| Goal missing | hard | hard | hard | hard | hard |
| Criteria missing | hard | hard | hard | hard | hard |
| Problem missing | — | hard | hard | hard | hard |
| Test Strategy missing | — | hard | hard | hard | hard |
| Vision missing | — | — | hard | hard | hard |
| Out of Scope missing | — | — | hard | hard | hard |
| Constraints missing | — | — | hard | hard | hard |
| Features missing | — | — | hard | hard | hard |
| Principles missing | — | — | — | hard | hard |
| Decisions missing | — | — | — | hard | hard |
| Changelog missing | — | — | — | hard | hard |
| Interview not run pre-BUILD | — | — | — | — | hard |
| Anti-criteria count = 0 | hard | hard | hard | hard | hard |
| Antecedent missing (experiential) | hard | hard | hard | hard | hard |
| ID-stability violation | hard | hard | hard | hard | hard |
| ISC count under tier floor | — | soft | soft | soft | soft |
| Granularity violation | hard | hard | hard | hard | hard |
| Anchoring violation (orphan ISC, v6.4.0+ ISAs only) | hard | hard | hard | hard | hard |
| Goal-signal mismatch (classifier vs ISA, v6.4.0+ ISAs only) | hard | hard | hard | hard | hard |
| Artifact-presence violation (v6.4.0+ ISAs only, E4+) | — | — | — | hard | hard |
| Density-gate not acknowledged (v6.5.0+ ISAs only, E3+) | — | — | hard | hard | hard |
| `divergence_risk: high` without Decisions audit-trail (v6.5.0+ ISAs only) | — | — | hard | hard | hard |
| `density_score` out of `[0, 1]` (v6.5.0+ ISAs only) | — | — | hard | hard | hard |
| `context_sufficient` missing on v6.7.0+ ISAs at all ALGORITHM tiers (E1 reads true/null only when Density Gate skipped via `proceed`) | hard | hard | hard | hard | hard |
| `context_checks_fired` empty array on v6.7.0+ ISAs when ALGORITHM phase reached PLAN | — | — | hard | hard | hard |
| PLAN-refresh flag set (`plan-refresh` in `context_checks_fired` + `divergence_risk: medium`) — soft-gate teeth contract per v6.7.0 (currently SHOULD; CheckCompleteness cannot inspect phase-output text — re-open as MUST when a phase-output gate hook lands) | — | — | — | — | — |

## Failure modes

- **Frontmatter missing or malformed:** abort with explicit error. The frontmatter is non-negotiable.
- **Project ISA scored at task tier:** override to max(tier, E3). Report the override in the output.
- **ISC body parsing fails:** treat as zero ISCs and surface the parse error.
