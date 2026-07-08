import { loadAllManifests, loadManifestById } from "./lib/manifest-loader";
import { readPage, readIndex, isStale, writeIndex, type IndexEntry } from "./lib/data-plane";
import { renderShell, renderPage, renderEmpty, renderStaleBanner } from "./ui/render";
import { runAdapter } from "./adapters/AdapterRunner";
import { applyEdit } from "./edit/edit-handler";

function html(body: string, status = 200): Response {
  return new Response(body, { status, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), { status, headers: { "Content-Type": "application/json" } });
}

async function refreshIndex(): Promise<void> {
  const manifests = loadAllManifests();
  const entries: IndexEntry[] = manifests.map((m) => {
    const file = readPage(m.id);
    return {
      id: m.id,
      title: m.title,
      kind: m.dataType.replace("PageSchema", "").toLowerCase(),
      lastBuildAt: file?._meta.lastBuildAt ?? "",
      hasError: !file,
      costUSD: file?._meta.costUSD ?? 0,
      provenance: file?._meta.provenance ?? "template",
    };
  });
  writeIndex(entries);
}

export async function handleV2Request(req: Request, pathname: string): Promise<Response | null> {
  if (!pathname.startsWith("/v2") && !pathname.startsWith("/api/pulse/rebuild") && !pathname.startsWith("/api/pulse/edit")) {
    return null;
  }

  // GET /v2/ → redirect to first page
  if (req.method === "GET" && (pathname === "/v2" || pathname === "/v2/")) {
    const idx = readIndex();
    const first = idx?.pages[0];
    if (first) return new Response(null, { status: 302, headers: { Location: `/v2/${first.id}` } });
    return html(renderShell({
      mode: "light",
      pageId: "_root",
      pageTitle: "Pulse v2",
      index: idx,
      body: renderEmpty("_root", "No pages yet. Run `bun LIFEOS/PULSE/Tools/RebuildAll.ts` to populate."),
    }));
  }

  // GET /v2/:pageId → render page
  const pageMatch = pathname.match(/^\/v2\/([a-z][a-z0-9-]*)$/);
  if (req.method === "GET" && pageMatch) {
    const pageId = pageMatch[1]!;
    const manifest = loadManifestById(pageId);
    if (!manifest) return new Response(`unknown page: ${pageId}`, { status: 404 });

    const idx = readIndex();
    const file = readPage(pageId);
    if (!file) {
      return html(renderShell({
        mode: "light",
        pageId,
        pageTitle: manifest.title,
        index: idx,
        body: renderEmpty(manifest.title, "No data plane file yet — click Rebuild to generate."),
      }));
    }
    const stale = isStale(pageId, manifest.staleAfterHours);
    let body = "";
    if (stale?.stale) body += renderStaleBanner(stale.ageHours);
    body += renderPage(file.data, { rebuildable: manifest.rebuildButton });
    return html(renderShell({ mode: "light", pageId, pageTitle: manifest.title, index: idx, body }));
  }

  // POST /api/pulse/rebuild/:pageId
  const rebuildMatch = pathname.match(/^\/api\/pulse\/rebuild\/([a-z][a-z0-9-]*)$/);
  if (req.method === "POST" && rebuildMatch) {
    const pageId = rebuildMatch[1]!;
    const manifest = loadManifestById(pageId);
    if (!manifest) return json({ ok: false, error: "unknown page" }, 404);
    const result = await runAdapter(manifest, { force: true });
    await refreshIndex();
    return json({ ok: result.status === "success", result });
  }

  // POST /api/pulse/rebuild-all
  if (req.method === "POST" && pathname === "/api/pulse/rebuild-all") {
    const manifests = loadAllManifests();
    const start = Date.now();
    const results = await Promise.allSettled(manifests.map((m) => runAdapter(m, { force: true })));
    await refreshIndex();
    return json({
      ok: true,
      wallMs: Date.now() - start,
      results: results.map((r, i) => r.status === "fulfilled" ? r.value : { manifest: manifests[i], status: "rejected" }),
    });
  }

  // POST /api/pulse/edit/:pageId
  const editMatch = pathname.match(/^\/api\/pulse\/edit\/([a-z][a-z0-9-]*)$/);
  if (req.method === "POST" && editMatch) {
    const pageId = editMatch[1]!;
    const body = await req.json() as Record<string, unknown>;
    const result = applyEdit({
      pageId,
      sourceFile: String(body.sourceFile),
      fieldPath: String(body.fieldPath),
      beforeHash: String(body.beforeHash),
      newContent: String(body.newContent),
      draftStartedAt: String(body.draftStartedAt),
    });
    return json(result, result.ok ? 200 : 409);
  }

  return null;
}
