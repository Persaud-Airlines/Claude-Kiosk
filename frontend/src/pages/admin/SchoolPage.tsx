import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CreditCard, Tablet, Wifi, WifiOff } from "lucide-react";
import { ErrorNote, PageHeader, Spinner } from "../../components/ui";
import { api, ApiError, type School } from "../../lib/api";
import { formatDateTime } from "../../lib/live";

// Platform-operator view of one school: subscription status and kiosk health only.
// Students, sign-in/out records, staff and audit logs are not available to the platform operator.

interface BillingStatus {
  subscription_status: string;
  current_period_end: string | null;
  price_cents: number;
  banner: boolean;
}

interface KioskHealth {
  id: string;
  device_uid: string;
  room_number: string | null;
  pairing_status: string;
  online: boolean;
  firmware_version: string | null;
  ip_address: string | null;
  wifi_rssi: number | null;
  offline_queue_depth: number;
  last_seen_at: string | null;
}

export default function SchoolPage() {
  const { id } = useParams();
  const [school, setSchool] = useState<School | null>(null);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [kiosks, setKiosks] = useState<KioskHealth[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setError(null);
    api<{ id: string; name: string; timezone: string }[]>("/api/v1/admin/schools")
      .then((all) => setSchool(all.find((s) => s.id === id) as School | null))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load school"));
    api<BillingStatus>(`/api/v1/billing/status?school_id=${id}`).then(setBilling).catch(() => undefined);
    api<KioskHealth[]>(`/api/v1/admin/kiosks?school_id=${id}`).then(setKiosks).catch(() => undefined);
  }, [id]);

  const status = billing?.subscription_status ?? "";
  const paid = status === "active" || status === "trialing";

  return (
    <>
      <Link to="/admin" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> All schools
      </Link>
      <PageHeader title={school?.name ?? "School"} subtitle="Subscription and kiosk health. No student or sign-in data is shown here." />
      <ErrorNote error={error} />

      <section className="card mb-6 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <CreditCard className="h-4 w-4" /> Subscription
          </div>
          {billing ? (
            <span className={`badge px-3 py-1 ${paid ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-700"}`}>
              {status.replace("_", " ")}
            </span>
          ) : <Spinner />}
        </div>
        {billing && (
          <p className="mt-3 text-sm text-slate-600">
            ${(billing.price_cents / 100).toFixed(2)} / month
            {billing.current_period_end && <> · current period ends {formatDateTime(billing.current_period_end)}</>}
          </p>
        )}
      </section>

      <section className="card">
        <h2 className="flex items-center gap-2 border-b border-slate-100 px-4 py-3 font-bold">
          <Tablet className="h-4 w-4" /> Kiosks bound to this school
        </h2>
        {!kiosks ? <Spinner /> : kiosks.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">No kiosks are paired to this school yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-100">
              <thead>
                <tr>
                  <th className="th">Status</th>
                  <th className="th">Room</th>
                  <th className="th">Device</th>
                  <th className="th">Firmware</th>
                  <th className="th">Wi-Fi</th>
                  <th className="th">Queue</th>
                  <th className="th">Last seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {kiosks.map((k) => (
                  <tr key={k.id}>
                    <td className="td">
                      {k.pairing_status !== "paired" ? <span className="badge bg-slate-100 text-slate-500">{k.pairing_status}</span>
                        : k.online ? <span className="badge bg-emerald-100 text-emerald-700"><Wifi className="h-3 w-3" /> online</span>
                        : <span className="badge bg-red-100 text-red-700"><WifiOff className="h-3 w-3" /> offline</span>}
                    </td>
                    <td className="td font-semibold">{k.room_number ?? "—"}</td>
                    <td className="td font-mono text-xs">{k.device_uid}<div className="text-slate-400">{k.ip_address ?? ""}</div></td>
                    <td className="td text-xs">{k.firmware_version ?? "—"}</td>
                    <td className="td text-xs">{k.wifi_rssi != null ? `${k.wifi_rssi} dBm` : "—"}</td>
                    <td className="td text-xs">{k.offline_queue_depth}</td>
                    <td className="td text-xs">{formatDateTime(k.last_seen_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
