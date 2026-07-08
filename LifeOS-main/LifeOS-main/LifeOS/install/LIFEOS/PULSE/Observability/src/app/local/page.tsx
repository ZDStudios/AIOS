"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Building2,
  Shield,
  Briefcase,
  Users,
  ScrollText,
  Vote,
  Gavel,
  Newspaper,
  RefreshCw,
  AlertCircle,
} from "lucide-react";

type SourceStatus = "ok" | "unavailable" | "empty";
type Item = { title: string; source: string; url: string; date: string; summary?: string };
type FetchResult = { items: Item[]; source_status: SourceStatus; errors?: string[] };

interface Digest {
  meta: {
    city: string;
    state: string;
    county?: string;
    zip?: string;
    generated_at: string;
    sources_used: string[];
    sources_failed: string[];
    errors: string[];
  };
  construction: FetchResult;
  crime: FetchResult;
  business: FetchResult;
  officials: FetchResult;
  legislation: FetchResult;
  elections: FetchResult;
  arrests: FetchResult;
  news: FetchResult;
}

type SectionKey =
  | "construction"
  | "crime"
  | "business"
  | "officials"
  | "legislation"
  | "elections"
  | "arrests"
  | "news";

interface SectionDef {
  key: SectionKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  // Tailwind classes already authored as full class names so JIT picks them up.
  chipBg: string;
  chipBorder: string;
  chipText: string;
  iconText: string;
  dot: string;
  emptyHint: string;
}

const SECTIONS: SectionDef[] = [
  {
    key: "construction",
    label: "Construction",
    icon: Building2,
    chipBg: "bg-amber-400/10",
    chipBorder: "border-amber-400/30",
    chipText: "text-amber-300",
    iconText: "text-amber-400",
    dot: "bg-amber-400",
    emptyHint: "No new construction permits this week.",
  },
  {
    key: "crime",
    label: "Crime",
    icon: Shield,
    chipBg: "bg-red-400/10",
    chipBorder: "border-red-400/30",
    chipText: "text-red-300",
    iconText: "text-red-400",
    dot: "bg-red-400",
    emptyHint: "No new crime stats this week.",
  },
  {
    key: "business",
    label: "New Business",
    icon: Briefcase,
    chipBg: "bg-emerald-400/10",
    chipBorder: "border-emerald-400/30",
    chipText: "text-emerald-300",
    iconText: "text-emerald-400",
    dot: "bg-emerald-400",
    emptyHint: "No new business openings this week.",
  },
  {
    key: "officials",
    label: "Officials",
    icon: Users,
    chipBg: "bg-indigo-400/10",
    chipBorder: "border-indigo-400/30",
    chipText: "text-indigo-300",
    iconText: "text-indigo-400",
    dot: "bg-indigo-400",
    emptyHint: "No officials news this week.",
  },
  {
    key: "legislation",
    label: "Legislation",
    icon: ScrollText,
    chipBg: "bg-violet-400/10",
    chipBorder: "border-violet-400/30",
    chipText: "text-violet-300",
    iconText: "text-violet-400",
    dot: "bg-violet-400",
    emptyHint: "No pending or enacted laws this week.",
  },
  {
    key: "elections",
    label: "Elections",
    icon: Vote,
    chipBg: "bg-sky-400/10",
    chipBorder: "border-sky-400/30",
    chipText: "text-sky-300",
    iconText: "text-sky-400",
    dot: "bg-sky-400",
    emptyHint: "No upcoming elections.",
  },
  {
    key: "arrests",
    label: "Arrests",
    icon: Gavel,
    chipBg: "bg-orange-400/10",
    chipBorder: "border-orange-400/30",
    chipText: "text-orange-300",
    iconText: "text-orange-400",
    dot: "bg-orange-400",
    emptyHint: "No new arrests reported this week.",
  },
  {
    key: "news",
    label: "Local News",
    icon: Newspaper,
    chipBg: "bg-cyan-400/10",
    chipBorder: "border-cyan-400/30",
    chipText: "text-cyan-300",
    iconText: "text-cyan-400",
    dot: "bg-cyan-400",
    emptyHint: "No local news this week.",
  },
];

function relativeTime(iso: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const ago = Math.floor((Date.now() - t) / 1000);
  if (ago < 60) return `${ago}s ago`;
  if (ago < 3600) return `${Math.floor(ago / 60)}m ago`;
  if (ago < 86400) return `${Math.floor(ago / 3600)}h ago`;
  if (ago < 86400 * 30) return `${Math.floor(ago / 86400)}d ago`;
  if (ago < 86400 * 365) return `${Math.floor(ago / (86400 * 30))}mo ago`;
  return `${Math.floor(ago / (86400 * 365))}y ago`;
}

