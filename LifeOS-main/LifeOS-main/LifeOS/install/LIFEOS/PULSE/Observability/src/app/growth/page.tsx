"use client";
import { useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  Cell,
  CartesianGrid,
} from "recharts";
import { TrendingUp, Users, Mail, Video, Globe, type LucideIcon } from "lucide-react";

interface GrowthData {
  generatedAt: string;
  newsletter: {
    totalActive: number;
    free: number;
    premium: number;
    newToday: number;
    new7d: number;
    new30d: number;
    avgPerDay7d: number;
    avgPerDay30d: number;
    openRate: number;
    clickRate: number;
    dailyTrend: { date: string; count: number }[];
    todayChannels: Record<string, number>;
    channels30d: Record<string, number>;
  } | null;
  youtube: {
    subscribers: number;
    totalViews: number;
    videoCount: number;
    recentVideos: { title: string; views: number; likes: number; comments: number }[];
  } | null;
  web: { range: string; pageviews: number; visitors: number } | null;
  errors: string[];
}

const GREEN = "#34D399";
const GOLD = "#E0A458";
const BLUE = "#7DD3FC";
const RED = "#F87B7B";
const PURPLE = "#B794F4";
const CHANNEL_COLORS = [GREEN, BLUE, GOLD, PURPLE, RED, "#2DD4BF"];

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
function mmdd(d: string): string {
  const p = d.split("-");
  return p.length === 3 ? `${p[1]}/${p[2]}` : d;
}

