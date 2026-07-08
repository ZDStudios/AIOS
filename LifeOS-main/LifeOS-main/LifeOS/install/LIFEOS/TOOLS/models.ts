#!/usr/bin/env bun
/**
 * ============================================================================
 * MODELS — single source of truth for model IDs across LifeOS
 * ============================================================================
 *
 * WHY THIS EXISTS:
 * Model IDs used to be pinned in scattered files. On a new model release the
 * updates were a manual scramble and drifted silently (e.g. ContextAudit
 * checked for claude-opus-4-7 long after claude-opus-4-8 shipped). This file
 * is the one place that knows current IDs. Consumers either:
 *   (a) use a tier ALIAS ("opus"/"sonnet"/"haiku") — auto-resolves to latest,
 *       no registry needed (preferred — see Pulse manifests, Inference.ts), or
 *   (b) import CURRENT[...] from here when they genuinely need a pinned ID
 *       (e.g. a drift-check that must name the expected latest).
 *
 * ON A NEW RELEASE: bump CURRENT below (one edit), then `bun UpdateModels.ts
 * --check` confirms nothing else drifted. The _NEWS Anthropic monitor surfaces
 * a proposal when it detects a new model; application is propose-not-auto.
 *
 * NOT IN SCOPE: cross-vendor pins (Forge gpt-5.5, build+audit modes) track their own
 * vendors — recorded here for inventory, never auto-bumped to Claude.
 * ============================================================================
 */

export type ClaudeTier = "opus" | "sonnet" | "haiku" | "fable";

/**
 * ============================================================================
 * EFFORT LEVELS — the four-level abstraction over the Claude lineup
 * ============================================================================
 *
 * Consumers route by INTENT (max/high/medium/low), never by model name. Two
 * independent edit points keep the system cohesive across model churn:
 *
 *   Layer 1  EFFORT_MODEL  level → tier   edit when the LINEUP changes
 *                                          (a model enters/exits the
 *                                          subscription, or moves rungs)
 *   Layer 2  CURRENT       tier → ID      edit when a VERSION releases
 *
 * Routing policy (Algorithm doctrine): NATIVE delegated work runs at `high`;
 * Algorithm E1–E3 dispatch at `high`; E4/E5 dispatch at `max`. `medium` and
 * `low` exist for utility inference (classification, summarization, vision
 * triage) so cheap calls never silently ride an expensive model. The
 * Advisor is pinned `max` (keystone commitment call); the TheRouter
 * classifier is pinned `high` (Opus, re-pinned off `max` 2026-07-01) — it
 * fires on every prompt, so the per-prompt keystone stays off the top rung.
 */
export type EffortLevel = "max" | "high" | "medium" | "low";

/**
 * Level → tier binding. THIS IS THE SINGLE EDIT POINT on a lineup change.
 * Example: Fable exits the subscription → `max: "opus"` and the entire
 * routing system follows; no other code changes.
 *
 * DECISION (2026-07-01, principal): Fable is re-enabled and IS the top rung.
 * `max: "fable"` — the hardest work (Algorithm E4/E5 + every Core-System
 * Override task) auto-dispatches Fable; `high` stays Opus for E1–E3 + NATIVE.
 * This restores a real ladder to the routing system — Fable → Opus → Sonnet →
 * Haiku — reachable with NO new agent (the dispatch-time `model` param carries
 * the rung; agents are personas, model is orthogonal). Fable is ~2× Opus, so
 * the cost lands only on genuinely hard runs. Two guardrails ship with the flip:
 *   (a) the TheRouter classifier is re-pinned to `high` (Opus), NOT `max`,
 *       so the per-prompt keystone stays fast + cheap — "keystone" never meant
 *       "most-expensive rung"; the classifier's model is UNCHANGED from before
 *       the flip (it was Opus via max=opus; it's Opus via high now).
 *   (b) the Advisor stays at `max` (now Fable) — a once-per-deliverable
 *       commitment call, where best judgment is worth the cost.
 * `max` and `high` are now DISTINCT models, so the Inference.ts max-fallback
 * degrades max→high = fable→opus: a genuinely real degraded path.
 *
 * SUPERSEDES the 2026-06-30 decision ("Opus stays top, Fable no longer the
 * intended top model"). That call held while Fable was unavailable; Fable is
 * reachable again (probed 2026-07-01: `claude --model fable` → clean completion)
 * and the principal's directive is that the hardest work should ride it. The
 * prior decision is preserved here in history, not tombstoned.
 */
