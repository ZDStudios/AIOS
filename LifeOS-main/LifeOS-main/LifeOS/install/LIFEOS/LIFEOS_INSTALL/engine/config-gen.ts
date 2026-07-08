/**
 * LifeOS Installer v6.0 — Configuration Generator
 * Generates a FALLBACK settings.json from collected user data.
 * Only used when no existing settings.json exists.
 * Produces minimal output — just fields the installer collects.
 * Hooks, permissions, and other config come from the release template.
 */

import type { LifeosConfig } from "./types";
import { DEFAULT_VOICES, LIFEOS_VERSION, ALGORITHM_VERSION } from "./types";

/**
 * Generate a minimal fallback settings.json from installer-collected data.
 * This is merged into (not replacing) the release template.
 */
export function generateSettingsJson(config: LifeosConfig): Record<string, any> {
  const voiceId = config.voiceId || DEFAULT_VOICES[config.voiceType as keyof typeof DEFAULT_VOICES] || DEFAULT_VOICES.female;

  return {
    env: {
      // LIFEOS_DIR is the LifeOS subsystem directory (~/.claude/LIFEOS) — where Memory,
      // Algorithm, USER, TOOLS, PULSE live. NOT the install root (~/.claude).
      // LIFEOS_StatusLine.sh, hooks, and tools read LIFEOS_DIR expecting the /PAI
      // suffix; if we write just `~/.claude` here the statusline can't find
      // ALGORITHM/LATEST and falls back to "—". The variable name `config.paiDir`
      // is misleading — it's actually the INSTALL ROOT.
      LIFEOS_DIR: `${config.paiDir}/PAI`,
      ...(config.projectsDir ? { PROJECTS_DIR: config.projectsDir } : {}),
      LIFEOS_CONFIG_DIR: config.configDir,
    },

    daidentity: {
      name: config.aiName,
      fullName: `${config.aiName} — Personal AI`,
      displayName: config.aiName.toUpperCase(),
      color: "#3B82F6",
      voices: {
        main: {
          voiceId,
          stability: 0.35,
          similarityBoost: 0.80,
          style: 0.90,
          speed: 1.1,
        },
      },
      startupCatchphrase: config.catchphrase,
    },

    principal: {
      name: config.principalName,
      timezone: config.timezone,
    },

    preferences: {
      temperatureUnit: config.temperatureUnit || "fahrenheit",
    },

    pai: {
      repoUrl: "https://github.com/danielmiessler/PAI",
      version: LIFEOS_VERSION,
      algorithmVersion: ALGORITHM_VERSION,
    },
  };
}
