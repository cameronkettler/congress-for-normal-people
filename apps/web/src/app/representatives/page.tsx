"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  BrainCircuit,
  CheckCircle2,
  CircleDollarSign,
  FileText,
  Loader2,
  Radar,
  UserRound,
} from "lucide-react";

type AuthUser = {
  id: number;
  email: string;
};

type RepresentativeRecord = {
  name: string;
  chamber: string;
  party: string;
  state: string;
  district?: string | null;
  bioguide_id?: string | null;
  official_url?: string | null;
  photo_url?: string | null;
};

type SourceReference = {
  label: string;
  url?: string | null;
  confidence?: string;
  description?: string;
};

type RepresentativeActivityItem = {
  title: string;
  congress_bill_id: string;
  introduced_date?: string | null;
  latest_action: string;
  policy_area: string;
  url?: string | null;
};

type RepresentativeDeepDive = {
  representative: RepresentativeRecord;
  serving_since?: string | null;
  next_election: string;
  committees: string[];
  recent_legislation: RepresentativeActivityItem[];
  finance: { confidence?: string; candidate_matches?: unknown[]; warning?: string };
  money_context: string;
  public_themes: string[];
  watchlist_alignment: string[];
  summary: string;
  caveats: string[];
  sources: SourceReference[];
};

type RepresentativeDeepDiveResponse = {
  items: RepresentativeDeepDive[];
  warning?: string | null;
};

type ProgressEvent = {
  type: "progress";
  step: string;
  representative?: string;
  label: string;
  detail: string;
};

type StreamEvent =
  | ProgressEvent
  | { type: "item"; data: RepresentativeDeepDive }
  | { type: "result"; data: RepresentativeDeepDiveResponse }
  | { type: "error"; detail: string; status?: number };

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const tokenStorageKey = "civic-pulse-token";

type DisplayProgress = {
  key: string;
  label: string;
  detail: string;
  status: "active" | "done";
};

