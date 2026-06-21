"use client";

import Link from "next/link";
import {
  Activity,
  Bell,
  BrainCircuit,
  CheckCircle2,
  CircleDollarSign,
  FileSearch,
  Flame,
  LogOut,
  Loader2,
  Plus,
  Radar,
  Search,
  ShieldCheck,
  UserRound
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

type LookupResponse = {
  bill: {
    congress_bill_id: string;
    title: string;
    summary: string;
    sponsor: string;
    sponsor_bioguide_id?: string | null;
    sponsor_photo_url?: string | null;
    latest_action: string;
    status: string;
    topic: string;
  };
  sponsor?: {
    name?: string;
    party?: string;
    state?: string;
    photo_url?: string | null;
  };
  finance: { patterns?: string[]; top_industries?: string[]; confidence?: string };
  generated_summary: string;
  generated_analysis: string;
  analysis_sections?: Record<string, string>;
  stakeholders: {
    possible_supporters: StakeholderInsight[];
    possible_opponents: StakeholderInsight[];
  };
  caveats: string[];
  confidence: string;
  representative_context?: RepresentativeBillSignal[];
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

type RepresentativeBillSignal = {
  representative: RepresentativeRecord;
  signal: string;
  detail: string;
  ai_context?: string | null;
  ai_context_label?: string;
  sources?: SourceReference[];
};

type SourceReference = {
  label: string;
  url?: string | null;
  confidence?: string;
  description?: string;
};

type StakeholderInsight = {
  name: string;
  context: string;
  takeaway?: string;
  issue_area?: string | null;
  registrant_name?: string | null;
  filing_year?: number | null;
  filing_type?: string | null;
  recency?: string;
  relevance?: string;
};

type HotTopicBill = {
  congress_bill_id: string;
  title: string;
  topic: string;
  reason: string;
  year: number;
};

type HotTopicsResponse = {
  items: HotTopicBill[];
};

type MonitoringBill = {
  congress_bill_id: string;
  title: string;
  topic: string;
  summary: string;
  alert_status: string;
};

type MonitoringRecentResponse = {
  items: MonitoringBill[];
  warning?: string | null;
};

type Interest = {
  id: number;
  topic: string;
  enabled: boolean;
};

type AuthUser = {
  id: number;
  email: string;
};

type AuthResponse = {
  token: string;
  user: AuthUser;
};

type UserProfile = {
  street_address: string;
  address_line_2?: string;
  city: string;
  state: string;
  zip_code: string;
  congressional_district: string;
  location_confidence: string;
  representatives: RepresentativeRecord[];
  warning?: string | null;
};

type RegistrationPayload = {
  email: string;
  password: string;
  street_address?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
};

type PreviousLookup = {
  congress_bill_id: string;
  title: string;
  topic: string;
  summary: string;
  cachedAt: number;
};

type LookupProgress = {
  step?: string;
  message: string;
  detail?: string;
};

type LookupStreamEvent =
  | (LookupProgress & { type: "progress" })
  | { type: "result"; data: LookupResponse }
  | { type: "error"; status?: number; detail?: string; error?: string; provider?: string };

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const tokenStorageKey = "civic-pulse-token";
const lastLookupStorageKey = "civic-pulse-last-lookup";
const previousLookupsStorageKey = "civic-pulse-previous-lookups";

export default function Home() {
  const [billId, setBillId] = useState("");
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [lookup, setLookup] = useState<LookupResponse | null>(null);
  const [watchlistBills, setWatchlistBills] = useState<MonitoringBill[]>([]);
  const [hotTopics, setHotTopics] = useState<HotTopicBill[]>([]);
  const [interests, setInterests] = useState<Interest[]>([]);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [representativeCheck, setRepresentativeCheck] = useState<RepresentativeBillSignal | null>(null);
  const [representativeChecking, setRepresentativeChecking] = useState(false);
  const [newTopic, setNewTopic] = useState("");
  const [status, setStatus] = useState("Ready");
  const [lookupProgress, setLookupProgress] = useState<LookupProgress[]>([]);
  const [previousLookups, setPreviousLookups] = useState<PreviousLookup[]>([]);

  useEffect(() => {
    void bootstrap();
  }, []);

  const enabledCount = useMemo(() => interests.filter((item) => item.enabled).length, [interests]);
  const enabledTopics = useMemo(
    () => new Set(interests.filter((item) => item.enabled).map((item) => item.topic.toLowerCase())),
    [interests]
  );
  const visibleWatchlistBills = useMemo(
    () =>
      watchlistBills
        .filter((bill) => enabledTopics.size === 0 || enabledTopics.has(bill.topic.toLowerCase()))
        .slice(0, 5),
    [watchlistBills, enabledTopics]
  );

  async function bootstrap() {
    await loadWatchlistBills();
    await loadHotTopics();
    restoreCachedLookup();
    restorePreviousLookups();
    const storedToken = window.localStorage.getItem(tokenStorageKey);
    if (!storedToken) {
      setAuthChecked(true);
      return;
    }

    try {
      const response = await fetch(`${apiBase}/api/auth/me`, {
        headers: authHeaders(storedToken)
      });
      if (!response.ok) {
        window.localStorage.removeItem(tokenStorageKey);
        setAuthChecked(true);
        return;
      }
      const account = (await response.json()) as AuthUser;
      setAuthToken(storedToken);
      setUser(account);
      await Promise.all([loadInterests(storedToken), loadProfile(storedToken)]);
    } finally {
      setAuthChecked(true);
    }
  }

  async function loadInterests(token = authToken) {
    if (!token) return;
    const response = await fetch(`${apiBase}/api/interests`, {
      headers: authHeaders(token)
    });
    if (response.status === 401) {
      signOut();
      return;
    }
    setInterests(await response.json());
  }

  async function loadProfile(token = authToken) {
    if (!token) return;
    const response = await fetch(`${apiBase}/api/profile`, {
      headers: authHeaders(token)
    });
    if (response.ok) {
      setProfile(await response.json());
    }
  }

  async function saveProfileLocation(payload: {
    street_address: string;
    address_line_2: string;
    city: string;
    state: string;
    zip_code: string;
  }) {
    if (!authToken) return;
    setStatus("Resolving your district");
    const response = await fetch(`${apiBase}/api/profile/location`, {
      method: "PUT",
      headers: authHeaders(authToken),
      body: JSON.stringify(payload)
    });
    const body = await response.json();
    if (!response.ok) {
      setStatus(body.detail ?? "Could not resolve that address");
      return;
    }
    setProfile(body);
    setStatus("Profile updated");
  }

  async function toggleInterest(interest: Interest) {
    if (!authToken) return;
    const next = !interest.enabled;
    setInterests((current) =>
      current.map((item) => (item.id === interest.id ? { ...item, enabled: next } : item))
    );
    try {
      const response = await fetch(`${apiBase}/api/interests/${encodeURIComponent(interest.topic)}`, {
        method: "PATCH",
        headers: authHeaders(authToken),
        body: JSON.stringify({ enabled: next })
      });
      if (!response.ok) {
        await loadInterests();
        setStatus("Could not update alert topic");
        return;
      }
      setStatus(`${interest.topic} ${next ? "enabled" : "disabled"} for monitoring`);
    } catch {
      await loadInterests();
      setStatus("Could not reach the API");
    }
  }

  async function addInterest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authToken) return;
    const topic = newTopic.trim();
    if (!topic) return;

    setStatus(`Adding ${topic} to monitoring`);
    try {
      const response = await fetch(`${apiBase}/api/interests/${encodeURIComponent(topic)}`, {
        method: "PATCH",
        headers: authHeaders(authToken),
        body: JSON.stringify({ enabled: true })
      });
      if (!response.ok) {
        setStatus("Could not add alert topic");
        return;
      }
      setNewTopic("");
      await loadInterests();
      setStatus(`${topic} enabled for monitoring`);
    } catch {
      setStatus("Could not reach the API");
    }
  }

  async function submitAuth(payload: RegistrationPayload, mode: "login" | "register") {
    setStatus(mode === "login" ? "Signing in" : "Creating account");
    const response = await fetch(`${apiBase}/api/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const body = await response.json();
    if (!response.ok) {
      setStatus(body.detail ?? "Authentication failed");
      return;
    }

    const auth = body as AuthResponse;
    window.localStorage.setItem(tokenStorageKey, auth.token);
    setAuthToken(auth.token);
    setUser(auth.user);
    setStatus("Signed in");
    await Promise.all([loadInterests(auth.token), loadProfile(auth.token)]);
  }

  async function loadWatchlistBills() {
    try {
      const response = await fetch(`${apiBase}/api/monitoring/recent`);
      if (!response.ok) {
        setWatchlistBills([]);
        return;
      }
      const payload = (await response.json()) as MonitoringBill[] | MonitoringRecentResponse;
      setWatchlistBills(Array.isArray(payload) ? payload : payload.items ?? []);
    } catch {
      setWatchlistBills([]);
    }
  }

  async function loadHotTopics() {
    try {
      const response = await fetch(`${apiBase}/api/monitoring/hot-topics`);
      if (!response.ok) {
        setHotTopics([]);
        return;
      }
      const payload = (await response.json()) as HotTopicsResponse;
      setHotTopics(payload.items ?? []);
    } catch {
      setHotTopics([]);
    }
  }

  function signOut() {
    window.localStorage.removeItem(tokenStorageKey);
    window.localStorage.removeItem(lastLookupStorageKey);
    setAuthToken(null);
    setUser(null);
    setInterests([]);
    setProfile(null);
    setStatus("Signed out");
  }

  async function submitLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runLookup(billId);
  }

  async function runLookup(query: string) {
    const nextBillId = query.trim();
    if (!nextBillId) return;
    setBillId(nextBillId);
    setLoading(true);
    setLookupProgress([]);
    setStatus("Running bill lookup workflow");
    try {
      const response = await fetch(`${apiBase}/api/bills/lookup/stream`, {
        method: "POST",
        headers: authToken ? authHeaders(authToken) : { "Content-Type": "application/json" },
        body: JSON.stringify({ bill_id: nextBillId })
      });
      if (!response.ok || !response.body) {
        setLookup(null);
        setStatus("Lookup failed");
        return;
      }
      const payload = await readLookupStream(response.body);
      if (!payload) return;
      setLookup(payload);
      setRepresentativeCheck(null);
      cacheLookup(nextBillId, payload);
      setStatus("Report generated");
      await loadWatchlistBills();
      await loadHotTopics();
    } catch (error) {
      setLookup(null);
      if (!(error instanceof Error) || error.message !== "LOOKUP_STREAM_ERROR") {
        setStatus("Could not reach the API");
      }
    } finally {
      setLoading(false);
    }
  }

  async function readLookupStream(body: ReadableStream<Uint8Array>) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const payload = handleLookupStreamLine(line);
        if (payload) return payload;
      }
    }

    if (buffer.trim()) {
      const payload = handleLookupStreamLine(buffer);
      if (payload) return payload;
    }

    setLookup(null);
    setStatus("Lookup ended before a report was generated");
    return null;
  }

  function handleLookupStreamLine(line: string): LookupResponse | null {
    if (!line.trim()) return null;
    const event = JSON.parse(line) as LookupStreamEvent;
    if (event.type === "progress") {
      setLookupProgress((items) => [...items, event].slice(-6));
      setStatus(event.message);
      return null;
    }
    if (event.type === "error") {
      setLookup(null);
      setStatus(event.detail ?? event.error ?? "Lookup failed");
      throw new Error("LOOKUP_STREAM_ERROR");
    }
    return event.data;
  }

  function restoreCachedLookup() {
    const cached = window.localStorage.getItem(lastLookupStorageKey);
    if (!cached) return;
    try {
      const payload = JSON.parse(cached) as { billId?: string; lookup?: LookupResponse };
      if (payload.lookup) {
        setLookup(payload.lookup);
        if (payload.billId) {
          setBillId(payload.billId);
        }
      }
    } catch {
      window.localStorage.removeItem(lastLookupStorageKey);
    }
  }

  function cacheLookup(nextBillId: string, payload: LookupResponse) {
    window.localStorage.setItem(
      lastLookupStorageKey,
      JSON.stringify({ billId: nextBillId, lookup: payload, cachedAt: Date.now() })
    );
    rememberPreviousLookup(payload);
  }

  function restorePreviousLookups() {
    const cached = window.localStorage.getItem(previousLookupsStorageKey);
    if (!cached) return;
    try {
      const payload = JSON.parse(cached) as PreviousLookup[];
      setPreviousLookups(Array.isArray(payload) ? payload.slice(0, 6) : []);
    } catch {
      window.localStorage.removeItem(previousLookupsStorageKey);
    }
  }

  function rememberPreviousLookup(payload: LookupResponse) {
    const item: PreviousLookup = {
      congress_bill_id: payload.bill.congress_bill_id,
      title: payload.bill.title,
      topic: payload.bill.topic,
      summary: payload.generated_summary,
      cachedAt: Date.now()
    };
    setPreviousLookups((current) => {
      const next = [
        item,
        ...current.filter((existing) => existing.congress_bill_id !== item.congress_bill_id)
      ].slice(0, 6);
      window.localStorage.setItem(previousLookupsStorageKey, JSON.stringify(next));
      return next;
    });
  }

  function namesReferToSamePerson(left: string, right: string) {
    const normalizedLeft = normalizedPersonName(left);
    const normalizedRight = normalizedPersonName(right);
    if (!normalizedLeft || !normalizedRight) return false;
    const leftParts = new Set(normalizedLeft.split(" "));
    const rightParts = new Set(normalizedRight.split(" "));
    return (
      normalizedLeft === normalizedRight ||
      normalizedLeft.includes(normalizedRight) ||
      normalizedRight.includes(normalizedLeft) ||
      setsMatch(leftParts, rightParts) ||
      setContainsAll(leftParts, rightParts) ||
      setContainsAll(rightParts, leftParts)
    );
  }

  function normalizedPersonName(value: string) {
    return value
      .replace(/\[[^\]]+\]/g, " ")
      .replace(/Rep\.|Sen\.|Representative|Senator/gi, " ")
      .replace(/[^a-zA-Z\s]/g, " ")
      .toLowerCase()
      .split(/\s+/)
      .filter((part) => part && !["jr", "sr", "ii", "iii", "iv"].includes(part))
      .sort()
      .join(" ");
  }

  function setsMatch(left: Set<string>, right: Set<string>) {
    return left.size > 0 && left.size === right.size && setContainsAll(left, right);
  }

  function setContainsAll(left: Set<string>, right: Set<string>) {
    if (right.size < 2) return false;
    for (const item of right) {
      if (!left.has(item)) return false;
    }
    return true;
  }

  async function runRepresentativeCheck(representativeName: string) {
    const name = representativeName.trim();
    if (!authToken || !lookup || !name) return;
    const cachedSignal = lookup.representative_context?.find((signal) =>
      namesReferToSamePerson(signal.representative.name, name)
    );
    if (cachedSignal) {
      setRepresentativeCheck(cachedSignal);
      setStatus("Representative context loaded from current report");
      return;
    }

    setRepresentativeChecking(true);
    setStatus(`Checking ${name}`);
    try {
      const response = await fetch(`${apiBase}/api/bills/representative-context`, {
        method: "POST",
        headers: authHeaders(authToken),
        body: JSON.stringify({ bill: lookup.bill, representative_name: name })
      });
      const payload = await response.json();
      if (!response.ok) {
        setStatus(payload.detail ?? "Representative check failed");
        return;
      }
      setRepresentativeCheck(payload);
      setStatus("Representative context generated");
    } catch {
      setStatus("Could not reach the API");
    } finally {
      setRepresentativeChecking(false);
    }
  }

  async function pollBills() {
    if (!authToken) return;
    setPolling(true);
    setStatus("Polling Congress.gov feed");
    try {
      const response = await fetch(`${apiBase}/api/monitoring/poll`, {
        method: "POST",
        headers: authHeaders(authToken)
      });
      const payload = await response.json();
      setStatus(
        `Watchlist refreshed: ${payload.discovered} new bills found`
      );
      await loadWatchlistBills();
      await loadHotTopics();
    } finally {
      setPolling(false);
    }
  }

  if (!authChecked) {
    return <LoadingScreen />;
  }

  if (!user) {
    return <LoginPage status={status} onSubmit={submitAuth} />;
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
              <h1 className="text-xl font-semibold tracking-normal">Congress For Normal People</h1>
              <p className="text-sm text-slate-600">Agentic federal legislation intelligence</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-700">
            <Activity size={17} aria-hidden="true" />
            <span>{status}</span>
            <span className="hidden text-slate-400 md:inline">|</span>
            <span className="hidden md:inline">{user.email}</span>
            <Link
              href="/representatives"
              className="focus-ring grid h-8 w-8 place-items-center rounded border border-line text-slate-700"
              aria-label="Representative deep dive"
              title="Representative deep dive"
            >
              <BrainCircuit size={15} aria-hidden="true" />
            </Link>
            <Link
              href="/profile"
              className="focus-ring grid h-8 w-8 place-items-center rounded border border-line text-slate-700"
              aria-label="Profile settings"
              title="Profile settings"
            >
              <UserRound size={15} aria-hidden="true" />
            </Link>
            <button
              onClick={signOut}
              className="focus-ring inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-xs font-medium"
            >
              <LogOut size={14} aria-hidden="true" />
              Sign out
            </button>
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
              placeholder="Enter a House bill number like HR-22"
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

          {loading && lookupProgress.length > 0 ? (
            <LookupProgressList items={lookupProgress} />
          ) : null}

          <div className="grid gap-4 p-4">
            {lookup ? (
              <>
                <div>
                  <div className="mb-3 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-normal text-slate-600">
                    <span className="rounded border border-line bg-white px-2 py-1">{lookup.bill.topic}</span>
                    <span>{lookup.bill.status}</span>
                    <span>{lookup.bill.congress_bill_id}</span>
                  </div>
                  <h3 className="text-2xl font-semibold tracking-normal">{lookup.bill.title}</h3>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-700">
                    {lookup.generated_summary}
                  </p>
                </div>

                <SponsorCard sponsor={lookup.bill.sponsor} photoUrl={lookup.bill.sponsor_photo_url ?? lookup.sponsor?.photo_url} />
                <ReportCoverageCard lookup={lookup} />

                <section>
                  <h4 className="mb-2 text-sm font-semibold uppercase text-slate-500">Political Read</h4>
                  {lookup.analysis_sections && Object.keys(lookup.analysis_sections).length > 0 ? (
                    <div className="grid gap-2">
                      {Object.entries(lookup.analysis_sections).map(([title, body]) => (
                        <section key={title} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
                          <h5 className="text-sm font-semibold">{title}</h5>
                          <p className="mt-1 text-sm leading-6 text-slate-700">{body}</p>
                        </section>
                      ))}
                    </div>
                  ) : (
                    <p className="rounded border border-line bg-panel p-3 text-sm leading-6">
                      {lookup.generated_analysis}
                    </p>
                  )}
                </section>

                {lookup.representative_context && lookup.representative_context.length > 0 ? (
                  <RepresentativeContext signals={lookup.representative_context} />
                ) : null}

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
              <div className="grid min-h-80 place-items-center rounded border border-dashed border-line bg-panel p-6 text-center">
                <div className="max-w-lg">
                  <FileSearch className="mx-auto mb-3 text-civic" size={34} />
                  <p className="text-lg font-semibold">Welcome to Congress For Normal People</p>
                  <p className="mt-2 text-sm leading-6 text-slate-600">
                    Search a federal bill to generate a plain-language political read, source context,
                    and related influence signals. Add your address in the profile panel to see how your
                    own representative connects to the bill through votes, sponsorship, public reporting,
                    and AI-assisted context.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        <aside className="grid content-start gap-5">
          <RepresentativeLookupCard
            profile={profile}
            lookup={lookup}
            result={representativeCheck}
            loading={representativeChecking}
            onRun={runRepresentativeCheck}
          />

          <HotTopicsCard items={hotTopics} onSelect={runLookup} />

          <WatchlistCard
            interests={interests}
            enabledCount={enabledCount}
            bills={visibleWatchlistBills}
            newTopic={newTopic}
            polling={polling}
            onNewTopicChange={setNewTopic}
            onAddInterest={addInterest}
            onToggleInterest={toggleInterest}
            onRefresh={pollBills}
            onSelectBill={runLookup}
          />

          <PreviousLookupsCard items={previousLookups} onSelect={runLookup} />
        </aside>
      </section>
    </main>
  );
}

function authHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json"
  };
}

function LoadingScreen() {
  return (
    <main className="grid min-h-screen place-items-center bg-[#eef1f4] text-ink">
      <div className="flex items-center gap-2 text-sm text-slate-700">
        <Loader2 className="animate-spin" size={17} aria-hidden="true" />
        Loading Congress For Normal People
      </div>
    </main>
  );
}

function LoginPage({
  status,
  onSubmit
}: {
  status: string;
  onSubmit: (payload: RegistrationPayload, mode: "login" | "register") => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [streetAddress, setStreetAddress] = useState("");
  const [addressLine2, setAddressLine2] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [zipCode, setZipCode] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit(
        {
          email,
          password,
          street_address: streetAddress,
          address_line_2: addressLine2,
          city,
          state,
          zip_code: zipCode
        },
        mode
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen bg-[#eef1f4] px-5 py-8 text-ink">
      <section className="mx-auto grid w-full max-w-5xl items-center gap-6 lg:grid-cols-[1fr_0.9fr]">
        <div>
          <div className="mb-4 grid h-11 w-11 place-items-center rounded bg-civic text-white">
            <Radar size={22} aria-hidden="true" />
          </div>
          <h1 className="text-3xl font-semibold tracking-normal">Congress For Normal People</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-700">
            Track legislation in plain English, understand what federal bills would actually do,
            and see how your representatives connect to votes, sponsorship, public reporting, and
            major policy debates.
          </p>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-700">
            Congress For Normal People helps voters follow bills about artificial intelligence,
            housing, healthcare, privacy, energy, elections, immigration, national security, and
            other national issues with source-grounded summaries and AI-assisted context.
          </p>
        </div>

        <form onSubmit={submit} className="rounded border border-line bg-white p-5">
          <div className="mb-4 flex rounded border border-line bg-panel p-1">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`focus-ring flex-1 rounded px-3 py-2 text-sm font-medium ${
                mode === "login" ? "bg-white text-ink shadow-sm" : "text-slate-600"
              }`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`focus-ring flex-1 rounded px-3 py-2 text-sm font-medium ${
                mode === "register" ? "bg-white text-ink shadow-sm" : "text-slate-600"
              }`}
            >
              Create account
            </button>
          </div>

          <label className="block text-sm font-medium">
            Email
            <input
              className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>

          <label className="mt-3 block text-sm font-medium">
            Password
            <input
              className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={8}
            />
          </label>

          {mode === "register" ? (
            <div className="mt-4 grid gap-3 border-t border-line pt-4">
              <p className="text-sm leading-6 text-slate-600">
                Add your address so reports can show your House representative and both senators.
              </p>
              <label className="block text-sm font-medium">
                Street address
                <input
                  className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
                  value={streetAddress}
                  onChange={(event) => setStreetAddress(event.target.value)}
                  required={mode === "register"}
                />
              </label>
              <label className="block text-sm font-medium">
                Address line 2
                <input
                  className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
                  value={addressLine2}
                  onChange={(event) => setAddressLine2(event.target.value)}
                  placeholder="Apt, suite, floor"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-[1fr_70px_100px]">
                <label className="block text-sm font-medium">
                  City
                  <input
                    className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
                    value={city}
                    onChange={(event) => setCity(event.target.value)}
                    required={mode === "register"}
                  />
                </label>
                <label className="block text-sm font-medium">
                  State
                  <input
                    className="focus-ring mt-1 w-full rounded border border-line px-3 py-2 uppercase"
                    value={state}
                    onChange={(event) => setState(event.target.value.toUpperCase())}
                    maxLength={2}
                    required={mode === "register"}
                  />
                </label>
                <label className="block text-sm font-medium">
                  ZIP
                  <input
                    className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
                    value={zipCode}
                    onChange={(event) => setZipCode(event.target.value)}
                    required={mode === "register"}
                  />
                </label>
              </div>
            </div>
          ) : null}

          <button
            className="focus-ring mt-4 inline-flex w-full items-center justify-center gap-2 rounded bg-civic px-4 py-2 font-medium text-white disabled:opacity-60"
            disabled={submitting}
          >
            {submitting ? <Loader2 className="animate-spin" size={17} /> : <UserRound size={17} />}
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
          <p className="mt-3 min-h-5 text-sm text-slate-600">{status}</p>
        </form>
      </section>
    </main>
  );
}

function WatchlistCard({
  interests,
  enabledCount,
  bills,
  newTopic,
  polling,
  onNewTopicChange,
  onAddInterest,
  onToggleInterest,
  onRefresh,
  onSelectBill
}: {
  interests: Interest[];
  enabledCount: number;
  bills: MonitoringBill[];
  newTopic: string;
  polling: boolean;
  onNewTopicChange: (value: string) => void;
  onAddInterest: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  onToggleInterest: (interest: Interest) => Promise<void>;
  onRefresh: () => Promise<void>;
  onSelectBill: (billId: string) => Promise<void>;
}) {
  return (
    <div className="rounded border border-line bg-white">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <Bell size={18} aria-hidden="true" />
          <h2 className="text-base font-semibold">Your Watchlist</h2>
        </div>
        <button
          onClick={() => void onRefresh()}
          className="focus-ring inline-flex items-center gap-2 rounded border border-line px-3 py-1.5 text-sm font-medium"
          disabled={polling}
        >
          {polling ? <Loader2 className="animate-spin" size={16} /> : <Radar size={16} />}
          Refresh Bills
        </button>
      </div>
      <div className="p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-sm leading-6 text-slate-600">
            Topics used to shape your in-app briefing and bill monitoring.
          </p>
          <span className="shrink-0 rounded border border-line bg-panel px-2 py-1 text-xs font-semibold">
            {enabledCount} active
          </span>
        </div>
        <form onSubmit={onAddInterest} className="mb-3 flex gap-2">
          <input
            className="focus-ring min-w-0 flex-1 rounded border border-line px-3 py-2 text-sm"
            value={newTopic}
            onChange={(event) => onNewTopicChange(event.target.value)}
            placeholder="Add topic"
            aria-label="Add watchlist topic"
          />
          <button
            className="focus-ring inline-flex items-center justify-center rounded border border-line px-3 text-sm font-medium"
            aria-label="Add topic"
          >
            <Plus size={16} aria-hidden="true" />
          </button>
        </form>
        <div className="flex flex-wrap gap-2">
          {interests.map((interest) => (
            <button
              key={interest.topic}
              onClick={() => void onToggleInterest(interest)}
              className={`focus-ring rounded border px-2 py-1 text-xs font-medium ${
                interest.enabled
                  ? "border-signal bg-emerald-50 text-signal"
                  : "border-line bg-panel text-slate-500"
              }`}
            >
              {interest.topic}
            </button>
          ))}
        </div>
        <div className="mt-4 border-t border-line pt-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold uppercase text-slate-500">Watchlist Bills</h3>
            <span className="text-xs text-slate-500">{bills.length} shown</span>
          </div>
          <div className="grid gap-2">
            {bills.length === 0 ? (
              <p className="text-sm leading-6 text-slate-600">
                No matching bills are saved yet. Refresh Bills checks for newly introduced bills tied to your active topics.
              </p>
            ) : null}
            {bills.map((bill) => (
              <button
                key={bill.congress_bill_id}
                type="button"
                onClick={() => void onSelectBill(bill.congress_bill_id)}
                className="focus-ring rounded border border-line bg-panel p-3 text-left transition hover:bg-white"
              >
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="text-xs font-semibold uppercase text-civic">{bill.congress_bill_id}</span>
                  <span className="rounded bg-white px-2 py-0.5 text-xs">{bill.topic}</span>
                </div>
                <h4 className="text-sm font-semibold leading-5">{bill.title}</h4>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">{bill.summary}</p>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function PreviousLookupsCard({
  items,
  onSelect
}: {
  items: PreviousLookup[];
  onSelect: (billId: string) => Promise<void>;
}) {
  return (
    <div className="rounded border border-line bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 size={18} aria-hidden="true" />
          <h2 className="text-base font-semibold">Previous Lookups</h2>
        </div>
        <span className="text-xs text-slate-500">This browser</span>
      </div>
      <div className="divide-y divide-line">
        {items.length === 0 ? (
          <p className="p-4 text-sm leading-6 text-slate-600">
            Search a bill to start building your lookup history.
          </p>
        ) : null}
        {items.map((item) => (
          <button
            key={item.congress_bill_id}
            type="button"
            onClick={() => void onSelect(item.congress_bill_id)}
            className="focus-ring block w-full p-4 text-left transition hover:bg-panel"
          >
            <div className="mb-1 flex items-center justify-between gap-3">
              <span className="text-xs font-semibold uppercase text-civic">{item.congress_bill_id}</span>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{item.topic}</span>
            </div>
            <h3 className="text-sm font-semibold leading-5">{item.title}</h3>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">{item.summary}</p>
          </button>
        ))}
      </div>
    </div>
  );
}

function RepresentativeLookupCard({
  profile,
  lookup,
  result,
  loading,
  onRun
}: {
  profile: UserProfile | null;
  lookup: LookupResponse | null;
  result: RepresentativeBillSignal | null;
  loading: boolean;
  onRun: (representativeName: string) => Promise<void>;
}) {
  const [representativeName, setRepresentativeName] = useState("");

  useEffect(() => {
    if (!representativeName && profile?.representatives[0]) {
      setRepresentativeName(profile.representatives[0].name);
    }
  }, [profile, representativeName]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onRun(representativeName);
  }

  return (
    <div className="rounded border border-line bg-white">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <BrainCircuit size={18} aria-hidden="true" />
        <h2 className="text-base font-semibold">Representative Check</h2>
      </div>
      <form onSubmit={submit} className="grid gap-3 p-4">
        <p className="text-sm leading-6 text-slate-600">
          Curious what a specific representative thinks of the bill you searched? Enter a senator or
          representative and this will use the current report as context.
        </p>
        <input
          className="focus-ring rounded border border-line px-3 py-2 text-sm"
          value={representativeName}
          onChange={(event) => setRepresentativeName(event.target.value)}
          placeholder="Representative or senator name"
          aria-label="Representative or senator name"
        />
        <button
          className="focus-ring inline-flex items-center justify-center gap-2 rounded border border-line px-3 py-2 text-sm font-medium"
          disabled={loading || !lookup || !representativeName.trim()}
        >
          {loading ? <Loader2 className="animate-spin" size={16} /> : <Search size={16} />}
          Check current bill
        </button>
      </form>

      {profile?.representatives && profile.representatives.length > 0 ? (
        <div className="border-t border-line p-4 text-sm">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="font-semibold">
              {profile.state}-{profile.congressional_district}
            </div>
            <Link href="/profile" className="text-xs font-medium text-civic hover:underline">
              Edit address
            </Link>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {profile.representatives.map((representative) => (
              <button
                key={`${representative.chamber}-${representative.name}`}
                type="button"
                onClick={() => {
                  setRepresentativeName(representative.name);
                  void onRun(representative.name);
                }}
                className="focus-ring flex items-center gap-2 rounded border border-line bg-panel p-2 text-left text-xs"
                disabled={loading || !lookup}
              >
                <MemberAvatar
                  name={representative.name}
                  photoUrl={representative.photo_url}
                  size="sm"
                />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{displayPersonName(representative.name)}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1 text-slate-600">
                    <span>{representative.chamber}</span>
                    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[11px] font-semibold ${partyBadgeClass(representative.party)}`}>
                      {partyLabel(representative.party)}
                    </span>
                  </span>
                </span>
              </button>
            ))}
          </div>
          {profile.warning ? <p className="mt-2 text-xs text-slate-500">{profile.warning}</p> : null}
        </div>
      ) : (
        <div className="border-t border-line p-4 text-sm text-slate-600">
          Save your address on the profile page to load your House representative and both senators.
        </div>
      )}

      {result ? (
        <div className="border-t border-line p-4">
          <RepresentativeContext signals={[result]} title="Representative Result" />
        </div>
      ) : null}
    </div>
  );
}