export const EFFORT_MODEL: Record<EffortLevel, ClaudeTier> = {
  max: "fable",   // top rung — E4/E5 + Core-System Override dispatch here (~2× Opus, hard work only)
  high: "opus",   // E1–E3 + NATIVE + the re-pinned TheRouter classifier
  medium: "sonnet",
  low: "haiku",
};

/**
 * ============================================================================
 * THE THREE LEVEL AXES — don't conflate them (2026-06-29)
 * ============================================================================
 * LifeOS has three independent "level" dials. They share words ("max", "high")
 * but they are NOT one axis. The statusline shows two of them; this file is the
 * source of truth for the mapping between the first two.
 *
 *   1. MODEL RUNG       EFFORT_MODEL above — which Claude model an agent runs.
 *                       Exactly four, because the lineup has four models
 *                       (fable/opus/sonnet/haiku): max | high | medium | low.
 *
 *   2. REASONING EFFORT HarnessEffort — how hard a model thinks WITHIN itself
 *                       (Claude Code's `--effort` / `/effort` knob). Five:
 *                       low | medium | high | xhigh | max. This is the LEVEL the
 *                       statusline reads from `effort.level`. Claude-Code-owned:
 *                       a UserPromptSubmit hook can read it but CANNOT set the main
 *                       loop's value (hooks doc "Important Limitations") — it's
 *                       `/effort` / settings `effortLevel` / `--effort` /
 *                       `CLAUDE_CODE_EFFORT_LEVEL` only, and the persistent field
 *                       caps at `xhigh` (`max` is `/effort max` interactive-only).
 *                       Only dispatched agents carry a programmable effort
 *                       (Algorithm v6.19.0 § tier table). Because the tier can't
 *                       auto-apply its target, the statusline SURFACES the gap:
 *                       when live effort is below the active Algorithm tier's
 *                       target (E1 low · E2 medium · E3 high · E4 xhigh · E5 xhigh
 *                       — xhigh not max at E5: the nudge only points at a settable
 *                       level; `max` is `/effort max` interactive-only),
 *                       it renders an amber `↑<TARGET>` nudge — the un-settable
 *                       dial made visible, one `/effort` to close it. See
 *                       LIFEOS_StatusLine.sh § "Effort↔tier nudge" (2026-06-29).
 *
 *   3. COMPOSITION      ultracode — whether to fan a task into a multi-agent
 *                       Workflow. NOT an effort level: it rides on xhigh effort
 *                       and is detected via output-style, not `effort.level`
 *                       (LIFEOS_StatusLine.sh promotes XHIGH→ULT). It belongs to
 *                       no rung; it is orthogonal to axes 1 and 2.
 *
 * The crossover that trips people up: dispatching at MODEL RUNG `max` emits
 * REASONING EFFORT `xhigh`, NOT `max` (see LEVEL_TO_HARNESS_EFFORT). "Max model"
 * and "max thinking" are different dials that share a word. LifeOS dispatch
 * deliberately caps reasoning at `xhigh`; harness effort `max` is reachable by a
 * human via `/effort max` but no LifeOS level emits it.
 */

/** Axis 2: the harness reasoning-effort knob (Claude Code `--effort`). */
export type HarnessEffort = "low" | "medium" | "high" | "xhigh" | "max";

/**
 * MODEL RUNG → REASONING EFFORT emitted when LifeOS dispatches at that rung.
 * Single source of truth for the crossover (consumed by Inference.ts). Note
 * `max → xhigh`, by design: LifeOS dispatch caps reasoning effort at xhigh.
 */
