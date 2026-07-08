#!/usr/bin/env bun
/**
 * TheRouter — UserPromptSubmit hook that owns mode/tier classification.
 *
 * Three-stage cascade:
 *   A. Deterministic fast-paths (0ms): /eN, ratings, praise, system-text, short, hard triggers.
 *   B. 60s decision cache: SHA-256 hash of normalized prompt → reuse prior decision.
 *   C. Opus-level ('high') classifier: rich LifeOS / Algorithm / capability / time-pressure prompt.
 *
 * Fail-safe: tier-aware (≥1500 → E4, ≥400 → E3, else NATIVE). Under-escalation is the
 * failure mode this system was built to prevent (Algorithm v6.3.0 line 97).
 *
 * PromptProcessing.hook.ts retains tab-title + session-naming via Haiku and runs after
 * this hook in settings.json. Mode/tier classification lives ONLY here.
 */

import { appendFileSync, existsSync, readFileSync, writeFileSync, renameSync } from 'fs';
import { createHash } from 'crypto';
import { inference } from '../LIFEOS/TOOLS/Inference';
import { paiPath } from './lib/paths';
import { markAlgorithmStarting, markSessionNative } from './lib/isa-utils';
import { setModeToken } from './lib/tab-setter';

// ── Types ──

interface HookInput {
  session_id: string;
  prompt?: string;
  user_prompt?: string;
  transcript_path?: string;
  hook_event_name?: string;
}

type Mode = 'MINIMAL' | 'NATIVE' | 'ALGORITHM';
type Source = 'classifier' | 'fail-safe' | 'fast-path' | 'cache' | 'explicit';
type GoalSignal = 1 | 2 | 3 | 4 | null;

interface Decision {
  mode: Mode;
  tier: number | null;
  reason: string;
  source: Source;
  goalSignal?: GoalSignal;
  goalLiteral?: string;
  interviewEligible?: boolean;
}

interface CacheEntry {
  hash: string;
  mode: Mode;
  tier: number | null;
  reason: string;
  ts: number;
}

interface CacheFile {
  entries: CacheEntry[];
}

interface ClassifierJSON {
  mode?: string;
  tier?: number | null;
  reason?: string;
  confidence?: number;
}

// ── Constants ──

const MIN_PROMPT_LENGTH = 3;
const CLASSIFIER_TIMEOUT_MS = 30000; // classifier runs at level 'high' (Opus, re-pinned 2026-07-01 — max is now Fable, and firing Fable on every prompt is a needless 2× cost + latency hit). Single ≤30s Opus attempt under the TheRouter hook ceiling (settings.json timeout: 50s); on timeout/parse-fail it degrades via failsafeDecision(). The classifier's model is UNCHANGED by the re-pin (was Opus via max=opus; is Opus via high now).
const STDIN_TIMEOUT_MS = 5000;
const CACHE_TTL_MS = 60_000;
const CACHE_MAX_ENTRIES = 50;
const CACHE_PATH = paiPath('MEMORY', 'STATE', 'effort-router-cache.json');
const TELEMETRY_PATH = paiPath('MEMORY', 'OBSERVABILITY', 'effort-router.jsonl');

// ── Stdin ──

async function readStdinWithTimeout(timeout: number = STDIN_TIMEOUT_MS): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    const timer = setTimeout(() => resolve(data), timeout);
    process.stdin.on('data', (chunk) => { data += chunk.toString(); });
    process.stdin.on('end', () => { clearTimeout(timer); resolve(data); });
    process.stdin.on('error', (err) => { clearTimeout(timer); reject(err); });
  });
}

// ── Output ──

function emit(decision: Decision): void {
  const modeLine = (decision.mode === 'ALGORITHM' && decision.tier !== null)
    ? `MODE: ALGORITHM | TIER: E${decision.tier} | REASON: ${decision.reason} | SOURCE: ${decision.source}`
    : `MODE: ${decision.mode} | REASON: ${decision.reason} | SOURCE: ${decision.source}`;
  // v6.4.0: principal-stated goal handshake. Scaffold trusts as hint, re-validates.
  const goalSignalLine = decision.goalSignal !== undefined && decision.goalSignal !== null
    ? `GOAL_SIGNAL: ${decision.goalSignal}`
    : 'GOAL_SIGNAL: none';
  const goalLiteralLine = decision.goalLiteral
    ? `GOAL_LITERAL: ${JSON.stringify(decision.goalLiteral)}`
    : '';
  // v6.5.0: stage-1 eligibility for the density × tier gate. true iff ALGORITHM at tier ≥ E3;
  // Scaffold preflight computes stage-2 density score against the actual ISA sections.
  const eligibilityLine = decision.interviewEligible !== undefined
    ? `INTERVIEW_ELIGIBLE: ${decision.interviewEligible}`
    : '';
  const lines = [modeLine, goalSignalLine, goalLiteralLine, eligibilityLine].filter(Boolean).join('\n');
  console.log(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: lines },
  }));
}

