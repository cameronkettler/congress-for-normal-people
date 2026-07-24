"use client";

import { AlertCircle, CheckCircle2, ChevronDown, Loader2, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";

type Source = { label: string; url?: string | null; description?: string };
type Bill = { congress_bill_id: string; display_id: string; title: string; status: string };
type Item = { id?: number | null; topic: string; headline: string; change_summary: string; why_it_matters: string; what_happens_next: string; significance: string; confidence: string; bills: Bill[]; sources: Source[]; evidence: Array<{ event_id?: number | null; event_type: string; event_date?: string | null; description: string; source: Source }>; caveats: string[] };
type Briefing = { period_start: string; period_end: string; generated_at: string; topics: string[]; groups: Array<{ topic: string; items: Item[]; has_major_change: boolean }>; total_items: number; is_cached: boolean; warning?: string | null };
type Period = "day" | "week" | "month";

export function PolicyBriefing({ apiBase, token, onSelectBill, onEditTopics }: { apiBase: string; token: string; onSelectBill: (id: string) => void; onEditTopics: () => void }) {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [message, setMessage] = useState("Loading your policy interests");
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState<Period>("week");

  useEffect(() => { void load(false, period); }, [token, period]);

  async function load(force = false, selectedPeriod = period) {
    setLoading(true);
    try {
      if (force) {
        setMessage("Checking Congress.gov for newer actions");
        await fetch(`${apiBase}/api/monitoring/poll`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      }
      const response = await fetch(`${apiBase}/api/briefing/stream?period=${selectedPeriod}&force_refresh=${force}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok || !response.body) throw new Error("Briefing unavailable");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "progress") setMessage(event.message);
          if (event.type === "result") setBriefing(event.data);
        }
      }
    } catch { setMessage("Your briefing is temporarily unavailable."); }
    finally { setLoading(false); }
  }

  return (
    <section className="mx-auto max-w-7xl px-5 pt-5" aria-labelledby="briefing-title">
      <div className="rounded border border-line bg-white">
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line p-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-civic">Your policy briefing</p>
            <h2 id="briefing-title" className="mt-1 text-2xl font-semibold">What changed in Congress {period === "day" ? "today" : period === "week" ? "this week" : "this month"}</h2>
            {briefing ? <p className="mt-1 text-sm font-medium text-slate-700">Updated {formatDateTime(briefing.generated_at)}</p> : null}
            <p className="mt-0.5 text-sm text-slate-600">Changes from the past {period === "day" ? "24 hours" : period === "week" ? "7 days" : "30 days"}</p>
            <p className="mt-1 text-sm text-slate-600">{briefing?.topics.length ? `Covering ${briefing.topics.join(", ")}` : "Built from your enabled policy interests"}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="sr-only" htmlFor="briefing-period">Briefing timeframe</label>
            <select id="briefing-period" value={period} onChange={(event) => setPeriod(event.target.value as Period)} className="focus-ring rounded border border-line bg-white px-3 py-2 text-sm font-medium">
              <option value="day">Past 24 hours</option><option value="week">Past 7 days</option><option value="month">Past 30 days</option>
            </select>
            <button onClick={onEditTopics} className="focus-ring inline-flex items-center gap-2 rounded border border-line px-3 py-2 text-sm font-medium"><Settings2 size={15} />Edit interests</button>
            <button onClick={() => void load(true)} disabled={loading} className="focus-ring rounded border border-line px-3 py-2 text-sm font-medium disabled:opacity-60">Check for newer changes</button>
          </div>
        </header>
        <div aria-live="polite">
          {loading ? <div className="flex items-center gap-2 p-5 text-sm text-slate-600"><Loader2 className="animate-spin text-civic" size={17} />{message}</div> : null}
          {!loading && briefing?.warning ? <div className="flex gap-2 border-b border-line bg-amber-50 p-4 text-sm text-amber-900"><AlertCircle size={17} className="shrink-0" />{briefing.warning}</div> : null}
          {!loading && briefing?.total_items === 0 && !briefing.warning ? <p className="p-5 text-sm text-slate-600">No major changes across your topics.</p> : null}
        </div>
        <div className="divide-y divide-line">
          {briefing?.groups.map(group => (
            <details key={group.topic} className="group p-4" open={group.items.length > 0}>
              <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded py-1">
                <h3 id={`topic-${group.topic}`} className="text-lg font-semibold">{group.topic}</h3>
                <span className="flex items-center gap-3">
                  <span className="text-sm font-medium text-slate-500">{group.items.length === 0 ? "No developments" : `${group.items.length} ${group.items.length === 1 ? "update" : "updates"}`}</span>
                  <ChevronDown className="text-slate-500 transition-transform group-open:rotate-180" size={18} aria-hidden="true" />
                </span>
              </summary>
              <div className="mt-3 grid gap-3" role="region" aria-labelledby={`topic-${group.topic}`}>
                {group.items.length ? group.items.map(item => <BriefingItem key={`${item.topic}-${item.headline}`} item={item} onSelectBill={onSelectBill} />) : <p className="rounded border border-dashed border-line bg-panel p-4 text-sm text-slate-600">No meaningful {group.topic.toLowerCase()} developments found in this period.</p>}
              </div>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

function BriefingItem({ item, onSelectBill }: { item: Item; onSelectBill: (id: string) => void }) {
  const primaryEvidence = item.evidence[0];
  const primaryBill = item.bills[0];
  return <article className="rounded border border-line bg-panel p-4">
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-semibold uppercase"><span className="rounded bg-white px-2 py-1">{significanceLabel(item.significance)}</span><span className="text-slate-500">{item.topic}</span></div>
    <h4 className="mt-3 text-lg font-semibold leading-6">{item.headline}</h4>
    <p className="mt-1 text-sm font-medium text-slate-600">{primaryEvidence?.event_date ? formatActionDate(primaryEvidence.event_date) : "Action date unavailable"} · {primaryBill?.display_id}</p>
    <BriefingField label="What changed" value={item.change_summary} />
    <BriefingField label="Why it matters" value={item.why_it_matters} />
    <BriefingField label="What happens next" value={item.what_happens_next} />
    {primaryBill ? <div className="mt-4 text-sm"><span className="text-slate-600">Underlying legislation: </span><button onClick={() => onSelectBill(primaryBill.congress_bill_id)} className="focus-ring font-medium text-civic underline-offset-2 hover:underline">{primaryBill.display_id}</button><button onClick={() => onSelectBill(primaryBill.congress_bill_id)} className="focus-ring ml-4 font-semibold text-civic">View full analysis →</button></div> : null}
    <details className="mt-3 rounded border border-line bg-white p-3"><summary className="focus-ring flex cursor-pointer list-none items-center gap-2 text-sm font-semibold"><ChevronDown size={15} />Evidence and sources</summary><p className="mt-2 text-xs text-slate-500">Source confidence: {item.confidence}</p><ul className="mt-2 grid gap-2 text-sm">{item.evidence.map((evidence, index) => <li key={`${evidence.event_id}-${index}`}><CheckCircle2 className="mr-1 inline text-emerald-600" size={14} />{evidence.description}{evidence.source.url ? <> — <a href={evidence.source.url} className="text-civic underline" target="_blank" rel="noreferrer">{evidence.source.label}</a></> : ` — ${evidence.source.label}`}</li>)}</ul>{item.caveats.length ? <p className="mt-2 text-xs text-slate-500">Caveat: {item.caveats.join(" ")}</p> : null}</details>
  </article>;
}

function BriefingField({ label, value }: { label: string; value: string }) { return <div className="mt-3"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-1 text-sm leading-6 text-slate-700">{value}</p></div>; }
function significanceLabel(value: string) { return value === "major" ? "Major development" : value === "notable" ? "Notable development" : "Procedural update"; }
function formatActionDate(value: string) { return new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(value)); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago", timeZoneName: "short" }).format(new Date(value)); }