export default function LocalPage() {
  const [digest, setDigest] = useState<Digest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/local-intelligence", { cache: "no-store" });
      if (!res.ok) {
        setError(res.status === 404 ? "not-yet-generated" : `http_${res.status}`);
        setDigest(null);
        return;
      }
      const j = (await res.json()) as Digest;
      setDigest(j);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
      setDigest(null);
    }
  }, []);

  const refreshNow = async () => {
    setRefreshing(true);
    try {
      await fetch("/api/local-intelligence/refresh", { method: "POST" });
      const start = Date.now();
      while (Date.now() - start < 90_000) {
        await new Promise((r) => setTimeout(r, 3000));
        const res = await fetch("/api/local-intelligence", { cache: "no-store" });
        if (res.ok) {
          const j = (await res.json()) as Digest;
          if (!digest || j.meta.generated_at !== digest.meta.generated_at) {
            setDigest(j);
            setError(null);
            break;
          }
        }
      }
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void load();
  }, [load]);

  if (error === "not-yet-generated") {
    return (
      <main className="max-w-[1400px] mx-auto px-6 py-8 text-slate-200">
        <h1 className="text-2xl font-semibold mb-4 tracking-tight">Local Intelligence</h1>
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-amber-400 mt-0.5" />
          <div>
            <p className="font-medium">No digest generated yet.</p>
            <p className="text-sm text-slate-300 mt-1">
              The first refresh hasn&apos;t completed. Click below to run it now or wait
              for the daily 6 a.m. job.
            </p>
            <button
              onClick={refreshNow}
              disabled={refreshing}
              className="mt-4 inline-flex items-center gap-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 px-3 py-1.5 text-sm font-medium"
            >
              <RefreshCw className={refreshing ? "w-4 h-4 animate-spin" : "w-4 h-4"} />
              {refreshing ? "Refreshing…" : "Refresh now"}
            </button>
          </div>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="max-w-[1400px] mx-auto px-6 py-8 text-slate-200">
        <h1 className="text-2xl font-semibold mb-4 tracking-tight">Local Intelligence</h1>
        <div className="rounded-lg border border-red-900 bg-red-950/40 p-4 text-sm">
          Error loading digest: {error}
        </div>
      </main>
    );
  }

  if (!digest) {
    return (
      <main className="max-w-[1400px] mx-auto px-6 py-8 text-slate-400 text-sm">
        Loading…
      </main>
    );
  }

  const { meta } = digest;
  const totalSources = meta.sources_used.length + meta.sources_failed.length;

  return (
    <main className="max-w-[1400px] mx-auto px-6 py-8 text-slate-200">
      {/* Header */}
      <header className="flex items-end justify-between mb-8 flex-wrap gap-3 pb-5 border-b border-slate-800">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-50">
            {meta.city}, {meta.state}
          </h1>
          <p className="mt-2 flex items-center gap-3 text-[12px] uppercase tracking-[0.18em] text-slate-500 font-mono">
            {meta.zip ? <span>{meta.zip}</span> : null}
            {meta.county ? (
              <>
                <span className="text-slate-700">·</span>
                <span>{meta.county} County</span>
              </>
            ) : null}
            <span className="text-slate-700">·</span>
            <span>refreshed {relativeTime(meta.generated_at)}</span>
            <span className="text-slate-700">·</span>
            <span className="text-slate-400">
              {meta.sources_used.length}/{totalSources} sources
            </span>
          </p>
        </div>
        <button
          onClick={refreshNow}
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-md border border-slate-700 hover:border-slate-500 disabled:opacity-50 px-3 py-1.5 text-sm transition-colors"
        >
          <RefreshCw className={refreshing ? "w-4 h-4 animate-spin" : "w-4 h-4"} />
          {refreshing ? "Refreshing…" : "Refresh now"}
        </button>
      </header>

      {/* Card grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {SECTIONS.map((section) => {
          const data = digest[section.key];
          const Icon = section.icon;
          return (
            <section
              key={section.key}
              className="rounded-xl border border-slate-800 bg-slate-900/40 hover:border-slate-700 transition-colors p-5 flex flex-col"
            >
              {/* Section header chip */}
              <header className="flex items-center justify-between mb-4">
                <div
                  className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-md border ${section.chipBg} ${section.chipBorder}`}
                >
                  <Icon className={`w-3.5 h-3.5 ${section.iconText}`} />
                  <span className={`text-[12px] uppercase tracking-[0.2em] font-semibold ${section.chipText}`}>
                    {section.label}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      data.source_status === "ok"
                        ? section.dot
                        : data.source_status === "empty"
                          ? "bg-slate-600"
                          : "bg-amber-500"
                    }`}
                  />
                  <span className="text-[12px] uppercase tracking-wider text-slate-500 font-mono">
                    {data.source_status}
                  </span>
                </div>
              </header>

              {data.items.length === 0 ? (
                <p className="text-sm text-slate-400 italic">
                  {data.source_status === "unavailable"
                    ? "Source unavailable for this city."
                    : section.emptyHint}
                </p>
              ) : (
                <ul className="space-y-3.5 flex-1">
                  {data.items.slice(0, 7).map((item, i) => (
                    <li key={i} className="group">
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block"
                      >
                        <div className="text-[14px] font-medium text-slate-100 leading-snug group-hover:text-blue-400 transition-colors line-clamp-2">
                          {item.title}
                        </div>
                        {item.summary ? (
                          <p className="mt-1 text-[13px] text-slate-300 leading-relaxed line-clamp-2">
                            {item.summary}
                          </p>
                        ) : null}
                        <div className="mt-1.5 text-[12px] uppercase tracking-[0.15em] text-slate-500 font-mono tabular-nums flex items-center gap-2">
                          <span className="truncate max-w-[60%]">{item.source}</span>
                          {item.date ? (
                            <>
                              <span className="text-slate-700">·</span>
                              <span>{relativeTime(item.date)}</span>
                            </>
                          ) : null}
                        </div>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>

      {/* Errors */}
      {meta.errors.length > 0 ? (
        <details className="mt-8 text-xs text-slate-500 font-mono">
          <summary className="cursor-pointer hover:text-slate-300 uppercase tracking-[0.18em]">
            {meta.errors.length} source error{meta.errors.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-3 space-y-1 pl-4">
            {meta.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </main>
  );
}