function Hero({ nl }: { nl: NonNullable<GrowthData["newsletter"]> }) {
  return (
    <section className="telos-card" style={{ cursor: "default", borderLeft: `3px solid ${GREEN}` }}>
      <div className="flex items-start gap-6 flex-wrap">
        <TrendingUp className="w-10 h-10 shrink-0" color={GREEN} />
        <div className="flex-1 min-w-0">
          <div className="text-xs uppercase tracking-widest muted mb-2" style={{ color: GREEN }}>
            Audience Growth
          </div>
          <div className="flex items-baseline gap-8 flex-wrap">
            <div>
              <div className="text-xs uppercase tracking-wider muted">New subscribers today</div>
              <div className="text-5xl lg:text-6xl font-medium tabular-nums leading-tight" style={{ color: GREEN }}>
                {nl.newToday}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider muted">Total active</div>
              <div className="text-3xl lg:text-4xl font-medium tabular-nums leading-tight">
                {fmt(nl.totalActive)}
              </div>
              <div className="text-xs mt-1 muted">
                {fmt(nl.free)} free · {nl.premium.toLocaleString()} premium
              </div>
            </div>
            <div className="text-sm space-y-1 muted">
              <div>
                <span className="tabular-nums" style={{ color: BLUE }}>{nl.new7d}</span> in 7d ·{" "}
                {nl.avgPerDay7d}/day
              </div>
              <div>
                <span className="tabular-nums" style={{ color: BLUE }}>{nl.new30d.toLocaleString()}</span> in 30d ·{" "}
                {nl.avgPerDay30d}/day
              </div>
              <div className="text-xs">
                Open {nl.openRate}% · Click {nl.clickRate}%
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function TrendChart({ nl }: { nl: NonNullable<GrowthData["newsletter"]> }) {
  const data = nl.dailyTrend.map((d) => ({ ...d, label: mmdd(d.date) }));
  return (
    <section>
      <h2 className="text-sm font-medium uppercase tracking-widest muted mb-4" style={{ color: GREEN }}>
        New Subscribers · 30 Days
      </h2>
      <div className="telos-card" style={{ cursor: "default", borderLeft: `3px solid ${GREEN}` }}>
        <div style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ left: 0, right: 12, top: 8 }}>
              <defs>
                <linearGradient id="subGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={GREEN} stopOpacity={0.45} />
                  <stop offset="100%" stopColor={GREEN} stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1A2A4D" vertical={false} />
              <XAxis dataKey="label" stroke="#6B80AB" fontSize={10} interval={4} tickLine={false} />
              <YAxis stroke="#6B80AB" fontSize={10} width={32} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{
                  background: "#0F1A33",
                  border: "1px solid #1A2A4D",
                  borderRadius: 8,
                  fontSize: 12,
                  color: "#E8EFFF",
                }}
                formatter={(v: number) => [`${v} new`, "Subscribers"]}
              />
              <Area type="monotone" dataKey="count" stroke={GREEN} strokeWidth={2} fill="url(#subGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}

function Channels({ nl }: { nl: NonNullable<GrowthData["newsletter"]> }) {
  const rows = Object.entries(nl.channels30d).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const total = rows.reduce((s, [, v]) => s + v, 0) || 1;
  const today = Object.entries(nl.todayChannels).sort((a, b) => b[1] - a[1]);
  if (rows.length === 0) return null;
  return (
    <section>
      <h2 className="text-sm font-medium uppercase tracking-widest muted mb-4" style={{ color: BLUE }}>
        Where They Came From · 30 Days
      </h2>
      <div className="telos-card" style={{ cursor: "default", borderLeft: `3px solid ${BLUE}` }}>
        <div style={{ height: 200 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows.map(([name, count]) => ({ name, count }))} layout="vertical" margin={{ left: 20, right: 40 }}>
              <XAxis type="number" stroke="#6B80AB" fontSize={11} tickLine={false} />
              <YAxis type="category" dataKey="name" stroke="#6B80AB" fontSize={11} width={120} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ background: "#0F1A33", border: "1px solid #1A2A4D", borderRadius: 8, fontSize: 12, color: "#E8EFFF" }}
                formatter={(v: number) => [`${v} (${((v / total) * 100).toFixed(0)}%)`, "Subs"]}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {rows.map((_, i) => (
                  <Cell key={i} fill={CHANNEL_COLORS[i % CHANNEL_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        {today.length > 0 && (
          <div className="text-xs muted mt-4 pt-4" style={{ borderTop: "1px solid #1A2A4D" }}>
            Today: {today.map(([k, v]) => `${k} ${v}`).join(" · ")}
          </div>
        )}
      </div>
    </section>
  );
}

function Stat({ icon: Icon, accent, label, value, sub }: { icon: LucideIcon; accent: string; label: string; value: string; sub?: string }) {
  return (
    <div className="telos-card" style={{ cursor: "default", borderLeft: `3px solid ${accent}` }}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 shrink-0" color={accent} />
        <h3 className="text-xs uppercase tracking-wider muted">{label}</h3>
      </div>
      <div className="text-2xl font-medium tabular-nums" style={{ color: accent }}>{value}</div>
      {sub && <div className="text-xs muted mt-1">{sub}</div>}
    </div>
  );
}

function NotConnected({ icon: Icon, accent, label, envVar, note }: { icon: LucideIcon; accent: string; label: string; envVar: string; note: string }) {
  return (
    <div className="telos-card" style={{ cursor: "default", borderLeft: `3px solid #2A3A5D`, opacity: 0.75 }}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 shrink-0" color={accent} />
        <h3 className="text-xs uppercase tracking-wider muted">{label}</h3>
      </div>
      <div className="text-sm muted">Not connected</div>
      <div className="text-xs muted mt-1">
        {note} Set <code style={{ color: accent }}>{envVar}</code> in <code>~/.claude/.env</code>.
      </div>
    </div>
  );
}

export default function GrowthPage() {
  const [data, setData] = useState<GrowthData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/life/growth")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="p-8 max-w-5xl mx-auto">
        <div className="telos-card" style={{ cursor: "default", borderLeft: `3px solid ${RED}` }}>
          <h2 className="font-medium" style={{ color: RED }}>Failed to load growth</h2>
          <p className="text-sm" style={{ color: "#FCA5A5" }}>{error}</p>
        </div>
      </div>
    );
  }
  if (!data) return <div className="p-8 text-sm muted">Loading Growth…</div>;

  const nl = data.newsletter;

  return (
    <div className="p-6 lg:p-8 max-w-[1920px] mx-auto space-y-6">
      {nl ? (
        <>
          <Hero nl={nl} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <TrendChart nl={nl} />
            <Channels nl={nl} />
          </div>
        </>
      ) : (
        <div className="telos-card" style={{ cursor: "default", borderLeft: `3px solid ${RED}` }}>
          <h2 className="font-medium" style={{ color: RED }}>Newsletter not connected</h2>
          <p className="text-sm muted">Set BEEHIIV_API_KEY and BEEHIIV_PUB_ID in ~/.claude/.env.</p>
        </div>
      )}

      <h2 className="text-sm font-medium uppercase tracking-widest muted">Other Channels</h2>
      <div className="prob-grid">
        {data.youtube ? (
          <Stat
            icon={Video}
            accent={RED}
            label="YouTube"
            value={fmt(data.youtube.subscribers)}
            sub={`${fmt(data.youtube.totalViews)} views · ${data.youtube.videoCount} videos`}
          />
        ) : (
          <NotConnected icon={Video} accent={RED} label="YouTube" envVar="GOOGLE_API_KEY" note="Enable YouTube Data API v3 on this key's project." />
        )}
        {data.web ? (
          <Stat
            icon={Globe}
            accent={GOLD}
            label={`Web traffic (${data.web.range})`}
            value={fmt(data.web.pageviews)}
            sub={`${fmt(data.web.visitors)} visitors`}
          />
        ) : (
          <NotConnected icon={Globe} accent={GOLD} label="Web traffic" envVar="CLOUDFLARE_API_TOKEN" note="Needs Account Analytics Read scope." />
        )}
        {nl && (
          <Stat
            icon={Mail}
            accent={PURPLE}
            label="List health"
            value={`${nl.openRate}%`}
            sub={`open · ${nl.clickRate}% click · ${nl.premium.toLocaleString()} premium`}
          />
        )}
        {nl && (
          <Stat icon={Users} accent={GREEN} label="Free / Premium" value={`${fmt(nl.free)}`} sub={`free · ${nl.premium.toLocaleString()} premium`} />
        )}
      </div>

      <div className="text-xs muted pt-2">
        Updated {new Date(data.generatedAt).toLocaleString("en-US", { timeZone: "America/Los_Angeles" })} PT
        {data.errors.length > 0 && <span> · {data.errors.length} source(s) need credentials</span>}
      </div>
    </div>
  );
}
