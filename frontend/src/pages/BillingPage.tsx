import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, CreditCard, ExternalLink, ShieldCheck } from "lucide-react";
import { ErrorNote, PageHeader, Spinner } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime } from "../lib/live";

interface Status { subscription_status: string; current_period_end: string | null; has_customer: boolean; price_cents: number; stripe_configured: boolean; banner: boolean }

export default function BillingPage() {
  const { schoolId, school, reloadSchool } = useAuth();
  const [params] = useSearchParams();
  const [st, setSt] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (schoolId) api<Status>(`/api/v1/billing/status?school_id=${schoolId}`).then(setSt).catch(() => undefined);
    if (params.get("status") === "success") reloadSchool();
  }, [schoolId, params, reloadSchool]);

  const go = async (path: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ url: string }>(path, { method: "POST", json: { school_id: schoolId } });
      if (!r.url.startsWith("https://")) throw new ApiError(500, "Unexpected redirect URL");
      window.location.href = r.url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
      setBusy(false);
    }
  };
  if (!st) return <Spinner />;
  const active = st.subscription_status === "active" || st.subscription_status === "trialing";
  return (
    <div className="max-w-2xl">
      <PageHeader title="Billing" subtitle={school?.name} />
      {params.get("status") === "success" && <div className="mb-4 flex items-center gap-2 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800"><CheckCircle2 className="h-4 w-4" /> Thank you! Your subscription will show as active within a few seconds.</div>}
      <div className="card p-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-sm font-semibold uppercase tracking-wide text-slate-500">School subscription</div>
            <div className="mt-1 text-4xl font-extrabold text-slate-900">${(st.price_cents / 100).toFixed(2)}<span className="text-base font-medium text-slate-500"> / month</span></div>
            <div className="mt-1 text-sm text-slate-500">Unlimited kiosks, staff and students for one school.</div>
          </div>
          <span className={`badge px-3 py-1 text-sm ${active ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{st.subscription_status.replace("_", " ")}</span>
        </div>
        {st.current_period_end && <p className="mt-4 text-sm text-slate-600">Current period ends {formatDateTime(st.current_period_end, school?.timezone)}</p>}
        <div className="mt-6 flex flex-wrap gap-2">
          {!active && <button className="btn-primary" disabled={busy || !st.stripe_configured} onClick={() => go("/api/v1/billing/create-checkout-session")}><CreditCard className="h-4 w-4" /> Subscribe with Stripe</button>}
          {st.has_customer && <button className="btn-secondary" disabled={busy || !st.stripe_configured} onClick={() => go("/api/v1/billing/create-portal-session")}><ExternalLink className="h-4 w-4" /> Manage billing, cards &amp; invoices</button>}
        </div>
        {!st.stripe_configured && <p className="mt-3 text-xs text-amber-700">Stripe keys are not configured on this server (STRIPE_SECRET_KEY).</p>}
        <ErrorNote error={error} />
      </div>
      <div className="mt-4 flex gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
        <ShieldCheck className="h-5 w-5 shrink-0" />
        <p><b>Safety-first grace policy:</b> even if a payment fails, student sign-ins, the emergency locator and lockdown roll-call are never switched off.</p>
      </div>
    </div>
  );
}
