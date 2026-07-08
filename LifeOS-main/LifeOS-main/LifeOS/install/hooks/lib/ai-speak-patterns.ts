/**
 * ai-speak-patterns.ts — detector for AI-speak drift in assistant prose.
 *
 * Operationalizes the DA_IDENTITY § Hard Bans / AIWritingPatterns.md ban list as a
 * deterministic, testable scan. Consumed by OutputFormatGate.hook.ts (Stop) to block
 * responses that drift back into AI register — the recurring failure {{PRINCIPAL_NAME}} keeps
 * having to correct by hand.
 *
 * Design constraints (why it won't over-fire):
 *  - Scans PROSE only: code fences, inline code, and quoted spans are stripped first,
 *    so discussing the ban list ("don't say `delve`") never counts as a hit.
 *  - Two signal classes: banned vocabulary (weight 1 each) and the contrastive
 *    construction (the #1 tell — weight 3, blocks on its own).
 *  - Word list is the high-signal operative subset, curated to avoid LifeOS vocabulary
 *    collisions (harness / substrate / ecosystem / robust / comprehensive are NOT
 *    banned here — they're legitimate system terms).
 */

// High-signal banned vocabulary (whole-word, case-insensitive). Operative subset of
// DA_IDENTITY § Hard Bans — deliberately excludes words that collide with real LifeOS
// system vocabulary. Multi-word entries matched as phrases.
export const BANNED_WORDS: string[] = [
  "delve",
  "leverage",
  "utilize",
  "seamless",
  "seamlessly",
  "meticulous",
  "meticulously",
  "pivotal",
  "tapestry",
  "realm",
  "paradigm",
  "embark",
  "beacon",
  "vibrant",
  "thriving",
  "nestled",
  "showcasing",
  "intricate",
  "intricacies",
  "ever-evolving",
  "daunting",
  "holistic",
  "synergy",
  "boasts",
  "commence",
  "ascertain",
  "endeavor",
  "foster",
  "elevate",
  "unleash",
  "streamline",
  "empower",
  "bolster",
  "resonate",
  "revolutionize",
  "facilitate",
  "underpin",
  "multifaceted",
  "myriad",
  "plethora",
  "catalyze",
  "reimagine",
  "galvanize",
  "cultivate",
  "illuminate",
  "elucidate",
  "cornerstone",
  "paramount",
  "burgeoning",
  "nascent",
  "quintessential",
  "overarching",
  "game-changer",
  "cutting-edge",
  "deep dive",
  "dive into",
  "thought leader",
  "at its core",
  "testament to",
  "poised to",
  "in order to",
  "due to the fact that",
];

// The contrastive tic — "Not X. It's Y." and variants. The single most reliable AI
// tell. Tuned to the "just/only/merely + but/it's/dash" structure to avoid firing on
// incidental "not ... it's" prose.
// Apostrophes use the class ['’] so smart-quoted contractions ("isn’t") match too.
export const CONTRASTIVE_PATTERNS: RegExp[] = [
  /\bnot\s+(just|only|merely|simply)\b[^.!?\n]*\b(but|it['’]?s|they['’]?re|that['’]?s)\b/i,
  /\b(isn['’]?t|aren['’]?t|wasn['’]?t|weren['’]?t)\s+(just|only|merely|simply)\b[^.!?\n]*[—–-]/i,
  /\bit['’]?s\s+not\s+(just|only|that|about)\b[^.!?\n]*,\s*(it['’]?s|but|they['’]?re)\b/i,
  /\bnot\s+[a-z]+\s*[—–]\s*it['’]?s\b/i,
  /\bmore\s+than\s+(just\s+)?[a-z][^.!?\n]*,\s*(it['’]?s|this\s+is)\b/i,
];

export interface AiSpeakScan {
  wordHits: string[];
  contrastiveHits: number;
  score: number; // wordHits.length * 1 + contrastiveHits * 3
}

/**
 * Strip the spans that should never be scanned: fenced code blocks, inline code,
 * and double-quoted spans (quoting someone / a banned word). This is what keeps
 * meta-discussion of the ban list from tripping the gate.
 */
export function stripNonProse(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ") // fenced code
    .replace(/`[^`\n]*`/g, " ") // inline code
    .replace(/"[^"\n]{0,200}"/g, " ") // double-quoted spans
    .replace(/“[^”\n]{0,200}”/g, " "); // smart-quoted spans
}

export function scanAiSpeak(rawText: string): AiSpeakScan {
  const text = stripNonProse(rawText);
  const lower = text.toLowerCase();

  const wordHits: string[] = [];
  for (const term of BANNED_WORDS) {
    // Whole-word / phrase match; hyphenated and multi-word entries handled by \b ... \b.
    const re = new RegExp(`(?<![a-z])${term.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&")}(?![a-z])`, "i");
    if (re.test(lower)) wordHits.push(term);
  }

  let contrastiveHits = 0;
  for (const re of CONTRASTIVE_PATTERNS) {
    if (re.test(text)) contrastiveHits++;
  }

  const score = wordHits.length * 1 + contrastiveHits * 3;
  return { wordHits, contrastiveHits, score };
}
