"use client";

import Link from "next/link";
import {
  Activity,
  Bell,
  CheckCircle2,
  CircleDollarSign,
  FileSearch,
  LogOut,
  Loader2,
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
    latest_action: string;
    status: string;
    topic: string;
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
};

type RepresentativeBillSignal = {
  representative: RepresentativeRecord;
  signal: string;
  detail: string;
  sources?: SourceReference[];
};

type SourceReference = {
  label: string;
  url?: string | null;
  confidence?: string;
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
  city: string;
  state: string;
  zip_code: string;
  congressional_district: string;
  location_confidence: string;
  representatives: RepresentativeRecord[];
  warning?: string | null;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const tokenStorageKey = "civic-pulse-token";

export default function Home() {
  const [billId, setBillId] = useState("hr-1234-119");
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [lookup, setLookup] = useState<LookupResponse | null>(null);
  const [recent, setRecent] = useState<MonitoringBill[]>([]);
  const [interests, setInterests] = useState<Interest[]>([]);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [status, setStatus] = useState("Ready");

  useEffect(() => {
    void bootstrap();
  }, []);

  const enabledCount = useMemo(() => interests.filter((item) => item.enabled).length, [interests]);

  async function bootstrap() {
    await loadRecent();
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

  async function loadRecent() {
    try {
      const response = await fetch(`${apiBase}/api/monitoring/recent`);
      if (!response.ok) {
        setRecent([]);
        setStatus("Recent bills unavailable");
        return;
      }
      const payload = (await response.json()) as MonitoringBill[] | MonitoringRecentResponse;
      if (Array.isArray(payload)) {
        setRecent(payload);
        return;
      }
      setRecent(payload.items ?? []);
      if (payload.warning) {
        setStatus(payload.warning);
      }
    } catch {
      setRecent([]);
      setStatus("Recent bills unavailable");
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

  async function submitAuth(email: string, password: string, mode: "login" | "register") {
    setStatus(mode === "login" ? "Signing in" : "Creating account");
    const response = await fetch(`${apiBase}/api/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    const payload = await response.json();
    if (!response.ok) {
      setStatus(payload.detail ?? "Authentication failed");
      return;
    }

    const auth = payload as AuthResponse;
    window.localStorage.setItem(tokenStorageKey, auth.token);
    setAuthToken(auth.token);
    setUser(auth.user);
    setStatus("Signed in");
    await loadInterests(auth.token);
  }

  function signOut() {
    window.localStorage.removeItem(tokenStorageKey);
    setAuthToken(null);
    setUser(null);
    setInterests([]);
    setProfile(null);
    setStatus("Signed out");
  }

  async function submitLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setStatus("Running bill lookup workflow");
    try {
      const response = await fetch(`${apiBase}/api/bills/lookup`, {
        method: "POST",
        headers: authToken ? authHeaders(authToken) : { "Content-Type": "application/json" },
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
        `Poll complete: ${payload.discovered} discovered, ${payload.notifications} notifications queued`
      );
      await loadRecent();
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
              <h1 className="text-xl font-semibold tracking-normal">Civic Pulse</h1>
              <p className="text-sm text-slate-600">Agentic federal legislation intelligence</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-700">
            <Activity size={17} aria-hidden="true" />
            <span>{status}</span>
            <span className="hidden text-slate-400 md:inline">|</span>
            <span className="hidden md:inline">{user.email}</span>
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

                <div className="grid gap-3 md:grid-cols-[1.35fr_0.65fr_0.65fr]">
                  <SponsorCard sponsor={lookup.bill.sponsor} />
                  <SignalCard
                    icon={<ShieldCheck size={17} aria-hidden="true" />}
                    label="Source depth"
                    value={lookup.confidence}
                  />
                  <SignalCard
                    icon={<CircleDollarSign size={17} aria-hidden="true" />}
                    label="Finance coverage"
                    value={lookup.finance.confidence ?? "low"}
                  />
                </div>

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
          <ProfileCard profile={profile} onSave={saveProfileLocation} />

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
              <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold uppercase text-slate-500">Alert Topics</h3>
                <span className="text-xs text-slate-500">Used by Poll</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {interests.map((interest) => (
                  <button
                    key={interest.topic}
                    onClick={() => void toggleInterest(interest)}
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
        Loading Civic Pulse
      </div>
    </main>
  );
}

function LoginPage({
  status,
  onSubmit
}: {
  status: string;
  onSubmit: (email: string, password: string, mode: "login" | "register") => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit(email, password, mode);
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
          <h1 className="text-3xl font-semibold tracking-normal">Civic Pulse</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-700">
            Sign in to keep monitoring topics tied to your account. Your bill lookups stay source-grounded,
            while alert topics become configurable per user instead of global for everyone.
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

function Metric({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className={compact ? "p-3" : "rounded border border-line bg-panel p-3"}>
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold">{value}</div>
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
    city: string;
    state: string;
    zip_code: string;
  }) => Promise<void>;
}) {
  const [streetAddress, setStreetAddress] = useState(profile?.street_address ?? "");
  const [city, setCity] = useState(profile?.city ?? "");
  const [state, setState] = useState(profile?.state ?? "");
  const [zipCode, setZipCode] = useState(profile?.zip_code ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setStreetAddress(profile?.street_address ?? "");
    setCity(profile?.city ?? "");
    setState(profile?.state ?? "");
    setZipCode(profile?.zip_code ?? "");
  }, [profile]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await onSave({ street_address: streetAddress, city, state, zip_code: zipCode });
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
                <div className="font-medium">{representative.name}</div>
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

function RepresentativeContext({ signals }: { signals: RepresentativeBillSignal[] }) {
  return (
    <section className="rounded border border-line bg-panel p-3">
      <h4 className="mb-2 text-sm font-semibold uppercase text-slate-500">Your Representative Context</h4>
      <div className="grid gap-2">
        {signals.map((signal) => (
          <article key={`${signal.representative.chamber}-${signal.representative.name}`} className="text-sm leading-6">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{signal.representative.name}</span>
              <span className="rounded bg-white px-2 py-0.5 text-xs font-medium text-slate-600">
                {signal.signal}
              </span>
            </div>
            <p className="text-xs leading-5 text-slate-600">{signal.detail}</p>
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

function SponsorCard({ sponsor }: { sponsor: string }) {
  const party = parseSponsorParty(sponsor);
  const color = partyColor(party.code);

  return (
    <div className="rounded border border-line bg-panel p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase text-slate-500">Sponsor</div>
          <div className="mt-1 break-words text-sm font-semibold">{sponsor}</div>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded border px-2 py-1 text-xs font-semibold ${color}`}>
          <UserRound size={13} aria-hidden="true" />
          {party.label}
        </span>
      </div>
    </div>
  );
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
