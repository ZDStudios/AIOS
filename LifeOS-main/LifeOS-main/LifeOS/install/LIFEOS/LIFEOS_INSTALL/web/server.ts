/**
 * LifeOS Installer v6.0 — Web Server
 * Bun HTTP + WebSocket server for the thick-client web installer.
 * Serves static files and handles WebSocket communication.
 */

// Prevent unhandled errors from crashing the server
process.on("uncaughtException", (err) => {
  console.error("[LifeOS Installer] Uncaught exception:", err.message);
});
process.on("unhandledRejection", (err: any) => {
  console.error("[LifeOS Installer] Unhandled rejection:", err?.message || err);
});

import { existsSync, readFileSync } from "fs";
import { join, extname } from "path";
import { handleWsMessage, addClient, removeClient } from "./routes";

const PORT = parseInt(process.env.LIFEOS_INSTALL_PORT || "1337");
const PUBLIC_DIR = join(import.meta.dir, "..", "public");

// Read canonical LifeOS version on startup. The installer ships inside
// ~/.claude/LIFEOS/LIFEOS_INSTALL/, so PAI/VERSION sits two levels up. The
// {{LIFEOS_VERSION}} placeholder in HTML responses is substituted on serve
// — change PAI/VERSION (or run UpdateLifeosVersion) and the installer banner
// reflects the new version on next launch with no source edit needed.
const LIFEOS_VERSION_FILE = join(import.meta.dir, "..", "..", "VERSION");
const LIFEOS_VERSION: string = (() => {
  try { return readFileSync(LIFEOS_VERSION_FILE, "utf8").trim() || "?.?.?"; }
  catch { return "?.?.?"; }
})();
function injectVersion(html: string): string {
  return html.split("{{LIFEOS_VERSION}}").join(LIFEOS_VERSION);
}

// ─── MIME Types ──────────────────────────────────────────────────

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "application/javascript",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".ico": "image/x-icon",
};

// ─── Inactivity Timeout ──────────────────────────────────────────

const INACTIVITY_MS = 30 * 60 * 1000; // 30 minutes
let inactivityTimer: Timer | null = null;

function resetInactivity(): void {
  if (inactivityTimer) clearTimeout(inactivityTimer);
  inactivityTimer = setTimeout(() => {
    console.log("\n[LifeOS Installer] Shutting down due to inactivity.");
    process.exit(0);
  }, INACTIVITY_MS);
}

// ─── Server ──────────────────────────────────────────────────────

const server = Bun.serve({
  port: PORT,
  hostname: "127.0.0.1", // Localhost only — never expose to network

  fetch(req, server) {
    resetInactivity();

    const url = new URL(req.url);

    // WebSocket upgrade
    if (url.pathname === "/ws") {
      const upgraded = server.upgrade(req);
      if (!upgraded) {
        return new Response("WebSocket upgrade failed", { status: 400 });
      }
      return undefined as any;
    }

    // Static file serving
    let filePath = url.pathname === "/" ? "/index.html" : url.pathname;
    const fullPath = join(PUBLIC_DIR, filePath);

    // Security: prevent directory traversal
    if (!fullPath.startsWith(PUBLIC_DIR)) {
      return new Response("Forbidden", { status: 403 });
    }

    if (existsSync(fullPath)) {
      const ext = extname(fullPath);
      const mime = MIME_TYPES[ext] || "application/octet-stream";
      // Substitute {{LIFEOS_VERSION}} in HTML responses so the installer
      // banner always reflects the canonical PAI/VERSION on disk.
      const isHtml = ext === ".html";
      const content = isHtml ? injectVersion(readFileSync(fullPath, "utf8")) : readFileSync(fullPath);
      return new Response(content, {
        headers: {
          "content-type": mime,
          "cache-control": "no-cache, no-store, must-revalidate",
        },
      });
    }

    // Fallback to index.html for SPA routing
    const indexPath = join(PUBLIC_DIR, "index.html");
    if (existsSync(indexPath)) {
      return new Response(injectVersion(readFileSync(indexPath, "utf8")), {
        headers: { "content-type": "text/html", "cache-control": "no-cache" },
      });
    }

    return new Response("Not Found", { status: 404 });
  },

  websocket: {
    open(ws) {
      addClient(ws);
      ws.send(JSON.stringify({ type: "connected", port: PORT }));
    },
    message(ws, message) {
      resetInactivity();
      handleWsMessage(ws, typeof message === "string" ? message : message.toString());
    },
    close(ws) {
      removeClient(ws);
    },
  },
});

resetInactivity();

console.log(`LifeOS Installer server running on http://127.0.0.1:${PORT}/`);

export { server };
