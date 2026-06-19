"use client";

import { Activity, Bell, CheckCircle2, FileSearch, Loader2, Radar, Search } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

type LookupResponse = {
  bill: {
    congress_bill_id: string;
    title: string;
    summary: string;
    sponsor: string;
    latest_action: string;
    status: string;
    topic: string;
  };
  finance: { patterns?: string[]; top_industries?: string[]; confidence?: string };
  generated_summary: string;
  generated_analysis: string;
  stakeholders: {
    possible_supporters: StakeholderInsight[];
    possible_opponents: StakeholderInsight[];
  };
  caveats: string[];
  confidence: string;
};

type StakeholderInsight = {
  name: string;
  context: string;
};

type MonitoringBill = {
  congress_bill_id: string;
  title: string;
  topic: string;
  summary: string;
  alert_status: string;
};

type Interest = {
  id: number;
  topic: string;
  enabled: boolean;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  const [billId, setBillId] = useState("hr-1234-119");
  const [lookup, setLookup] = useState<LookupResponse | null>(null);
  const [recent, setRecent] = useState<MonitoringBill[]>([]);
  const [interests, setInterests] = useState<Interest[]>([]);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [status, setStatus] = useState("Ready");

  useEffect(() => {
    void Promise.all([loadRecent(), loadInterests()]);
  }, []);

  const enabledCount = useMemo(() => interests.filter((item) => item.enabled).length, [interests]);

  async function loadRecent() {
    const response = await fetch(`${apiBase}/api/monitoring/recent`);
    setRecent(await response.json());
  }

  async function loadInterests() {
    const response = await fetch(`${apiBase}/api/interests`);
    setInterests(await response.json());
  }

  async function submitLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setStatus("Running bill lookup workflow");
    try {
      const response = await fetch(`${apiBase}/api/bills/lookup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bill_id: billId })
      });
      const payload = await response.json();
      if (!response.ok) {
        setLookup(null);
        setStatus(payload.detail ?? "Lookup failed");
        return;
      }
      setLookup(payload);
      setStatus("Report generated");
      await loadRecent();
    } catch {
      setLookup(null);
      setStatus("Could not reach the API");
    } finally {
      setLoading(false);
    }
  }

  async function pollBills() {
    setPolling(true);
    setStatus("Polling Congress.gov feed");
    try {
      const response = await fetch(`${apiBase}/api/monitoring/poll`, { method: "POST" });
      const payload = await response.json();
      setStatus(
        `Poll complete: ${payload.discovered} discovered, ${payload.notifications} notifications queued`
      );
      await loadRecent();
    } finally {
      setPolling(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#eef1f4] text-ink">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded bg-civic text-white">
              <Radar size={21} aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-normal">Civic Pulse</h1>
              <p className="text-sm text-slate-600">Agentic federal legislation intelligence</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-700">
            <Activity size={17} aria-hidden="true" />
            <span>{status}</span>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-5 px-5 py-5 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded border border-line bg-white">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <div className="flex items-center gap-2">
              <FileSearch size={18} aria-hidden="true" />
              <h2 className="text-base font-semibold">Bill Search</h2>
            </div>
            <span className="text-sm text-slate-600">Lookup agent</span>
          </div>

          <form onSubmit={submitLookup} className="flex gap-2 border-b border-line p-4">
            <input
              className="focus-ring min-w-0 flex-1 rounded border border-line px-3 py-2"
              value={billId}
              onChange={(event) => setBillId(event.target.value)}
              aria-label="Bill number"
            />
            <button
              className="focus-ring inline-flex items-center gap-2 rounded bg-civic px-4 py-2 font-medium text-white disabled:opacity-60"
              disabled={loading}
            >
              {loading ? <Loader2 className="animate-spin" size={17} /> : <Search size={17} />}
              Search
            </button>
          </form>

          <div className="grid gap-4 p-4">
            {lookup ? (
              <>
                <div>
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="rounded bg-slate-100 px-2 py-1 text-xs font-semibold uppercase">
                      {lookup.bill.topic}
                    </span>
                    <span className="text-sm text-slate-600">{lookup.bill.status}</span>
                  </div>
                  <h3 className="text-2xl font-semibold tracking-normal">{lookup.bill.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-700">{lookup.bill.summary}</p>
                </div>

                <div className="grid gap-3 md:grid-cols-3">
                  <Metric label="Sponsor" value={lookup.bill.sponsor} />
                  <Metric label="Confidence" value={lookup.confidence} />
                  <Metric label="Finance signal" value={lookup.finance.confidence ?? "low"} />
                </div>

                <section>
                  <h4 className="mb-2 text-sm font-semibold uppercase text-slate-500">Generated Analysis</h4>
                  <p className="rounded border border-line bg-panel p-3 text-sm leading-6">
                    {lookup.generated_analysis}
                  </p>
                </section>

                <div className="grid gap-3 md:grid-cols-2">
                  <StakeholderList
                    title="Related Lobbying Activity"
                    items={lookup.stakeholders.possible_supporters}
                  />
                  <StakeholderList
                    title="Additional Related Activity"
                    items={lookup.stakeholders.possible_opponents}
                  />
                </div>
              </>
            ) : (
              <div className="grid min-h-80 place-items-center rounded border border-dashed border-line bg-panel text-center">
                <div>
                  <FileSearch className="mx-auto mb-3 text-civic" size={34} />
                  <p className="font-medium">Search a bill to generate a source-grounded report.</p>
                  <p className="mt-1 text-sm text-slate-600">Demo data is available without API keys.</p>
                </div>
              </div>
            )}
          </div>
        </div>

        <aside className="grid gap-5">
          <div className="rounded border border-line bg-white">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div className="flex items-center gap-2">
                <Bell size={18} aria-hidden="true" />
                <h2 className="text-base font-semibold">Monitoring</h2>
              </div>
              <button
                onClick={pollBills}
                className="focus-ring inline-flex items-center gap-2 rounded border border-line px-3 py-1.5 text-sm font-medium"
                disabled={polling}
              >
                {polling ? <Loader2 className="animate-spin" size={16} /> : <Radar size={16} />}
                Poll
              </button>
            </div>
            <div className="grid grid-cols-3 border-b border-line text-center text-sm">
              <Metric label="Recent" value={String(recent.length)} compact />
              <Metric label="Topics" value={String(enabledCount)} compact />
              <Metric label="Alerts" value="Queued" compact />
            </div>
            <div className="p-4">
              <h3 className="mb-2 text-sm font-semibold uppercase text-slate-500">Topics</h3>
              <div className="flex flex-wrap gap-2">
                {interests.map((interest) => (
                  <span
                    key={interest.topic}
                    className={`rounded border px-2 py-1 text-xs font-medium ${
                      interest.enabled
                        ? "border-signal bg-emerald-50 text-signal"
                        : "border-line bg-panel text-slate-500"
                    }`}
                  >
                    {interest.topic}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded border border-line bg-white">
            <div className="flex items-center gap-2 border-b border-line px-4 py-3">
              <CheckCircle2 size={18} aria-hidden="true" />
              <h2 className="text-base font-semibold">Recent Bills</h2>
            </div>
            <div className="divide-y divide-line">
              {recent.slice(0, 7).map((bill) => (
                <article key={bill.congress_bill_id} className="p-4">
                  <div className="mb-1 flex items-center justify-between gap-3">
                    <span className="text-xs font-semibold uppercase text-civic">
                      {bill.congress_bill_id}
                    </span>
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{bill.topic}</span>
                  </div>
                  <h3 className="text-sm font-semibold leading-5">{bill.title}</h3>
                  <p className="mt-1 line-clamp-2 text-sm text-slate-600">{bill.summary}</p>
                </article>
              ))}
            </div>
          </div>
        </aside>
      </section>
    </main>
  );
}

function Metric({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className={compact ? "p-3" : "rounded border border-line bg-panel p-3"}>
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold">{value}</div>
    </div>
  );
}

function StakeholderList({ title, items }: { title: string; items: StakeholderInsight[] }) {
  return (
    <section className="rounded border border-line bg-panel p-3">
      <h4 className="mb-2 text-sm font-semibold uppercase text-slate-500">{title}</h4>
      <ul className="grid gap-2 text-sm">
        {items.map((item, index) => (
          <li key={`${item.name}-${index}`} className="leading-5">
            <div className="font-semibold">{item.name}</div>
            <div className="mt-1 text-xs leading-5 text-slate-600">{item.context}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