function appendTelemetry(entry: Record<string, unknown>): void {
  try {
    const serialized = JSON.stringify(entry);
    if (serialized.includes('\n')) return;
    appendFileSync(TELEMETRY_PATH, `${serialized}\n`, 'utf-8');
  } catch {}
}

// ── Fast-path detectors (ported verbatim from PromptProcessing) ──

function isExplicitRating(prompt: string): boolean {
  const trimmed = prompt.trim();
  const match = trimmed.match(/^(10|[1-9])(?:\s*[-:]\s*|\s+)?(.*)$/);
  if (!match) return false;
  const afterNumber = trimmed.slice(match[1].length);
  if (afterNumber.length > 0 && /^[/.\dA-Za-z]/.test(afterNumber)) return false;
  const rest = match[2]?.trim();
  if (rest) {
    const sentenceStarters = /^(items?|things?|steps?|files?|lines?|bugs?|issues?|errors?|times?|minutes?|hours?|days?|seconds?|percent|%|th\b|st\b|nd\b|rd\b|of\b|in\b|at\b|to\b|the\b|a\b|an\b)/i;
    if (sentenceStarters.test(rest)) return false;
  }
  return true;
}

const POSITIVE_PRAISE_WORDS = new Set([
  'excellent', 'amazing', 'brilliant', 'fantastic', 'wonderful', 'beautiful',
  'incredible', 'awesome', 'perfect', 'great', 'nice', 'superb', 'outstanding',
  'magnificent', 'stellar', 'phenomenal', 'remarkable', 'terrific', 'splendid',
  'ok', 'okay', 'thanks', 'thank', 'cool', 'good', 'yes', 'yep', 'yeah', 'sure',
]);
const POSITIVE_PHRASES = new Set([
  'great job', 'good job', 'nice work', 'well done', 'nice job', 'good work',
  'love it', 'nailed it', 'looks great', 'looks good', 'thats great', 'that works',
  'sounds good', 'works for me', 'thank you', 'got it',
]);

const SYSTEM_TEXT_PATTERNS = [
  /^<task-notification>/i,
  /^<system-reminder>/i,
  /^This session is being continued from a previous conversation/i,
  /^Please continue the conversation/i,
  /^Note:.*was read before/i,
];

const HARD_ALGORITHM_PHRASES: Array<{ pattern: RegExp; tier: 3 | 4 | 5; reason: string }> = [
  { pattern: /\bmaster plan\b/i, tier: 4, reason: "explicit 'master plan' request — ideal state requires ISC" },
  { pattern: /\bfundament(?:ally|al)\s+(?:rethink|redesign|rebuild|re-?architect|re-?evaluat)/i, tier: 4, reason: "fundamental rethink/redesign — spec emerges through ISC" },
  { pattern: /\b(?:comprehensively|completely|entirely)\s+(?:rewrit\w*|rebuild|redesign|re-?architect|overhaul)/i, tier: 4, reason: "comprehensive rewrite/rebuild — cross-cutting design" },
  { pattern: /\b(?:redesign|rebuild|re-?architect|reconstruct)\s+(?:from\s+scratch|the\s+(?:entire|whole)|all\s+of)/i, tier: 4, reason: "from-scratch redesign — no pre-articulated spec" },
  { pattern: /\b(?:design|build|create)\s+(?:a\s+new|the\s+entire)\s+(?:system|architecture|subsystem|framework|infrastructure)/i, tier: 4, reason: "designing new system — ideal state needs ISC" },
  { pattern: /\b(?:audit|overhaul|rewrite|redesign)\s+(?:the\s+)?(?:algorithm|system\s+prompt|hooks?|doctrine|architecture|classifier|routing)/i, tier: 4, reason: "doctrine/architecture change — spec emerges from audit" },
  { pattern: /\bfrom\s+(?:first\s+principles|the\s+ground\s+up|scratch)\b/i, tier: 4, reason: "ground-up build — emergent spec" },
  { pattern: /\bwe\s+need\s+to\s+(?:fundamentally\s+)?rethink\b/i, tier: 4, reason: "rethink request — spec needs to emerge" },
  { pattern: /\bcome\s+up\s+with\s+(?:a|the)\s+(?:master\s+|comprehensive\s+)?plan\s+for\b/i, tier: 3, reason: "asks for plan creation on a named subject — spec doesn't exist yet" },
  { pattern: /\b(?:thoroughly|comprehensively|deeply)\s+(?:fucking\s+)?(?:analyze|investigate|audit)\s+.{0,40}\b(?:and|then|to)\s+(?:fix|rewrite|rebuild|overhaul|redesign)/i, tier: 4, reason: "deep-analyze-then-rewrite — multi-stage emergent spec" },
];

