"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Sparkles,
  RefreshCw,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Clock,
} from "lucide-react";
import EmptyStateGuide from "@/components/EmptyStateGuide";

interface HypothesisSummary {
  slug: string;
  claim: string;
  confidence: number;
  target_frame: string;
  evidence_count: number;
  generated: string;
  expires_in_days: number;
}

interface HypothesisDetail extends HypothesisSummary {
  status: string;
  expires: string;
  evidence_signals: string[];
  falsifier: string;
  evidence: string;
  suggested_action: string;
}

function formatTimestamp(iso: string): string {
  if (!iso || iso === "never") return iso || "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function HypothesisCard({
  hypothesis,
  onGraduate,
  onReject,
}: {
  hypothesis: HypothesisSummary;
  onGraduate: (slug: string) => void;
  onReject: (slug: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<HypothesisDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const confidencePct = Math.round(hypothesis.confidence * 100);
  const expiresSoon = hypothesis.expires_in_days < 7;

  async function toggleExpand() {
    const next = !expanded;
    setExpanded(next);
    if (next && !detail) {
      setLoadingDetail(true);
      try {
        const resp = await fetch(
          `/api/hypotheses/${encodeURIComponent(hypothesis.slug)}`
        );
        if (resp.ok) setDetail(await resp.json());
      } finally {
        setLoadingDetail(false);
      }
    }
  }

  return (
    <div
      className={`bg-white/[0.02] border rounded-xl p-4 space-y-3 transition-colors ${
        expiresSoon ? "border-amber-500/40" : "border-white/[0.06]"
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-lg bg-purple-500/20 shrink-0">
          <Sparkles size={16} className="text-purple-300" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-zinc-200 leading-snug">
            {hypothesis.claim || hypothesis.slug}
          </h3>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className="text-emerald-400 font-semibold tabular-nums">
              {confidencePct}% confidence
            </span>
            <span className="text-zinc-500">
              → <span className="text-zinc-300">{hypothesis.target_frame}</span>
            </span>
            <span className="text-zinc-500">
              {hypothesis.evidence_count} signals
            </span>
            <span
              className={`flex items-center gap-1 ${
                expiresSoon ? "text-amber-400 font-semibold" : "text-zinc-500"
              }`}
            >
              <Clock size={11} />
              expires in {hypothesis.expires_in_days}d
            </span>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => onGraduate(hypothesis.slug)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30 transition-colors"
        >
          <CheckCircle2 size={12} />
          Graduate
        </button>
        <button
          onClick={() => onReject(hypothesis.slug)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-red-500/10 text-red-300 border border-red-500/30 hover:bg-red-500/20 transition-colors"
        >
          <XCircle size={12} />
          Reject
        </button>
        <button
          onClick={toggleExpand}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04] transition-colors ml-auto"
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {expanded ? "Hide" : "Evidence"}
        </button>
      </div>

      {expanded && (
        <div className="pt-3 border-t border-white/[0.04] space-y-3 text-xs">
          {loadingDetail && (
            <div className="text-zinc-500 italic">Loading detail…</div>
          )}
          {detail && (
            <>
              <div>
                <div className="text-zinc-400 uppercase tracking-wide text-[13px] mb-1">
                  Evidence ({detail.evidence_signals.length} signals)
                </div>
                <ul className="space-y-0.5 text-zinc-300 font-mono">
                  {detail.evidence_signals.slice(0, 8).map((sig) => (
                    <li key={sig} className="truncate">
                      {sig}
                    </li>
                  ))}
                  {detail.evidence_signals.length > 8 && (
                    <li className="text-zinc-600">
                      +{detail.evidence_signals.length - 8} more
                    </li>
                  )}
                </ul>
              </div>
              <div>
                <div className="text-zinc-400 uppercase tracking-wide text-[13px] mb-1">
                  Falsifier
                </div>
                <p className="text-zinc-300">{detail.falsifier}</p>
              </div>
              {detail.suggested_action && (
                <div>
                  <div className="text-zinc-400 uppercase tracking-wide text-[13px] mb-1">
                    Suggested Action
                  </div>
                  <p className="text-zinc-300">{detail.suggested_action}</p>
                </div>
              )}
              <div className="text-zinc-600 text-[12px] font-mono">
                generated {formatTimestamp(detail.generated)}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function HypothesesPage() {
  const [items, setItems] = useState<HypothesisSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);
  const [actionInFlight, setActionInFlight] = useState(false);

  const load = useCallback(async () => {
    try {
      const resp = await fetch("/api/hypotheses");
      if (!resp.ok) {
        setError(`API returned ${resp.status}`);
        return;
      }
      const data = (await resp.json()) as { hypotheses: HypothesisSummary[] };
      setItems(data.hypotheses || []);
      setError(null);
      setLastFetch(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "fetch failed");
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [load]);

  async function performAction(
    slug: string,
    action: "graduate" | "reject",
    note?: string
  ) {
    setActionInFlight(true);
    try {
      const resp = await fetch(
        `/api/hypotheses/${encodeURIComponent(slug)}/${action}`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ note: note || undefined }),
        }
      );
      if (!resp.ok) {
        alert(`Failed: ${resp.status}`);
        return;
      }
      await load();
    } finally {
      setActionInFlight(false);
    }
  }

  function handleGraduate(slug: string) {
    if (actionInFlight) return;
    const confirmed = window.confirm(
      `Graduate this hypothesis to its target frame? This appends to the WISDOM frame and archives the hypothesis.`
    );
    if (!confirmed) return;
    performAction(slug, "graduate");
  }

  function handleReject(slug: string) {
    if (actionInFlight) return;
    const note = window.prompt("Reject reason (optional):") ?? "";
    performAction(slug, "reject", note);
  }

  if (items === null && !error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="animate-pulse text-zinc-500 text-sm">
          Loading hypotheses…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div className="flex flex-col items-center justify-center py-12">
          <div className="bg-white/[0.03] p-6 rounded-2xl mb-4 inline-block">
            <RefreshCw size={40} className="text-zinc-600" />
          </div>
          <p className="text-base font-medium text-zinc-300 mb-1">
            Hypothesis API not reachable
          </p>
          <p className="text-sm text-zinc-600 font-mono">{error}</p>
        </div>
      </div>
    );
  }

  const hypotheses = items || [];

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold text-zinc-200 flex items-center gap-2">
            <Sparkles size={18} className="text-purple-400" />
            Hypotheses
          </h2>
          <p className="text-sm text-zinc-400 mt-1 max-w-2xl">
            Pending wisdom candidates from the proactive deriver loop. Graduate
            promotes the claim to a <code className="text-zinc-300">WISDOM/FRAMES</code>{" "}
            file; reject archives it; unreviewed hypotheses age out at 30 days.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-600">
          <RefreshCw size={12} />
          {lastFetch ? `synced ${formatTimestamp(lastFetch.toISOString())}` : "syncing…"}
        </div>
      </div>

      {hypotheses.length === 0 ? (
        <EmptyStateGuide
          section="Hypotheses"
          description="No pending hypotheses. The deriver runs nightly at 03:00 — it scans LEARNING signals and emits up to 3 conservative claims per run when patterns cross the confidence/sample thresholds."
          hideInterview
          daPromptExample="run the deriver loop now"
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {hypotheses.map((h) => (
            <HypothesisCard
              key={h.slug}
              hypothesis={h}
              onGraduate={handleGraduate}
              onReject={handleReject}
            />
          ))}
        </div>
      )}

      <div className="text-[12px] text-zinc-600 font-mono pt-2 border-t border-white/[0.04]">
        source: MEMORY/WISDOM/FRAMES/_hypotheses/ · api: /api/hypotheses · deriver: launchd com.lifeos.deriver
      </div>
    </div>
  );
}