function ProfileCard({
  profile,
  onSave
}: {
  profile: UserProfile | null;
  onSave: (payload: {
    street_address: string;
    address_line_2: string;
    city: string;
    state: string;
    zip_code: string;
  }) => Promise<void>;
}) {
  const [streetAddress, setStreetAddress] = useState(profile?.street_address ?? "");
  const [addressLine2, setAddressLine2] = useState(profile?.address_line_2 ?? "");
  const [city, setCity] = useState(profile?.city ?? "");
  const [state, setState] = useState(profile?.state ?? "");
  const [zipCode, setZipCode] = useState(profile?.zip_code ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setStreetAddress(profile?.street_address ?? "");
    setAddressLine2(profile?.address_line_2 ?? "");
    setCity(profile?.city ?? "");
    setState(profile?.state ?? "");
    setZipCode(profile?.zip_code ?? "");
  }, [profile]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await onSave({ street_address: streetAddress, address_line_2: addressLine2, city, state, zip_code: zipCode });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded border border-line bg-white">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <UserRound size={18} aria-hidden="true" />
        <h2 className="text-base font-semibold">Profile</h2>
      </div>
      <form onSubmit={submit} className="grid gap-2 p-4">
        <input
          className="focus-ring rounded border border-line px-3 py-2 text-sm"
          value={streetAddress}
          onChange={(event) => setStreetAddress(event.target.value)}
          placeholder="Street address"
          aria-label="Street address"
        />
        <input
          className="focus-ring rounded border border-line px-3 py-2 text-sm"
          value={addressLine2}
          onChange={(event) => setAddressLine2(event.target.value)}
          placeholder="Address line 2"
          aria-label="Address line 2"
        />
        <div className="grid grid-cols-[1fr_70px_90px] gap-2">
          <input
            className="focus-ring min-w-0 rounded border border-line px-3 py-2 text-sm"
            value={city}
            onChange={(event) => setCity(event.target.value)}
            placeholder="City"
            aria-label="City"
          />
          <input
            className="focus-ring min-w-0 rounded border border-line px-3 py-2 text-sm uppercase"
            value={state}
            onChange={(event) => setState(event.target.value.toUpperCase())}
            placeholder="State"
            aria-label="State"
            maxLength={2}
          />
          <input
            className="focus-ring min-w-0 rounded border border-line px-3 py-2 text-sm"
            value={zipCode}
            onChange={(event) => setZipCode(event.target.value)}
            placeholder="ZIP"
            aria-label="ZIP code"
            required
          />
        </div>
        <button
          className="focus-ring inline-flex items-center justify-center gap-2 rounded border border-line px-3 py-2 text-sm font-medium"
          disabled={saving}
        >
          {saving ? <Loader2 className="animate-spin" size={16} /> : <Radar size={16} />}
          Save district
        </button>
      </form>
      {profile?.congressional_district ? (
        <div className="border-t border-line p-4 text-sm">
          <div className="font-semibold">
            {profile.state}-{profile.congressional_district}
          </div>
          <div className="mt-2 grid gap-2">
            {profile.representatives.map((representative) => (
              <div key={`${representative.chamber}-${representative.name}`} className="leading-5">
                <div className="font-medium">{displayPersonName(representative.name)}</div>
                <div className="text-xs text-slate-600">
                  {representative.chamber} · {representative.party}
                </div>
              </div>
            ))}
          </div>
          {profile.warning ? <p className="mt-2 text-xs text-slate-500">{profile.warning}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function HotTopicsCard({
  items,
  onSelect
}: {
  items: HotTopicBill[];
  onSelect: (billId: string) => Promise<void>;
}) {
  return (
    <div className="rounded border border-line bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <Flame size={18} aria-hidden="true" />
          <h2 className="text-base font-semibold">National Spotlight</h2>
        </div>
        <span className="text-xs text-slate-500">Search prompts</span>
      </div>
      <div className="divide-y divide-line">
        {items.length === 0 ? (
          <p className="p-4 text-sm leading-6 text-slate-600">
            National spotlight prompts are temporarily unavailable.
          </p>
        ) : null}
        {items.slice(0, 7).map((item) => (
          <button
            key={item.congress_bill_id}
            type="button"
            onClick={() => void onSelect(item.congress_bill_id)}
            className="focus-ring block w-full p-4 text-left transition hover:bg-panel"
          >
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase text-civic">
                {item.congress_bill_id}
              </span>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{item.topic}</span>
              <span className="text-xs text-slate-500">{item.year}</span>
            </div>
            <h3 className="text-sm font-semibold leading-5">{item.title}</h3>
            <p className="mt-1 text-xs leading-5 text-slate-600">{item.reason}</p>
          </button>
        ))}
      </div>
    </div>
  );
}

function LookupProgressList({ items }: { items: LookupProgress[] }) {
  return (
    <div className="border-b border-line bg-panel px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
        <Loader2 className="animate-spin text-civic" size={14} aria-hidden="true" />
        Building Report
      </div>
      <ol className="grid gap-2">
        {items.map((item, index) => {
          const isActive = index === items.length - 1;
          return (
            <li key={`${item.step ?? item.message}-${index}`} className="flex gap-2 text-xs leading-5">
              {isActive ? (
                <Loader2 className="mt-0.5 shrink-0 animate-spin text-civic" size={14} aria-hidden="true" />
              ) : (
                <CheckCircle2 className="mt-0.5 shrink-0 text-civic" size={14} aria-hidden="true" />
              )}
              <span>
                <span className="font-semibold text-slate-800">{item.message}</span>
                {item.detail ? <span className="block text-slate-500">{item.detail}</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function RepresentativeContext({
  signals,
  title = "Your Representative Context"
}: {
  signals: RepresentativeBillSignal[];
  title?: string;
}) {
  return (
    <section className="rounded border border-line bg-panel p-3">
      <h4 className="mb-2 text-sm font-semibold uppercase text-slate-500">{title}</h4>
      <div className="grid gap-2">
        {signals.map((signal) => (
          <article key={`${signal.representative.chamber}-${signal.representative.name}`} className="text-sm leading-6">
            <div className="flex items-start gap-2">
              <MemberAvatar name={signal.representative.name} photoUrl={signal.representative.photo_url} size="lg" />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{displayPersonName(signal.representative.name)}</span>
                  <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${partyBadgeClass(signal.representative.party)}`}>
                    {partyLabel(signal.representative.party)}
                  </span>
                  <span className="rounded bg-white px-2 py-0.5 text-xs font-medium text-slate-600">
                    {signal.signal}
                  </span>
                </div>
                <p className="text-xs leading-5 text-slate-600">{signal.detail}</p>
              </div>
            </div>
            {signal.ai_context ? (
              <div className="mt-2 rounded border border-amber-200 bg-amber-50 p-2">
                <div className="mb-1 inline-flex items-center gap-1 text-xs font-semibold uppercase text-amber-800">
                  <BrainCircuit size={14} aria-hidden="true" />
                  {signal.ai_context_label ?? "AI-assisted context"}
                </div>
                <p className="text-xs leading-5 text-amber-950">{signal.ai_context}</p>
              </div>
            ) : null}
            {signal.sources && signal.sources.length > 0 ? (
              <div className="mt-2">
                <h5 className="text-xs font-semibold uppercase text-slate-500">Sources</h5>
                <ul className="mt-1 grid gap-1">
                  {signal.sources.map((source, index) => (
                    <li key={`${source.url ?? source.label}-${index}`} className="text-xs leading-5">
                      {source.url ? (
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-civic underline-offset-2 hover:underline"
                        >
                          {source.label}
                        </a>
                      ) : (
                        <span className="text-slate-600">{source.label}</span>
                      )}
                      {source.description ? (
                        <p className="text-slate-500">{source.description}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function SponsorCard({ sponsor, photoUrl }: { sponsor: string; photoUrl?: string | null }) {
  const party = parseSponsorParty(sponsor);
  const color = partyColor(party.code);

  return (
    <div className="rounded border border-line bg-panel p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <MemberAvatar name={displayPersonName(sponsor)} photoUrl={photoUrl} size="lg" />
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase text-slate-500">Sponsor</div>
            <div className="mt-1 break-words text-sm font-semibold">{displayPersonName(sponsor)}</div>
          </div>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded border px-2 py-1 text-xs font-semibold ${color}`}>
          <UserRound size={13} aria-hidden="true" />
          {party.label}
        </span>
      </div>
    </div>
  );
}

function ReportCoverageCard({ lookup }: { lookup: LookupResponse }) {
  const representativeCount = lookup.representative_context?.length ?? 0;

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold uppercase text-slate-500">Report Context</h4>
        <span className="text-xs text-slate-500">{representativeCount} representative checks included</span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <CoverageMetric
          icon={<ShieldCheck size={15} aria-hidden="true" />}
          label="Source Context"
          value={lookup.confidence}
          definition="How much supporting evidence the report found beyond the basic bill record."
          description={coverageDescription(lookup.confidence)}
        />
        <CoverageMetric
          icon={<CircleDollarSign size={15} aria-hidden="true" />}
          label="Campaign Finance"
          value={lookup.finance.confidence ?? "low"}
          definition="Whether sponsor-related campaign-finance records were found for review."
          description={financeCoverageDescription(lookup.finance.confidence ?? "low")}
        />
      </div>
    </section>
  );
}

function CoverageMetric({
  icon,
  label,
  value,
  definition,
  description
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  definition: string;
  description: string;
}) {
  return (
    <div className="rounded border border-line bg-panel p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase text-slate-500">
          {icon}
          {label}
        </div>
        <span className={`rounded border px-2 py-0.5 text-xs font-semibold uppercase ${coverageValueClass(value)}`}>
          {value}
        </span>
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-700">{definition}</p>
      <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
    </div>
  );
}

function coverageValueClass(value: string) {
  const normalized = value.toLowerCase();
  if (normalized === "high") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (normalized === "medium") return "border-amber-200 bg-amber-50 text-amber-800";
  if (normalized === "low") return "border-slate-200 bg-slate-50 text-slate-600";
  return "border-slate-200 bg-white text-slate-600";
}

function coverageDescription(value: string) {
  const normalized = value.toLowerCase();
  if (normalized === "high") return "Official bill data plus supporting context were found.";
  if (normalized === "medium") return "Core bill data was found, with some supporting context.";
  return "Limited supporting context was available for this report.";
}

function financeCoverageDescription(value: string) {
  const normalized = value.toLowerCase();
  if (normalized === "high") return "Sponsor-related campaign-finance records were found.";
  if (normalized === "medium") return "Some campaign-finance matches were found, but review is limited.";
  return "No strong sponsor campaign-finance match was found.";
}

function MemberAvatar({
  name,
  photoUrl,
  size
}: {
  name: string;
  photoUrl?: string | null;
  size: "sm" | "md" | "lg";
}) {
  const dimensions = size === "sm" ? "h-12 w-12" : size === "md" ? "h-14 w-14" : "h-16 w-16";
  const initials = displayPersonName(name)
    .replace(/Rep\.|Sen\./g, "")
    .replace(/\[[^\]]+\]/g, "")
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
        className={`${dimensions} shrink-0 rounded-full border border-line object-cover object-top`}
        onError={(event) => {
          event.currentTarget.style.display = "none";
        }}
      />
    );
  }

  return (
    <span className={`${dimensions} inline-flex shrink-0 items-center justify-center rounded-full border border-line bg-white text-xs font-semibold text-slate-500`}>
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

function SignalCard({
  icon,
  label,
  value
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded border border-line bg-panel p-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-sm font-semibold capitalize">{value}</div>
    </div>
  );
}

function parseSponsorParty(sponsor: string): { code: "D" | "R" | "I" | "U"; label: string } {
  if (sponsor.includes("[D-")) return { code: "D", label: "Democrat" };
  if (sponsor.includes("[R-")) return { code: "R", label: "Republican" };
  if (sponsor.includes("[I-")) return { code: "I", label: "Independent" };
  return { code: "U", label: "Unknown" };
}

function partyColor(code: "D" | "R" | "I" | "U") {
  if (code === "D") return "border-blue-200 bg-blue-50 text-blue-700";
  if (code === "R") return "border-red-200 bg-red-50 text-red-700";
  if (code === "I") return "border-violet-200 bg-violet-50 text-violet-700";
  return "border-slate-200 bg-white text-slate-600";
}

function partyLabel(party: string) {
  const normalized = party.trim().toLowerCase();
  if (party === "D" || normalized.includes("democrat")) return "Democrat";
  if (party === "R" || normalized.includes("republican")) return "Republican";
  if (party === "I" || normalized.includes("independent")) return "Independent";
  return party || "Unknown";
}

function partyBadgeClass(party: string) {
  const label = partyLabel(party);
  if (label === "Democrat") return "border-blue-200 bg-blue-50 text-blue-700";
  if (label === "Republican") return "border-red-200 bg-red-50 text-red-700";
  if (label === "Independent") return "border-violet-200 bg-violet-50 text-violet-700";
  return "border-slate-200 bg-white text-slate-600";
}

function StakeholderList({ title, items }: { title: string; items: StakeholderInsight[] }) {
  return (
    <section className="rounded border border-line bg-panel p-3">
      <h4 className="mb-2 text-sm font-semibold uppercase text-slate-500">{title}</h4>
      {items.length === 0 ? (
        <p className="text-sm leading-6 text-slate-600">
          No related lobbying disclosure matches found for this lookup.
        </p>
      ) : null}
      <ul className="grid gap-2 text-sm">
        {items.map((item, index) => (
          <li key={`${item.name}-${index}`} className="border-t border-line pt-2 leading-5 first:border-t-0 first:pt-0">
            <div className="flex flex-wrap items-center gap-2">
              <div className="font-semibold">{item.name}</div>
              {item.recency ? (
                <span className="rounded bg-white px-2 py-0.5 text-xs font-medium text-slate-600">
                  {item.recency}
                </span>
              ) : null}
            </div>
            <div className="mt-1 text-xs leading-5 text-slate-600">
              {item.takeaway ?? item.context}
            </div>
            {item.relevance ? <div className="mt-1 text-xs leading-5 text-slate-500">{item.relevance}</div> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
