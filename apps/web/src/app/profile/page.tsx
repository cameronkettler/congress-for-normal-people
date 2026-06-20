"use client";

import Link from "next/link";
import { ArrowLeft, Loader2, Radar, Save, UserRound } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

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
  official_url?: string | null;
};

type UserProfile = {
  street_address: string;
  address_line_2: string;
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

const emptyProfile: UserProfile = {
  street_address: "",
  address_line_2: "",
  city: "",
  state: "",
  zip_code: "",
  congressional_district: "",
  location_confidence: "unknown",
  representatives: []
};

export default function ProfilePage() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [profile, setProfile] = useState<UserProfile>(emptyProfile);
  const [status, setStatus] = useState("Loading profile settings");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void bootstrap();
  }, []);

  async function bootstrap() {
    const storedToken = window.localStorage.getItem(tokenStorageKey);
    if (!storedToken) {
      setLoading(false);
      setStatus("Sign in from the dashboard to edit profile settings.");
      return;
    }

    try {
      const accountResponse = await fetch(`${apiBase}/api/auth/me`, {
        headers: authHeaders(storedToken)
      });
      if (!accountResponse.ok) {
        window.localStorage.removeItem(tokenStorageKey);
        setStatus("Your session expired. Sign in again from the dashboard.");
        return;
      }

      setToken(storedToken);
      setUser((await accountResponse.json()) as AuthUser);

      const profileResponse = await fetch(`${apiBase}/api/profile`, {
        headers: authHeaders(storedToken)
      });
      if (!profileResponse.ok) {
        setStatus("Profile settings are temporarily unavailable.");
        return;
      }

      const payload = (await profileResponse.json()) as UserProfile;
      setProfile({ ...emptyProfile, ...payload });
      setStatus(payload.warning ?? "Profile settings loaded");
    } catch {
      setStatus("Could not reach the API.");
    } finally {
      setLoading(false);
    }
  }

  async function saveLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;

    setSaving(true);
    setStatus("Resolving congressional district");
    try {
      const response = await fetch(`${apiBase}/api/profile/location`, {
        method: "PUT",
        headers: authHeaders(token),
        body: JSON.stringify({
          street_address: profile.street_address,
          address_line_2: profile.address_line_2,
          city: profile.city,
          state: profile.state,
          zip_code: profile.zip_code
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        setStatus(payload.detail ?? "Could not save profile location.");
        return;
      }

      setProfile({ ...emptyProfile, ...(payload as UserProfile) });
      setStatus(payload.warning ?? "Profile location saved");
    } catch {
      setStatus("Could not reach the API.");
    } finally {
      setSaving(false);
    }
  }

  function updateField(field: keyof UserProfile, value: string) {
    setProfile((current) => ({ ...current, [field]: value }));
  }

  return (
    <main className="min-h-screen bg-[#eef1f4] text-ink">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded bg-civic text-white">
              <UserRound size={21} aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-normal">Profile Settings</h1>
              <p className="text-sm text-slate-600">{user?.email ?? status}</p>
            </div>
          </div>
          <Link
            href="/"
            className="focus-ring inline-flex items-center gap-2 rounded border border-line px-3 py-2 text-sm font-medium"
          >
            <ArrowLeft size={15} aria-hidden="true" />
            Dashboard
          </Link>
        </div>
      </header>

      <section className="mx-auto grid max-w-5xl gap-5 px-5 py-5 lg:grid-cols-[1fr_0.85fr]">
        <form onSubmit={saveLocation} className="rounded border border-line bg-white">
          <div className="flex items-center gap-2 border-b border-line px-4 py-3">
            <Radar size={18} aria-hidden="true" />
            <h2 className="text-base font-semibold">Home District</h2>
          </div>

          <div className="grid gap-4 p-4">
            <label className="block text-sm font-medium">
              Street address
              <input
                className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
                value={profile.street_address}
                onChange={(event) => updateField("street_address", event.target.value)}
                disabled={loading || !token}
                required
              />
            </label>

            <label className="block text-sm font-medium">
              Address line 2
              <input
                className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
                value={profile.address_line_2}
                onChange={(event) => updateField("address_line_2", event.target.value)}
                disabled={loading || !token}
                placeholder="Apt, suite, floor"
              />
            </label>

            <div className="grid gap-4 sm:grid-cols-[1fr_0.45fr_0.55fr]">
              <label className="block text-sm font-medium">
                City
                <input
                  className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
                  value={profile.city}
                  onChange={(event) => updateField("city", event.target.value)}
                  disabled={loading || !token}
                  required
                />
              </label>
              <label className="block text-sm font-medium">
                State
                <input
                  className="focus-ring mt-1 w-full rounded border border-line px-3 py-2 uppercase"
                  value={profile.state}
                  onChange={(event) => updateField("state", event.target.value.toUpperCase())}
                  disabled={loading || !token}
                  maxLength={2}
                  required
                />
              </label>
              <label className="block text-sm font-medium">
                ZIP
                <input
                  className="focus-ring mt-1 w-full rounded border border-line px-3 py-2"
                  value={profile.zip_code}
                  onChange={(event) => updateField("zip_code", event.target.value)}
                  disabled={loading || !token}
                  required
                />
              </label>
            </div>

            <button
              className="focus-ring inline-flex items-center justify-center gap-2 rounded bg-civic px-4 py-2 font-medium text-white disabled:opacity-60"
              disabled={loading || saving || !token}
            >
              {saving ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
              Save location
            </button>
            <p className="min-h-5 text-sm text-slate-600">{status}</p>
          </div>
        </form>

        <aside className="rounded border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <h2 className="text-base font-semibold">Your Representatives</h2>
            <p className="mt-1 text-sm text-slate-600">
              {profile.congressional_district
                ? `${profile.state}-${profile.congressional_district}`
                : "Save an address to resolve your district."}
            </p>
          </div>
          <div className="divide-y divide-line">
            {profile.representatives.length === 0 ? (
              <p className="p-4 text-sm leading-6 text-slate-600">
                No representatives loaded yet.
              </p>
            ) : null}
            {profile.representatives.map((representative) => (
              <article key={`${representative.chamber}-${representative.name}`} className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold">{representative.name}</h3>
                    <p className="mt-1 text-sm text-slate-600">
                      {representative.chamber}
                      {representative.district ? `, District ${representative.district}` : ""}
                    </p>
                  </div>
                  <span className={`rounded border px-2 py-1 text-xs font-semibold ${partyColor(representative.party)}`}>
                    {representative.party || "Unknown"}
                  </span>
                </div>
              </article>
            ))}
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

function partyColor(party: string) {
  if (party === "D" || party.toLowerCase().includes("democrat")) return "border-blue-200 bg-blue-50 text-blue-700";
  if (party === "R" || party.toLowerCase().includes("republican")) return "border-red-200 bg-red-50 text-red-700";
  if (party === "I" || party.toLowerCase().includes("independent")) return "border-violet-200 bg-violet-50 text-violet-700";
  return "border-slate-200 bg-white text-slate-600";
}