export default function RepresentativesPage() {
  const bootstrapped = useRef(false);
  const itemCount = useRef(0);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [items, setItems] = useState<RepresentativeDeepDive[]>([]);
  const [progress, setProgress] = useState<DisplayProgress[]>([]);
  const [status, setStatus] = useState("Loading representative deep dives");
  const [warning, setWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    void bootstrap();
  }, []);

  async function bootstrap() {
    const token = window.localStorage.getItem(tokenStorageKey);
    if (!token) {
      setStatus("Sign in from the dashboard to view representative deep dives.");
      setLoading(false);
      return;
    }

    try {
      const accountResponse = await fetch(`${apiBase}/api/auth/me`, {
        headers: authHeaders(token),
      });
      if (!accountResponse.ok) {
        window.localStorage.removeItem(tokenStorageKey);
        setStatus("Your session expired. Sign in again from the dashboard.");
        setLoading(false);
        return;
      }

      setUser((await accountResponse.json()) as AuthUser);
      await loadRepresentativeDeepDives(token);
    } catch {
      setStatus("Could not reach the API.");
      setLoading(false);
    }
  }

  async function loadRepresentativeDeepDives(token: string) {
    setLoading(true);
    setWarning(null);
    setItems([]);
    itemCount.current = 0;
    setProgress([]);
    setStatus("Starting representative deep dive");

    try {
      const response = await fetch(`${apiBase}/api/representatives/deep-dive/stream`, {
        headers: authHeaders(token),
      });
      if (!response.ok || !response.body) {
        setWarning("Representative deep dives are temporarily unavailable.");
        setStatus("Representative deep dives unavailable");
        return;
      }

      await readDeepDiveStream(response.body);
      setStatus("Representative deep dive complete");
    } catch {
      setWarning("Representative deep dives are temporarily unavailable.");
      setStatus("Representative deep dives unavailable");
    } finally {
      setLoading(false);
    }
  }

  async function readDeepDiveStream(body: ReadableStream<Uint8Array>) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/}\s*{/g, "}\n{");
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.trim()) continue;
        handleStreamEvent(JSON.parse(line) as StreamEvent);
      }
    }

    if (buffer.trim()) {
      handleStreamEvent(JSON.parse(buffer) as StreamEvent);
    }
  }

  function handleStreamEvent(event: StreamEvent) {
    if (event.type === "progress") {
      setProgress((current) => mergeDisplayProgress(current, event));
      setStatus(event.label);
      if (event.step === "representative_unavailable" && event.representative) {
        const representativeName = event.representative;
        setItems((current) => {
          const merged = mergeDeepDiveItems(current, [fallbackDeepDive(representativeName)]);
          itemCount.current = merged.length;
          return merged;
        });
      }
      return;
    }

    if (event.type === "item") {
      setItems((current) => {
        const merged = mergeDeepDiveItems(current, [event.data]);
        itemCount.current = merged.length;
        return merged;
      });
      return;
    }

    if (event.type === "result") {
      setItems((current) => {
        const merged = mergeDeepDiveItems(current, event.data.items ?? []);
        itemCount.current = merged.length;
        return merged;
      });
      setWarning(event.data.warning ?? null);
      return;
    }

    setWarning(
      itemCount.current > 0
        ? "Some representative deep dives were unavailable; showing the results that completed."
        : event.detail
    );
    setStatus("Representative deep dives unavailable");
  }

  return (
    <main className="min-h-screen bg-[#eef1f4] text-ink">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded bg-civic text-white">
              <BrainCircuit size={21} aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-normal">Representative Deep Dive</h1>
              <p className="text-sm text-slate-600">{user?.email ?? status}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/profile"
              className="focus-ring grid h-8 w-8 place-items-center rounded border border-line text-slate-700"
              aria-label="Profile settings"
              title="Profile settings"
            >
              <UserRound size={15} aria-hidden="true" />
            </Link>
            <Link
              href="/"
              className="focus-ring inline-flex items-center gap-2 rounded border border-line px-3 py-2 text-sm font-medium"
            >
              <ArrowLeft size={15} aria-hidden="true" />
              Dashboard
            </Link>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl gap-5 px-5 py-5 lg:grid-cols-[0.85fr_1.15fr]">
        <ProgressCard progress={progress} loading={loading} status={status} />
        <RepresentativeDeepDiveCard items={items} loading={loading} warning={warning} />
      </section>
    </main>
  );
}

function authHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

function representativeKey(item: RepresentativeDeepDive) {
  const representative = item.representative;
  return normalizedPersonKey(displayPersonName(representative.name)) || representative.bioguide_id || representative.name;
}

function mergeDeepDiveItems(
  current: RepresentativeDeepDive[],
  incoming: RepresentativeDeepDive[],
) {
  const merged = new Map<string, RepresentativeDeepDive>();
  for (const item of current) {
    merged.set(representativeKey(item), item);
  }
  for (const item of incoming) {
    merged.set(representativeKey(item), item);
  }
  return Array.from(merged.values());
}

function normalizedPersonKey(value: string) {
  return value
    .replace(/\[[^\]]+\]/g, " ")
    .replace(/Rep\.|Sen\.|Representative|Senator/gi, " ")
    .replace(/[^a-zA-Z\s]/g, " ")
    .toLowerCase()
    .split(/\s+/)
    .filter((part) => part && !["jr", "sr", "ii", "iii", "iv", "v"].includes(part))
    .sort()
    .join(" ");
}

function fallbackDeepDive(representativeName: string): RepresentativeDeepDive {
  return {
    representative: {
      name: displayPersonName(representativeName),
      chamber: "Unknown",
      party: "Unknown",
      state: "",
      district: null,
      bioguide_id: null,
      official_url: null,
      photo_url: null,
    },
    serving_since: null,
    next_election: "Estimate unavailable",
    committees: [],
    recent_legislation: [],
    finance: {},
    money_context: "Money-context research did not complete for this representative.",
    public_themes: [],
    watchlist_alignment: [],
    summary:
      "This representative was found for your profile, but the deep-dive research step did not complete. Try refreshing the page to rerun the profile.",
    caveats: ["This profile is incomplete because one research step failed."],
    sources: [],
  };
}