function hardAlgorithmTrigger(prompt: string): { tier: 3 | 4 | 5; reason: string } | null {
  for (const t of HARD_ALGORITHM_PHRASES) {
    if (t.pattern.test(prompt)) return { tier: t.tier, reason: t.reason };
  }
  return null;
}

const EXPLICIT_TIER_RE = /\/e([1-5])\b/i;

function explicitTierOverride(prompt: string): number | null {
  const m = prompt.match(EXPLICIT_TIER_RE);
  return m ? parseInt(m[1], 10) : null;
}

// ── v6.4.0: principal-stated goal four-signal detector ──
// Scaffold workflow trusts this as a hint and re-validates. See Algorithm v6.4.0 doctrine.

const GOAL_SIGNAL_PATTERNS: Array<{ signal: 1 | 2 | 3 | 4; pattern: RegExp }> = [
  // Signal 1: named metric + threshold (quantitative target)
  { signal: 1, pattern: /\b(p\d{1,2}|p99|p95|p90|latency|throughput|rate|count|subscribers?|users?|revenue|mrr|arr|cpu|memory|bundle|score|nps|csat)\b[^.!?\n]{0,80}\b(under|above|below|over|≤|≥|<|>|<=|>=|reach(?:es|ing)?|hit|exceed|less\s+than|more\s+than|at\s+least|at\s+most)\b[^.!?\n]{0,40}\b\d/i },
  { signal: 1, pattern: /\b(get|push|drive|reach|hit|grow|cut|reduce|increase)\b[^.!?\n]{0,40}\bto\s+\d/i },
  // Signal 2: explicit outcome assertion
  { signal: 2, pattern: /\b(i\s+want|i\s+need|let'?s\s+(?:go|do|ship|build|make)|achieve|accomplish|complete)\b/i },
  { signal: 2, pattern: /\b(yes,?\s+(?:let'?s|go\s+ahead|do\s+(?:this|it))|go\s+ahead\s+and\s+do)\b/i },
  // Signal 3: completion condition
  { signal: 3, pattern: /\b(until|such\s+that|so\s+that)\s+(?:all\s+)?\w+/i },
  { signal: 3, pattern: /\b(don'?t\s+stop|keep\s+going)\s+until\b/i },
  // Signal 4: structural/design directive (verb-object on the system)
  { signal: 4, pattern: /\b(design|build|create|absorb|replace|eliminate|unify|consolidate|merge|split|refactor|redesign|reorganize|restructure)\s+(?:how|the|a|an)?\s*\w+/i },
];

const NONSPECIFIC_PHRASES = new Set([
  'make it good', 'do better', 'refactor this', 'fix this', 'make it nice',
  'help me', 'try again', 'do it', 'do that', 'go ahead',
]);

function detectGoalSignal(prompt: string): { signal: GoalSignal; literal: string | null } {
  const trimmed = prompt.trim();
  if (!trimmed) return { signal: null, literal: null };

  // Try each signal pattern. First match wins.
  for (const { signal, pattern } of GOAL_SIGNAL_PATTERNS) {
    const m = trimmed.match(pattern);
    if (!m) continue;

    // Extract the candidate literal — the sentence containing the match.
    const sentences = trimmed.split(/(?<=[.!?])\s+/);
    const matchIdx = trimmed.indexOf(m[0]);
    let charCount = 0;
    let candidate = trimmed;
    for (const s of sentences) {
      if (charCount + s.length >= matchIdx) { candidate = s.trim(); break; }
      charCount += s.length + 1;
    }

    // Fail-closed minimum-content rule: < 6 tokens OR nonspecific phrase → null literal.
    const tokens = candidate.split(/\s+/).filter(t => t.length > 0);
    const normalized = candidate.toLowerCase().replace(/[.!?,]/g, '').trim();
    if (tokens.length < 6 || NONSPECIFIC_PHRASES.has(normalized)) {
      return { signal: null, literal: null };
    }

    return { signal, literal: candidate.slice(0, 400) };
  }

  return { signal: null, literal: null };
}

// ── Cache ──

function normalize(prompt: string): string {
  return prompt.replace(/\s+/g, ' ').trim().toLowerCase();
}

function hashPrompt(prompt: string): string {
  return createHash('sha256').update(normalize(prompt)).digest('hex');
}

function readCache(): CacheFile {
  try {
    if (!existsSync(CACHE_PATH)) return { entries: [] };
    const parsed = JSON.parse(readFileSync(CACHE_PATH, 'utf-8'));
    if (parsed && Array.isArray(parsed.entries)) return parsed as CacheFile;
    return { entries: [] };
  } catch {
    return { entries: [] };
  }
}

function writeCacheAtomic(cache: CacheFile): void {
  try {
    const tmp = `${CACHE_PATH}.tmp.${process.pid}`;
    writeFileSync(tmp, JSON.stringify(cache), 'utf-8');
    renameSync(tmp, CACHE_PATH);
  } catch {}
}

function checkCache(prompt: string): Decision | null {
  const cache = readCache();
  const hash = hashPrompt(prompt);
  const now = Date.now();
  const hit = cache.entries.find(e => e.hash === hash && (now - e.ts) <= CACHE_TTL_MS);
  if (!hit) return null;
  return { mode: hit.mode, tier: hit.tier, reason: hit.reason, source: 'cache' };
}

function storeCache(prompt: string, decision: Decision): void {
  if (decision.source === 'fail-safe') return;
  const cache = readCache();
  const hash = hashPrompt(prompt);
  cache.entries = cache.entries.filter(e => e.hash !== hash);
  cache.entries.push({ hash, mode: decision.mode, tier: decision.tier, reason: decision.reason, ts: Date.now() });
  cache.entries.sort((a, b) => b.ts - a.ts);
  if (cache.entries.length > CACHE_MAX_ENTRIES) {
    cache.entries = cache.entries.slice(0, CACHE_MAX_ENTRIES);
  }
  writeCacheAtomic(cache);
}

// ── Smart classifier prompt ──

function buildClassifierSystemPrompt(): string {
  return `You are the TheRouter for LifeOS, the LifeOS (Life Operating System) running on Claude Code. Every prompt is classified into one of three response modes — MINIMAL, NATIVE, or ALGORITHM — plus an effort tier when ALGORITHM is selected.

LifeOS is the Life Operating System — scaffolding that makes AI dependable. Every task is current state → ideal state, articulated as ISC (hard-to-vary criteria), pursued through verifiable iteration. The router preserves dynamic range: fast on simple work, deep on hard work, sharp variation between them.

## The discriminator rule

The boundary between NATIVE and ALGORITHM is NOT complexity, file count, or step count. It is whether the **ideal state is pre-articulable in one line**.

- NATIVE = ideal state pre-articulable in one line. Destination is clear. Execution may still involve multiple tools, skills, files, or parallel agents — but the spec exists before the work starts.
- ALGORITHM = ideal state requires ISC to articulate. Building, designing, integrating, or changing doctrine where "done" is not pre-legible. The seven phases are the mechanism for articulating what couldn't be stated up front.

**A short, clearly-stated QUESTION does not mean the ANSWER's ideal state is pre-articulable. This is the #1 misroute — but the fix cuts BOTH ways, so hold all three buckets at once. Route by the ANSWER, never the question's length.**

- **Lookup answer → NATIVE.** Facts to retrieve and assemble. "What time is it", "differences between BPE and WordPiece".
- **Opinion / advice / personal-judgment answer → NATIVE (with depth).** "Should I learn Rust or Go", "what do you think of X", "why do I keep procrastinating", "is remote work worth it". The answer is a reasoned take the reader can weigh at a glance. Synthesis of personal judgment is STILL NATIVE — do NOT escalate these. Almost every question involves *some* synthesis; "needs synthesis" is therefore NOT the discriminator.
- **Answer must be built by analytical synthesis against a body of external / contested / technical evidence → ALGORITHM.** A hard science / philosophy / technical / strategy question where a good answer must marshal evidence, weigh competing expert models, and construct a hard-to-vary argument whose correctness is NOT checkable at a glance. "Do LLMs actually reason", "why do we think humans reason and LLMs don't given both are black boxes". E3 default; E4 across contested fields.

**The discriminating test is VERIFIABILITY, not synthesis:** can the recipient check the answer's validity by inspection (→ NATIVE), or does it require structured, evidence-bound reasoning whose correctness is opaque without doing the work (→ ALGORITHM)? When a hard-*sounding* question is really just asking for your opinion, it's NATIVE.

NATIVE has full skill/agent/parallel-research/extended-thinking access — picking NATIVE does NOT cap depth. Mode constrains output template, not capability.

## Modes

- MINIMAL — greetings, ratings, single-token acknowledgments ("ok", "thanks", "8/10", "sounds good"). No ideal state in play.
- NATIVE — ideal state articulable in one line. Fact lookup, named-file edit, refactor with known spec, LOOKUP-shaped research (the answer is facts to retrieve and assemble), opinion / advice / personal-judgment questions (a reasoned take the reader weighs at a glance), debug with known symptom, multi-file change where each step is obvious.
- ALGORITHM — ideal state requires ISC to articulate. Build/create/architect/design/integrate something whose spec doesn't yet exist. Change doctrine, system-prompt, hooks, Algorithm files. Genuinely ambiguous scope where part of the work is figuring out what to build. Hard open intellectual / explanatory / technical questions whose ANSWER must be CONSTRUCTED by analytical synthesis against external / contested / technical evidence — "do LLMs actually reason", "why is X true given Y across the science", "what's really going on with Z" — and whose correctness is NOT checkable at a glance. NOT mere opinion/advice (that stays NATIVE). E3 default; E4 when the answer spans contested fields or demands original synthesis.

## Tiers (ALGORITHM only)

- E1 Standard ~<90s — trivial single-domain, default fast lane
- E2 Extended ~3min — single-domain, quality must be extraordinary
- E3 Advanced ~10min — substantial multi-file ISC work
- E4 Deep ~30min — cross-cutting design, doctrine/architecture
- E5 Comprehensive >2h — research/build with no time pressure

## Capabilities available in ALL modes (NATIVE and ALGORITHM both)

Skill (200+ specialized skills: Research, Council, Interceptor, Forge, Architect, Engineer, Algorithm, ISA, etc.), Agent (Forge for code AND cross-vendor audit via build/audit modes, Council for debate, Research for parallel research, custom composed agents), parallel agent spawning, run_in_background, worktree isolation, extended thinking. NATIVE wields ALL of these — picking NATIVE does NOT mean "shallow."

## Time-pressure cues

Bias tier DOWN on urgency cues: asap, quick, now, just, fast, brief.
Bias tier UP on thoroughness cues: thoroughly, properly, no rush, deeply, comprehensively, master plan, from scratch.

## Bias rule (CRITICAL)

**Under-escalation is the failure mode this system was built to prevent.** When in doubt between NATIVE and ALGORITHM E3, pick ALGORITHM E3. When in doubt between two ALGORITHM tiers, pick the LOWER one. Single-word approvals to multi-step proposals inherit the proposal's mode.

## Examples

- "thanks" → MINIMAL, tier null, "acknowledgment"
- "what time is it" → NATIVE, "single fact lookup, ideal state legible"
- "fix the typo on line 12 of foo.ts" → NATIVE, "single-line edit"
- "refactor auth to use new SessionStore — full spec in PRD.md" → NATIVE, "multi-file refactor with pre-articulated spec"
- "research differences between BPE and ISD" → NATIVE, "lookup-shaped — the answer is facts to retrieve and assemble"
- "should I learn Rust or Go for backend work" → NATIVE, "opinion/advice — a reasoned take checkable at a glance, not evidence-bound analysis"
- "why do I keep procrastinating on big projects" → NATIVE, "personal-judgment synthesis is still NATIVE — do not escalate opinion questions"
- "do LLMs actually reason or just pattern-match — make the real case" → ALGORITHM E3, "answer must be built against contested technical evidence, correctness not checkable at a glance"
- "if brains and LLMs are both opaque black boxes and both fallible, why think humans do something fundamentally more advanced? educate me on the human + LLM science" → ALGORITHM E4, "hard open question spanning contested fields; the ideal answer is built, not looked up — a one-line question is NOT a one-line answer"
- "build me a complex application" → ALGORITHM E3, "spec doesn't exist yet, requires ISC"
- "audit the algorithm and update doctrine" → ALGORITHM E4, "doctrine change, spec emerges from audit"
- "design a new memory subsystem from scratch" → ALGORITHM E4, "ideal state needs ISC to become legible"
- "yes" after assistant proposed three numbered build steps for a new feature → ALGORITHM E3, "approves multi-step build"

## Output

Return ONLY a single-line JSON object, no prose, no markdown, no code fences:
{"mode":"MINIMAL"|"NATIVE"|"ALGORITHM","tier":1|2|3|4|5|null,"reason":"<one short sentence>","confidence":0.0-1.0}`;
}

function getRecentContext(transcriptPath: string | undefined, maxTurns: number = 4): string {
  if (!transcriptPath) return '';
  try {
    if (!existsSync(transcriptPath)) return '';
    const lines = readFileSync(transcriptPath, 'utf-8').trim().split('\n');
    const turns: { role: string; text: string }[] = [];
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const entry = JSON.parse(line);
        if (entry.type === 'user' && entry.message?.content) {
          const text = typeof entry.message.content === 'string'
            ? entry.message.content
            : Array.isArray(entry.message.content)
              ? entry.message.content.filter((c: { type: string }) => c.type === 'text').map((c: { text: string }) => c.text).join(' ')
              : '';
          if (text.trim()) turns.push({ role: 'User', text: text.slice(0, 200) });
        }
        if (entry.type === 'assistant' && entry.message?.content) {
          const text = typeof entry.message.content === 'string'
            ? entry.message.content
            : Array.isArray(entry.message.content)
              ? entry.message.content.filter((c: { type: string }) => c.type === 'text').map((c: { text: string }) => c.text).join(' ')
              : '';
          if (text.trim()) {
            const m = text.match(/SUMMARY:\s*([^\n]+)/i);
            turns.push({ role: 'Assistant', text: (m ? m[1] : text).slice(0, 150) });
          }
        }
      } catch {}
    }
    const recent = turns.slice(-maxTurns);
    return recent.map(t => `${t.role}: ${t.text}`).join('\n').slice(0, 600);
  } catch {
    return '';
  }
}

// ── Smart classifier ──

async function classifySmart(prompt: string, contextStr: string): Promise<Decision> {
  const cleanPrompt = prompt.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 2000);
  const userPrompt = contextStr
    ? `CONTEXT:\n${contextStr}\n\nCURRENT PROMPT:\n${cleanPrompt}`
    : cleanPrompt;

  const result = await inference({
    systemPrompt: buildClassifierSystemPrompt(),
    userPrompt,
    expectJson: true,
    timeout: CLASSIFIER_TIMEOUT_MS,
    // Re-pinned 2026-07-01 from 'max' to 'high'. max is now Fable (models.ts
    // EFFORT_MODEL); the classifier fires on EVERY substantive prompt, so paying
    // Fable's ~2× cost + extra latency per prompt is wrong. Opus ('high') is an
    // excellent classifier and is the SAME model this ran on before the flip
    // (max was Opus). "Keystone" means highest-leverage, not most-expensive rung.
    // No max→high fallback exists at 'high'; a failed attempt degrades cleanly
    // through failsafeDecision() below.
    level: 'high',
  });

  if (!result.success || !result.parsed) {
    throw new Error(result.error ?? 'classifier returned no parsed JSON');
  }

  const r = result.parsed as ClassifierJSON;
  const validModes: Mode[] = ['MINIMAL', 'NATIVE', 'ALGORITHM'];
  const mode: Mode = (r.mode && validModes.includes(r.mode as Mode)) ? (r.mode as Mode) : 'NATIVE';
  let tier: number | null = null;
  if (mode === 'ALGORITHM') {
    tier = (typeof r.tier === 'number' && r.tier >= 1 && r.tier <= 5) ? r.tier : 3;
    const confidence = typeof r.confidence === 'number' ? r.confidence : 1.0;
    if (confidence < 0.7 && tier > 2) tier = tier - 1;
  }
  const reason = (typeof r.reason === 'string' && r.reason.length > 0)
    ? r.reason.slice(0, 200)
    : 'classifier';
  return { mode, tier, reason, source: 'classifier' };
}

// ── Fail-safe ──

function failsafeDecision(prompt: string, error: string): Decision {
  const len = prompt.length;
  if (len >= 1500) {
    return { mode: 'ALGORITHM', tier: 4, reason: `fail-safe ALGORITHM E4 — ${error.slice(0, 80)} (prompt ${len} chars)`, source: 'fail-safe' };
  }
  if (len >= 400) {
    return { mode: 'ALGORITHM', tier: 3, reason: `fail-safe ALGORITHM E3 — ${error.slice(0, 80)} (prompt ${len} chars)`, source: 'fail-safe' };
  }
  return { mode: 'NATIVE', tier: null, reason: `fail-safe NATIVE — ${error.slice(0, 80)} (prompt ${len} chars)`, source: 'fail-safe' };
}

// ── Main ──

async function main(): Promise<void> {
  const t0 = Date.now();
  let prompt = '';
  let sessionId = '';
  let transcriptPath: string | undefined;

  try {
    const input = await readStdinWithTimeout();
    if (!input) { process.exit(0); }
    const data: HookInput = JSON.parse(input);
    prompt = data.prompt || data.user_prompt || '';
    sessionId = data.session_id || '';
    transcriptPath = data.transcript_path;
  } catch {
    process.exit(0);
  }

  if (!prompt) { process.exit(0); }

  // ── Remote-channel short-circuit ──
  // When the SDK subprocess is running on behalf of a remote messaging
  // channel (Telegram, iMessage, ...), the CLAUDE.md mode-template
  // constitutional rule is wrong for the surface. The principal sees the
  // mode banner ("MINIMAL", "═══ LifeOS ═══", "📃 CONTENT:") as noise in a
  // chat conversation. Instead of emitting MODE/TIER classification, emit
  // a channel-specific TELEGRAM_DIRECTIVE / IMESSAGE_DIRECTIVE that
  // OVERRIDES the mode-template rule for this turn. Per-channel ephemeral
  // system prompts get injected at runtime. The egress sanitizer in
  // LIFEOS/PULSE/lib/strip-mode-scaffolding.ts is the belt-and-suspenders
  // layer that catches anything the model leaks despite this directive.
  //
  // Source of channel marker: hooks/lib/notification-channel.ts (set by
  // PULSE/modules/{telegram,imessage}.ts on sdkOptions.env).
  const remoteChannel = process.env.LIFEOS_NOTIFICATION_CHANNEL;
  if (remoteChannel && remoteChannel !== 'desktop') {
    const channelLabel = remoteChannel.toUpperCase();
    const directive = [
      `${channelLabel}_DIRECTIVE: This response goes to the principal's ${remoteChannel} chat — NOT a terminal.`,
      'OVERRIDES CLAUDE.md mode-template rule. Reply in plain prose only.',
      'No mode banner (no "MINIMAL", "NATIVE", "ALGORITHM" label).',
      'No template fields (no "📃 CONTENT:", "🔧 CHANGE:", "✅ VERIFY:", "🗒️ TASK:", "🗣️ {{DA_NAME}}:").',
      'No header dividers (no "═══", "━━━", phase markers).',
      'Lead with the answer. Keep under 200 words. Match the DA voice from DA_IDENTITY.',
      'No markdown headers. No code blocks unless explicitly asked for code.',
    ].join('\n');
    console.log(JSON.stringify({
      hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: directive },
    }));
    appendTelemetry({
      timestamp: new Date().toISOString(),
      session_id: sessionId,
      prompt_excerpt: prompt.slice(0, 120),
      mode: 'REMOTE_CHANNEL',
      tier: null,
      reason: `remote channel: ${remoteChannel}`,
      source: 'channel-short-circuit',
      latency_ms: Date.now() - t0,
    });
    process.exit(0);
  }

  const trimmed = prompt.trim();

  // v6.4.0: run goal-signal detection once, attach to every decision path.
  const goalDetection = detectGoalSignal(prompt);

  const decorate = (decision: Decision): Decision => ({
    ...decision,
    goalSignal: goalDetection.signal,
    goalLiteral: goalDetection.literal ?? undefined,
    interviewEligible: decision.mode === 'ALGORITHM' && decision.tier !== null && decision.tier >= 3,
  });

  // 2026-05-24 (realtime-phase-tracking) + 2026-07-01 (single-authority tab/state):
  // TheRouter owns the authoritative {mode,tier} decision, so it drives BOTH
  // surfaces the instant it classifies — work.json (the Pulse Agents/Lattice page)
  // AND the kitty tab mode token. This kills the divergence where PromptProcessing's
  // shadow 8-verb classifier stamped "N" on an ALGORITHM turn, and clears a prior
  // turn's stale "✅ done" so it can't linger into live work. Idempotent, race-safe
  // (setModeToken preserves PromptProcessing's live description), failure-silent, and
  // NEVER writes stdout (the harness parses this hook's stdout as decision JSON).
  const preEmit = (decision: Decision): void => {
    if (!sessionId) return;
    const taskHint = (goalDetection.literal || prompt).slice(0, 80);
    try {
      if (decision.mode === 'ALGORITHM' && decision.tier) {
        // Persist currentMode:algorithm + tier (E{tier}) to work.json AND stamp the tab.
        markAlgorithmStarting(sessionId, taskHint, decision.tier);
        setModeToken(sessionId, `E${decision.tier}`, taskHint);
      } else if (decision.mode === 'NATIVE') {
        // Bidirectional clear, BOTH surfaces: the tab drops the stale E{tier}/✅ and
        // shows N (setModeToken), AND the Pulse Agents/Lattice dashboard records the
        // algorithm→native switch (markSessionNative sets currentMode+modeHistory,
        // the authoritative downgrade upsertSession refuses for PromptProcessing).
        setModeToken(sessionId, 'N', taskHint);
        markSessionNative(sessionId);
      }
      // MINIMAL: intentionally leave both surfaces as-is — a rating/ack often IS
      // end-of-work, and has no dashboard lane of its own.
    } catch { /* failure-silent — tab/state is best-effort, never blocks the decision */ }
  };

  const log = (decision: Decision): void => {
    appendTelemetry({
      timestamp: new Date().toISOString(),
      session_id: sessionId,
      prompt_excerpt: prompt.slice(0, 120),
      mode: decision.mode,
      tier: decision.tier,
      reason: decision.reason,
      source: decision.source,
      goal_signal: decision.goalSignal ?? null,
      goal_literal_present: !!decision.goalLiteral,
      interview_eligible: decision.interviewEligible ?? false,
      latency_ms: Date.now() - t0,
    });
  };

  // ── Stage A: deterministic fast-paths ──

  const explicitTier = explicitTierOverride(prompt);
  if (explicitTier !== null) {
    const decision: Decision = {
      mode: 'ALGORITHM', tier: explicitTier,
      reason: `explicit /e${explicitTier} override`,
      source: 'explicit',
    };
    { const d = decorate(decision); preEmit(d); emit(d); log(d); storeCache(prompt, d); process.exit(0); }
  }

  if (isExplicitRating(prompt)) {
    const decision: Decision = { mode: 'MINIMAL', tier: null, reason: 'explicit rating', source: 'fast-path' };
    { const d = decorate(decision); preEmit(d); emit(d); log(d); storeCache(prompt, d); process.exit(0); }
  }

  if (SYSTEM_TEXT_PATTERNS.some(re => re.test(trimmed))) {
    process.exit(0);
  }

  if (prompt.length < MIN_PROMPT_LENGTH) {
    const decision: Decision = { mode: 'MINIMAL', tier: null, reason: 'prompt too short', source: 'fast-path' };
    { const d = decorate(decision); emit(d); log(d); process.exit(0); }
  }

  const normalized = trimmed.toLowerCase().replace(/[.!?,'"]/g, '');
  const words = normalized.split(/\s+/);
  if (words.length <= 2 && (
    POSITIVE_PRAISE_WORDS.has(normalized) ||
    POSITIVE_PHRASES.has(normalized) ||
    (words.length === 2 && words.every(w => POSITIVE_PRAISE_WORDS.has(w)))
  )) {
    const decision: Decision = { mode: 'MINIMAL', tier: null, reason: 'positive praise / acknowledgment', source: 'fast-path' };
    { const d = decorate(decision); preEmit(d); emit(d); log(d); storeCache(prompt, d); process.exit(0); }
  }

  const hard = hardAlgorithmTrigger(prompt);
  if (hard) {
    const decision: Decision = { mode: 'ALGORITHM', tier: hard.tier, reason: hard.reason, source: 'fast-path' };
    { const d = decorate(decision); preEmit(d); emit(d); log(d); storeCache(prompt, d); process.exit(0); }
  }

  // ── Stage B: cache ──

  const cached = checkCache(prompt);
  if (cached) {
    { const d = decorate(cached); preEmit(d); emit(d); log(d); process.exit(0); }
  }

  // ── Stage C: TheRouter classifier (level 'high' = Opus; re-pinned off max 2026-07-01) ──

  try {
    const contextStr = getRecentContext(transcriptPath);
    const decision = await classifySmart(prompt, contextStr);
    { const d = decorate(decision); preEmit(d); emit(d); log(d); storeCache(prompt, d); process.exit(0); }
  } catch (err) {
    const decision = failsafeDecision(prompt, String(err));
    const d = decorate(decision);
    preEmit(d); emit(d); log(d); process.exit(0);
  }
}

main().catch((err) => {
  console.error(`[TheRouter] Fatal: ${err}`);
  process.exit(0);
});
