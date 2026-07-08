"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import KnowledgeGraph from "@/components/wiki/KnowledgeGraph";
import { Network, Search, ArrowLeft, CornerDownRight } from "lucide-react";

interface MemNode { id: string; title: string; category: string; backlinkCount: number; silo: string; pagerank: number }
interface MemEdge { source: string; target: string; kind: string }
interface Community { id: number; key: string; size: number; lead: string }
interface MemGraph { nodes: MemNode[]; edges: MemEdge[]; communities: Community[]; built: string | null; nodeCount?: number; edgeCount?: number }

const KIND_ORDER = ["related", "wikilink", "inferred", "tag"];
const KIND_LABEL: Record<string, string> = { related: "Declared (typed)", wikilink: "Wikilinks", inferred: "Inferred (similar)", tag: "Shared tags" };
const NEIGHBOR_CAP = 36;

export default function MemoryGraphPage() {
  const [focus, setFocus] = useState<string | null>(null);
  const [trail, setTrail] = useState<string[]>([]);
  const [q, setQ] = useState("");

  const { data, isLoading } = useQuery<MemGraph>({
    queryKey: ["memory-graph"],
    queryFn: async () => {
      const res = await fetch("/api/memory/graph");
      if (!res.ok) throw new Error("Failed to fetch memory graph");
      return res.json();
    },
    staleTime: 60_000,
  });

  const nodeById = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);

  // adjacency: id -> [{id, kind}]
  const adj = useMemo(() => {
    const m = new Map<string, { id: string; kind: string }[]>();
    for (const e of data?.edges ?? []) {
      (m.get(e.source) ?? m.set(e.source, []).get(e.source)!).push({ id: e.target, kind: e.kind });
      (m.get(e.target) ?? m.set(e.target, []).get(e.target)!).push({ id: e.source, kind: e.kind });
    }
    return m;
  }, [data]);

  const colorMap = useMemo(() => {
    const m: Record<string, string> = {};
    (data?.communities ?? []).forEach((c, i) => {
      m[c.key] = `hsl(${Math.round((i * 360) / Math.max((data?.communities ?? []).length, 1))}, 68%, 56%)`;
    });
    return m;
  }, [data]);

  const go = (id: string) => { if (focus) setTrail((t) => [...t, focus]); setFocus(id); setQ(""); };
  const back = () => { setTrail((t) => { const n = [...t]; const prev = n.pop(); setFocus(prev ?? null); return n; }); };

  if (isLoading || !data) {
    return <div className="flex items-center justify-center h-full"><div className="text-xs text-slate-600" style={{ fontFamily: "'concourse-t3', sans-serif" }}>Loading memory graph…</div></div>;
  }

  // Search results (title contains query)
  const results = q.trim().length >= 2
    ? data.nodes.filter((n) => n.title.toLowerCase().includes(q.toLowerCase())).sort((a, b) => b.pagerank - a.pagerank).slice(0, 14)
    : [];

  // Neighborhood subgraph for the focused node
  const focusNode = focus ? nodeById.get(focus) : null;
  const neighbors = focus ? (adj.get(focus) ?? []) : [];
  // dedupe neighbor ids, keep strongest kind, cap by neighbor pagerank
  const seen = new Map<string, string>();
  for (const nb of neighbors) if (!seen.has(nb.id)) seen.set(nb.id, nb.kind);
  const neighborIds = [...seen.keys()].sort((a, b) => (nodeById.get(b)?.pagerank ?? 0) - (nodeById.get(a)?.pagerank ?? 0)).slice(0, NEIGHBOR_CAP);
  const subIds = new Set<string>([...(focus ? [focus] : []), ...neighborIds]);
  const subNodes = [...subIds].map((id) => nodeById.get(id)!).filter(Boolean);
  const subEdges = data.edges.filter((e) => subIds.has(e.source) && subIds.has(e.target));

  // Connections grouped by kind for the side panel
  const grouped: Record<string, { id: string; title: string; silo: string }[]> = {};
  for (const id of neighborIds) {
    const k = seen.get(id)!; const n = nodeById.get(id); if (!n) continue;
    (grouped[k] ??= []).push({ id, title: n.title, silo: n.silo });
  }

  const startPoints = data.communities.slice(0, 10);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-800/50 bg-slate-950/80 shrink-0">
        <Network className="w-4 h-4 text-violet-400" />
        <h1 className="text-sm font-medium text-white tracking-wide" style={{ fontFamily: "'advocate-c14', sans-serif" }}>Memory Graph — explore connections</h1>
        <div className="relative ml-4 flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
          <input
            value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search any memory item…"
            className="w-full bg-slate-900/80 border border-slate-700/60 rounded pl-7 pr-2 py-1 text-[12px] text-slate-200 outline-none focus:border-violet-500/60"
            style={{ fontFamily: "'concourse-t3', sans-serif" }}
          />
          {results.length > 0 && (
            <div className="absolute z-20 mt-1 w-full max-h-72 overflow-y-auto bg-slate-900 border border-slate-700 rounded shadow-xl">
              {results.map((r) => (
                <button key={r.id} onClick={() => go(r.id)} className="block w-full text-left px-2 py-1 text-[12px] text-slate-300 hover:bg-violet-600/20 hover:text-white truncate" style={{ fontFamily: "'concourse-t3', sans-serif" }}>
                  <span className="text-slate-500 text-[10px] uppercase mr-1">{r.silo}</span>{r.title}
                </button>
              ))}
            </div>
          )}
        </div>
        <span className="text-[11px] text-slate-500" style={{ fontFamily: "'concourse-t3', sans-serif" }}>{data.nodeCount} nodes · {data.communities.length} communities</span>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Side panel: focus + clickable connections (the useful part) */}
        <div className="w-80 shrink-0 overflow-y-auto border-r border-slate-800/50 bg-slate-950/60 p-3">
          {!focusNode ? (
            <div>
              <div className="text-[11px] text-slate-400 mb-3" style={{ fontFamily: "'concourse-t3', sans-serif" }}>
                Search above, or jump into a community to start exploring. Click any item to see what it connects to; click a connection to walk the graph.
              </div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2" style={{ fontFamily: "'advocate-c14', sans-serif" }}>Start points</div>
              {startPoints.map((c) => (
                <button key={c.key} onClick={() => go(data.nodes.find((n) => n.category === c.key)?.id ?? c.lead)} className="flex items-center gap-2 w-full text-left py-1 group">
                  <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: colorMap[c.key] }} />
                  <span className="text-[12px] text-slate-300 truncate group-hover:text-white" style={{ fontFamily: "'concourse-t3', sans-serif" }}>{c.lead} <span className="text-slate-600">({c.size})</span></span>
                </button>
              ))}
            </div>
          ) : (
            <div>
              <div className="flex items-center gap-2 mb-2">
                {trail.length > 0 && <button onClick={back} className="text-slate-400 hover:text-white"><ArrowLeft className="w-3.5 h-3.5" /></button>}
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: colorMap[focusNode.category] }} />
                <span className="text-[10px] uppercase text-slate-500">{focusNode.silo}</span>
              </div>
              <div className="text-[14px] text-white font-medium mb-1 leading-snug" style={{ fontFamily: "'advocate-c14', sans-serif" }}>{focusNode.title}</div>
              <div className="text-[11px] text-slate-500 mb-3" style={{ fontFamily: "'concourse-t3', sans-serif" }}>{neighborIds.length} connections</div>
              {KIND_ORDER.filter((k) => grouped[k]?.length).map((k) => (
                <div key={k} className="mb-3">
                  <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1" style={{ fontFamily: "'advocate-c14', sans-serif" }}>{KIND_LABEL[k]} ({grouped[k].length})</div>
                  <div className="space-y-1.5">
                    {grouped[k].map((n) => (
                      <button key={n.id} onClick={() => go(n.id)} className="flex items-start gap-1.5 w-full text-left group">
                        <CornerDownRight className="w-3 h-3 text-slate-600 mt-[3px] shrink-0 group-hover:text-violet-400" />
                        <span className="flex-1 min-w-0 text-[12px] text-slate-300 group-hover:text-white" style={{ fontFamily: "'concourse-t3', sans-serif", lineHeight: 1.35 }}>
                          <span className="text-slate-600 text-[10px] uppercase mr-1 align-baseline">{n.silo}</span>{n.title}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Focused mini-graph: just this node + neighbors, readable */}
        <div className="flex-1 min-w-0">
          {focusNode
            ? <KnowledgeGraph nodes={subNodes} edges={subEdges} colorMap={colorMap} onNodeClick={(slug) => go(slug)} />
            : <div className="flex items-center justify-center h-full text-[12px] text-slate-600" style={{ fontFamily: "'concourse-t3', sans-serif" }}>Pick something on the left to see its connections.</div>}
        </div>
      </div>
    </div>
  );
}