export const LEVEL_TO_HARNESS_EFFORT: Record<EffortLevel, HarnessEffort> = {
  max: "xhigh",
  high: "high",
  medium: "medium",
  low: "low",
};

/** Auto-tracking alias for an effort level (preferred — never drifts). */
export function modelForEffort(level: EffortLevel): string {
  return ALIAS[EFFORT_MODEL[level]];
}

/** Current pinned ID for an effort level (when an exact ID is required). */
export function pinnedModelForEffort(level: EffortLevel): string {
  return CURRENT[EFFORT_MODEL[level]];
}

/**
 * Current Claude model IDs. THIS IS THE SINGLE EDIT POINT on a model release.
 * Verify the exact string against the models overview / migration guide before
 * bumping. `bun UpdateModels.ts --apply <tier> <id>` rewrites these safely.
 */
export const CURRENT: Record<ClaudeTier, string> = {
  fable: "claude-fable-5",
  opus: "claude-opus-4-8",
  sonnet: "claude-sonnet-5",
  haiku: "claude-haiku-4-5-20251001",
};

/**
 * Tier aliases. The `claude` CLI and spawnClaude resolve these to the latest
 * model in the tier automatically. Prefer these in consumers that accept a
 * string and don't need a pinned ID — they never drift.
 */
export const ALIAS: Record<ClaudeTier, string> = {
  fable: "fable",
  opus: "opus",
  sonnet: "sonnet",
  haiku: "haiku",
};

/**
 * Cross-vendor pins — inventory only. These track their own vendors' cadence
 * and are NEVER auto-bumped to a Claude model. Recorded so the updater's drift
 * scan can distinguish intentional non-Claude pins from stale Claude pins.
 */
export const CROSS_VENDOR: Record<string, string> = {
  forge: "gpt-5.5",  // OpenAI (Tier-2 egress); covers build + audit modes (Cato folded in 2026-06-17)
  codexResearcher: "gpt-5.5",  // OpenAI (Tier-2 egress)
  gene: "z-ai/glm-5.2",  // OpenRouter broker (Tier-2, most opaque); GLM 5.2 via OpenRouter.ts; default-pinned US+ZDR (Fireworks) => INTERNAL ceiling, unpinned => PUBLIC
};

/**
 * ============================================================================
 * DATA CLASSIFICATION × INFERENCE-SOURCE ROUTING (LifeOS doctrine 2026-06-18)
 * ============================================================================
 * Machine-readable form of LIFEOS/DOCUMENTATION/Security/DataClassification.md.
 * hooks/lib/egress-class-core.ts (consumed by hooks/EgressClassGuard.hook.ts)
 * reads these — a policy change is a table edit, never code. Fail-closed.
 *
 * The ceiling is per-ROUTE (source + model + residency). Three rules, most-
 * restrictive wins:
 *   1. RESTRICTED-capable vendors: Anthropic (NATIVE) + OpenAI (FORGE) ONLY.
 *   2. Chinese-origin MODEL (GLM/Z.ai, Kimi/Moonshot, MiniMax, Qwen, DeepSeek)
 *      => INTERNAL ceiling; opaque broker w/o residency guarantee => PUBLIC.
 *   3. US/allied model, US inference, US company, no CN/RU egress => CONFIDENTIAL.
 *   Else => PUBLIC. LOCAL (on-device) => everything.
 */
export type DataClass = "RESTRICTED" | "CONFIDENTIAL" | "INTERNAL" | "PUBLIC";
export type InferenceSource = "LOCAL" | "NATIVE" | "FORGE" | "GENE";

/** Egress trust tier per source (0 = on-device / highest trust). */
export const SOURCE_TIER: Record<InferenceSource, number> = {
  LOCAL: 0, NATIVE: 1, FORGE: 2, GENE: 2,
};

/** Vendors cleared for RESTRICTED ({{PRINCIPAL_NAME}}'s directive: Anthropic + OpenAI only). */
export const RESTRICTED_CAPABLE_VENDORS = ["anthropic", "openai"] as const;