function mergeDisplayProgress(current: DisplayProgress[], event: ProgressEvent) {
  if (event.step === "load_profile" || event.step === "resolve_representatives") {
    return upsertProgress(current, {
      key: "prepare",
      label: "Preparing your representative list",
      detail: "Using your saved address to find the right House member and senators.",
      status: event.step === "resolve_representatives" ? "active" : "active",
    });
  }

  if (!event.representative) return current;

  const representativeKey = `representative-${event.representative}`;
  const isDone = event.step === "assemble_deep_dive" || event.step === "representative_unavailable";
  const next = current.map((item) =>
    item.key !== "prepare" && item.status === "active" && item.key !== representativeKey
      ? { ...item, status: "done" as const }
      : item
  );

  return upsertProgress(next, {
    key: representativeKey,
    label:
      event.step === "representative_unavailable"
        ? `Could not complete deep dive for ${displayPersonName(event.representative)}`
        : isDone
          ? `Finished ${displayPersonName(event.representative)}`
          : `Generating deep dive for ${displayPersonName(event.representative)}`,
    detail: representativeProgressDetail(event.step),
    status: isDone ? "done" : "active",
  }).map((item) => (item.key === "prepare" ? { ...item, status: "done" as const } : item));
}

function upsertProgress(current: DisplayProgress[], item: DisplayProgress) {
  const existingIndex = current.findIndex((candidate) => candidate.key === item.key);
  if (existingIndex === -1) return [...current, item];
  return current.map((candidate, index) => (index === existingIndex ? item : candidate));
}

function representativeProgressDetail(step: string) {
  if (step === "generate_public_context") {
    return "Running AI-assisted web research for public themes, money context, and sources.";
  }
  if (step === "retrieve_finance") {
    return "Checking public campaign-finance records.";
  }
  if (step === "representative_unavailable") {
    return "This deep dive could not be completed; showing the other representatives.";
  }
  if (step === "assemble_deep_dive") {
    return "Source review complete.";
  }
  return "Collecting official records and recent legislative activity.";
}

