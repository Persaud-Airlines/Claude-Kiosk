import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, DollarSign, Plus, Tablet, TrendingUp } from "lucide-react";
import { ErrorNote, Modal, PageHeader, Spinner, Stat } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";

interface SchoolRow { id: string; name: string; board: string | null; timezone: string; subscription_status: string; kiosks_total: number; kiosks_online: number; events_24h: number; lockdown_active: boolean }
interface Overview { schools_total: number; schools_active: number; schools_past_due: number; kiosks_total: number; kiosks_online: number; events_24h: number; mrr_cents: number; schools: SchoolRow[] }

export default function OverviewPage() {
  const { user, setSchoolId } = useAuth();
  const nav = useNavigate();
  const [ov, setOv] = useState<Overview | null>(null);
  const [creating, setCreating] = useState(false);
  const load = useCallback(async () => setOv(await api<Overview>("/api/v1/admin/overview")), []);
  useEffect(() => {
    if (user?.role === "SUPERSUDO") load().catch(() => undefined);
  }, [load, user]);
  if (user?.role !== "SUPERSUDO") return <p className="text-sm text-slate-500">Platform overview is limited to SUPERSUDO accounts.</p>;
  if (!ov) return <Spinner />;
  const open = (id: string) => {
    setSchoolId(id);
    nav("/");
  };
  const statusTone = (s: string) => (s === "active" ? "bg-emerald-100 text-emerald-800" : s === "trialing" ? "bg-sky-100 text-sky-800" : s === "past_due" || s === "unpaid" ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-600");
  return (
    <>
      <PageHeader title="Platform overview" subtitle="All onboarded schools and boards" actions={<button className="btn-primary" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> Provision school</button>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="MRR" value={`$${(ov.mrr_cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`} tone="green" icon={<DollarSign className="h-4 w-4" />} />
        <Stat label="Schools (paying)" value={`${ov.schools_active}/${ov.schools_total}`} icon={<Building2 className="h-4 w-4" />} />
        <Stat label="Kiosks online" value={`${ov.kiosks_online}/${ov.kiosks_total}`} tone={ov.kiosks_online < ov.kiosks_total ? "amber" : "green"} icon={<Tablet className="h-4 w-4" />} />
        <Stat label="Sign-ins/outs (24h)" value={ov.events_24h} tone="blue" icon={<TrendingUp className="h-4 w-4" />} />
      </div>
      <div className="card mt-6 overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-100">
          <thead><tr><th className="th">School</th><th className="th">Board</th><th className="th">Subscription</th><th className="th">Kiosks</th><th className="th">Events 24h</th><th className="th" /></tr></thead>
          <tbody className="divide-y divide-slate-50">
            {ov.schools.map((s) => (
              <tr key={s.id} className="hover:bg-slate-50">
                <td className="td font-semibold">{s.name} {s.lockdown_active && <span className="badge ml-1 bg-red-600 text-white">LOCKDOWN</span>}<div className="text-xs font-normal text-slate-400">{s.timezone}</div></td>
                <td className="td">{s.board ?? "—"}</td>
                <td className="td"><span className={`badge ${statusTone(s.subscription_status)}`}>{s.subscription_status.replace("_", " ")}</span></td>
                <td className="td">{s.kiosks_online}/{s.kiosks_total}</td>
                <td className="td">{s.events_24h}</td>
                <td className="td text-right"><button className="btn-secondary py-1" onClick={() => open(s.id)}>Open school →</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {creating && <CreateSchool onClose={() => setCreating(false)} onSaved={() => { setCreating(false); load(); }} />}
    </>
  );
}

function CreateSchool({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [zones, setZones] = useState<string[]>(["America/Toronto"]);
  const [f, setF] = useState({ name: "", address: "", timezone: "America/Toronto", board_name: "", principal_name: "", principal_email: "", principal_password: "" });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<string[]>("/api/v1/schools/timezones").then(setZones).catch(() => undefined);
  }, []);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const json = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || null]));
    try {
      await api("/api/v1/admin/schools", { method: "POST", json });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };
  return (
    <Modal open onClose={onClose} title="Provision a new school" wide>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><label className="label">School name</label><input className="input" required value={f.name} onChange={set("name")} /></div>
        <div><label className="label">Board / district</label><input className="input" value={f.board_name} onChange={set("board_name")} placeholder="optional" /></div>
        <div><label className="label">Timezone</label><select className="input" value={f.timezone} onChange={set("timezone")}>{zones.map((z) => <option key={z}>{z}</option>)}</select></div>
        <div className="sm:col-span-2"><label className="label">Address</label><input className="input" value={f.address} onChange={set("address")} /></div>
        <div className="sm:col-span-2 mt-2 text-sm font-bold text-slate-700">Principal account (optional)</div>
        <div><label className="label">Name</label><input className="input" value={f.principal_name} onChange={set("principal_name")} /></div>
        <div><label className="label">Email</label><input className="input" type="email" value={f.principal_email} onChange={set("principal_email")} /></div>
        <div className="sm:col-span-2"><label className="label">Temporary password</label><input className="input" minLength={12} value={f.principal_password} onChange={set("principal_password")} /></div>
        <div className="sm:col-span-2"><ErrorNote error={error} /></div>
        <div className="flex justify-end gap-2 sm:col-span-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary">Create school</button></div>
      </form>
    </Modal>
  );
}