/** Chinese-origin model families — capped at INTERNAL by rule 2. */
export const CHINESE_MODEL_PATTERNS: RegExp[] = [/glm/i, /z-?ai/i, /kimi/i, /moonshot/i, /minimax/i, /qwen/i, /deepseek/i];
export function isChineseModel(model: string): boolean {
  return CHINESE_MODEL_PATTERNS.some((re) => re.test(model));
}

/** Sensitivity ordinal — lower = more sensitive. */
export const CLASS_RANK: Record<DataClass, number> = { RESTRICTED: 0, CONFIDENTIAL: 1, INTERNAL: 2, PUBLIC: 3 };

export interface InferenceRoute {
  source: InferenceSource;
  vendor: string;                 // 'anthropic' | 'openai' | 'cerebras' | 'openrouter' | 'local'
  model: string;
  inferenceCountry?: string;      // best-known inference location, e.g. 'US'
  companyCountry?: string;        // vendor HQ country
  residencyGuaranteed?: boolean;  // true ONLY if pinned to a US provider with no China/Russia egress path
}

/** The maximum (most-sensitive) data class a route may process. */
export function maxClassForRoute(r: InferenceRoute): DataClass {
  if (r.source === "LOCAL") return "RESTRICTED";
  if ((RESTRICTED_CAPABLE_VENDORS as readonly string[]).includes(r.vendor)) return "RESTRICTED";
  if (isChineseModel(r.model)) return r.residencyGuaranteed ? "INTERNAL" : "PUBLIC";
  if (r.inferenceCountry === "US" && r.companyCountry === "US" && r.residencyGuaranteed) return "CONFIDENTIAL";
  return "PUBLIC";
}

/** True if a route may process `dataClass` (data at or below the route's ceiling). */
export function isRouteAllowed(r: InferenceRoute, dataClass: DataClass): boolean {
  return CLASS_RANK[dataClass] >= CLASS_RANK[maxClassForRoute(r)];
}

/** Canonical routes for the wired sources. GENE needs a US pin for INTERNAL. */
export const ROUTES: Record<string, InferenceRoute> = {
  NATIVE:           { source: "NATIVE",   vendor: "anthropic",  model: "claude",        inferenceCountry: "US", companyCountry: "US", residencyGuaranteed: true },
  FORGE:            { source: "FORGE",    vendor: "openai",     model: "gpt-5.5",       inferenceCountry: "US", companyCountry: "US", residencyGuaranteed: true },
  GENE_PINNED_US:   { source: "GENE",     vendor: "openrouter", model: "z-ai/glm-5.2",  inferenceCountry: "US", companyCountry: "US", residencyGuaranteed: true },  // pinned US+ZDR (default: Fireworks; allowlist in egress-class-core US_ZDR_PROVIDERS); Chinese => INTERNAL
  GENE_UNPINNED:    { source: "GENE",     vendor: "openrouter", model: "z-ai/glm-5.2",  residencyGuaranteed: false },                                                // broker, no guarantee => PUBLIC
};

/** Current pinned ID for a Claude tier. */
export function currentModel(tier: ClaudeTier): string {
  return CURRENT[tier];
}

/** Auto-tracking alias for a Claude tier. */
export function alias(tier: ClaudeTier): string {
  return ALIAS[tier];
}

/** Every current Claude ID, for drift scanning. */
export function allCurrentClaudeIds(): string[] {
  return Object.values(CURRENT);
}

/**
 * Dated/pinned Claude-ID pattern. Matches claude-{tier}-{major}[-{minor}][-date]
 * (the Claude 5 lineup dropped the minor version, e.g. "claude-sonnet-5") and
 * claude-{tier}-{major}-{minor}[-date] (older two-part IDs like "claude-opus-4-8").
 * Used by the drift scanner to find pinned IDs that may be stale.
 */
export const CLAUDE_ID_PATTERN = /claude-(opus|sonnet|haiku|fable)-\d+(?:-\d+)?(?:-\d{8})?/g;

/** True if `id` is a known-current Claude ID. */
export function isCurrent(id: string): boolean {
  return allCurrentClaudeIds().includes(id);
}