function ProgressCard({
  progress,
  loading,
  status,
}: {
  progress: DisplayProgress[];
  loading: boolean;
  status: string;
}) {
  return (
    <aside className="self-start rounded border border-line bg-white">
      <div className="border-b border-line px-4 py-3">
        <h2 className="text-base font-semibold">Research Status</h2>
        <p className="mt-1 text-sm text-slate-600">{status}</p>
      </div>

      <div className="grid gap-3 p-4">
        {progress.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-slate-600">
            {loading ? <Loader2 className="animate-spin text-civic" size={16} /> : null}
            Waiting to start.
          </div>
        ) : null}

        {progress.map((event) => {
          const isLatest = loading && event.status === "active";
          return (
            <div key={event.key} className="flex gap-3">
              <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border border-line bg-panel">
                {isLatest ? (
                  <Loader2 className="animate-spin text-civic" size={14} />
                ) : (
                  <CheckCircle2 className="text-emerald-600" size={14} />
                )}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold">{event.label}</p>
                <p className="mt-0.5 text-sm leading-5 text-slate-600">{event.detail}</p>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function RepresentativeDeepDiveCard({
  items,
  loading,
  warning,
}: {
  items: RepresentativeDeepDive[];
  loading: boolean;
  warning: string | null;
}) {
  return (
    <section className="self-start rounded border border-line bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <BrainCircuit size={18} aria-hidden="true" />
          <h2 className="text-base font-semibold">Deep Dives</h2>
        </div>
        {loading ? <Loader2 className="animate-spin text-civic" size={16} aria-hidden="true" /> : null}
      </div>

      {warning ? <p className="border-b border-line p-4 text-sm leading-6 text-slate-600">{warning}</p> : null}

      <div className="divide-y divide-line">
        {!loading && items.length === 0 ? (
          <p className="p-4 text-sm leading-6 text-slate-600">
            Save an address to generate deep dives for your House representative and senators.
          </p>
        ) : null}

        {items.map((item, index) => (
          <article key={`${representativeKey(item)}-${index}`} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-3">
                <MemberAvatar name={item.representative.name} photoUrl={item.representative.photo_url} />
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold">{displayPersonName(item.representative.name)}</h3>
                  <p className="mt-1 text-xs text-slate-600">
                    {item.representative.chamber}
                    {item.representative.district ? `, District ${item.representative.district}` : ""}
                  </p>
                </div>
              </div>
              <span className={`rounded border px-2 py-1 text-xs font-semibold ${partyColor(item.representative.party)}`}>
                {partyLabel(item.representative.party)}
              </span>
            </div>

            <p className="mt-3 text-sm leading-6 text-slate-700">
              <LinkedText text={item.summary} />
            </p>

            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <MiniFact label="Serving Since" value={item.serving_since ?? "Unknown"} />
              <MiniFact label="Next Election" value={item.next_election} />
            </div>

            <DeepDiveSection
              icon={<FileText size={14} aria-hidden="true" />}
              title="Recent Legislative Activity"
              empty="No recent sponsored legislation found in the current source set."
              items={item.recent_legislation.map((bill) =>
                `${bill.congress_bill_id ? `${bill.congress_bill_id}: ` : ""}${bill.title}${bill.policy_area ? ` (${bill.policy_area})` : ""}`
              )}
            />

            <DeepDiveSection
              icon={<Radar size={14} aria-hidden="true" />}
              title="Public Themes"
              empty="No clear public themes found yet."
              items={item.public_themes}
            />

            <DeepDiveSection
              icon={<CheckCircle2 size={14} aria-hidden="true" />}
              title="Watchlist Alignment"
              empty="No direct overlap with your watchlist topics found yet."
              items={item.watchlist_alignment}
            />

            <div className="mt-3 rounded border border-line bg-panel p-3">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase text-slate-500">
                <CircleDollarSign size={14} aria-hidden="true" />
                Money Context
              </div>
              <p className="text-sm leading-6 text-slate-700">
                <LinkedText text={moneyContext(item)} />
              </p>
            </div>

            {item.sources.length > 0 ? (
              <section className="mt-3">
                <h4 className="text-xs font-semibold uppercase text-slate-500">Sources</h4>
                <ul className="mt-2 grid gap-2 text-sm leading-5 text-slate-700">
                  {item.sources.map((source) => (
                    <li key={`${source.label}-${source.url ?? ""}`} className="rounded border border-line bg-white p-3">
                      {source.url ? (
                        <a className="font-medium text-civic underline-offset-2 hover:underline" href={source.url}>
                          {source.label}
                        </a>
                      ) : (
                        <span className="font-medium">{source.label}</span>
                      )}
                      {source.description ? (
                        <p className="mt-1 text-slate-600">
                          <LinkedText text={source.description} />
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {item.caveats.length > 0 ? (
              <ul className="mt-3 grid gap-1 text-xs leading-5 text-slate-500">
                {item.caveats.map((caveat) => (
                  <li key={caveat}>
                    <LinkedText text={caveat} />
                  </li>
                ))}
              </ul>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function moneyContext(item: RepresentativeDeepDive) {
  if (item.money_context?.trim()) return item.money_context;
  if (item.finance.warning) return item.finance.warning;
  return "No detailed campaign-finance profile was available from the current source set.";
}

function MemberAvatar({ name, photoUrl }: { name: string; photoUrl?: string | null }) {
  const initials = displayPersonName(name)
    .split(/[,\s]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  if (photoUrl) {
    return (
      <img
        src={photoUrl}
        alt=""
        className="h-14 w-14 shrink-0 rounded-full border border-line object-cover object-top"
        onError={(event) => {
          event.currentTarget.style.display = "none";
        }}
      />
    );
  }

  return (
    <span className="inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-full border border-line bg-white text-xs font-semibold text-slate-500">
      {initials || <UserRound size={16} aria-hidden="true" />}
    </span>
  );
}

function displayPersonName(value: string) {
  const text = value.replace(/\s+/g, " ").trim();
  const bracket = text.match(/\s*(\[[^\]]+\])\s*$/)?.[1] ?? "";
  const withoutBracket = bracket ? text.replace(/\s*\[[^\]]+\]\s*$/, "").trim() : text;
  const titleMatch = withoutBracket.match(/^(Rep\.|Sen\.|Representative|Senator)\s+(.+)$/i);
  const title = titleMatch?.[1] ?? "";
  const name = titleMatch?.[2] ?? withoutBracket;

  if (!name.includes(",")) return [title, name, bracket].filter(Boolean).join(" ");

  const [last, rest] = name.split(",", 2).map((part) => part.trim());
  const suffixes = new Set(["jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"]);
  const restParts = rest.split(/\s+/).filter(Boolean);
  const suffix = restParts.filter((part) => suffixes.has(part.toLowerCase()));
  const given = restParts.filter((part) => !suffixes.has(part.toLowerCase()));
  return [title, ...given, last, ...suffix, bracket].filter(Boolean).join(" ");
}

function MiniFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-panel p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold">
        <LinkedText text={value} />
      </div>
    </div>
  );
}

function DeepDiveSection({
  icon,
  title,
  items,
  empty,
}: {
  icon: ReactNode;
  title: string;
  items: string[];
  empty: string;
}) {
  return (
    <section className="mt-3">
      <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase text-slate-500">
        {icon}
        {title}
      </div>
      {items.length === 0 ? (
        <p className="text-sm leading-6 text-slate-600">{empty}</p>
      ) : (
        <ul className="grid gap-1 text-sm leading-6 text-slate-700">
          {items.map((item) => (
            <li key={item}>
              <LinkedText text={item} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function LinkedText({ text }: { text: string }) {
  const parts = markdownLinkParts(text);
  return (
    <>
      {parts.map((part, index) =>
        part.url ? (
          <a
            key={`${part.url}-${index}`}
            href={part.url}
            className="font-medium text-civic underline-offset-2 hover:underline"
          >
            {part.label}
          </a>
        ) : (
          <span key={`${part.label}-${index}`}>{part.label}</span>
        )
      )}
    </>
  );
}

function markdownLinkParts(text: string) {
  const parts: Array<{ label: string; url?: string }> = [];
  const linkPattern = /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = linkPattern.exec(text)) !== null) {
    const [fullMatch, label, url] = match;
    const prefix = text.slice(lastIndex, match.index);
    const cleanPrefix = prefix.endsWith("(") && text[match.index + fullMatch.length] === ")"
      ? prefix.slice(0, -1)
      : prefix;
    if (cleanPrefix) parts.push({ label: cleanPrefix });
    parts.push({ label, url });
    lastIndex = match.index + fullMatch.length;
    if (text[lastIndex] === ")" && prefix.endsWith("(")) {
      lastIndex += 1;
    }
  }

  const suffix = text.slice(lastIndex);
  if (suffix) parts.push({ label: suffix });
  return parts.length > 0 ? parts : [{ label: text }];
}

function partyColor(party: string) {
  const label = partyLabel(party);
  if (label === "Democrat") return "border-blue-200 bg-blue-50 text-blue-700";
  if (label === "Republican") return "border-red-200 bg-red-50 text-red-700";
  if (label === "Independent") return "border-violet-200 bg-violet-50 text-violet-700";
  return "border-slate-200 bg-white text-slate-600";
}

function partyLabel(party: string) {
  const normalized = party.trim().toLowerCase();
  if (party === "D" || normalized.includes("democrat")) return "Democrat";
  if (party === "R" || normalized.includes("republican")) return "Republican";
  if (party === "I" || normalized.includes("independent")) return "Independent";
  return party || "Unknown";
}
