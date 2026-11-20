import { useEffect, useState, type FormEvent } from "react";
import { ArrowDown, ArrowUp, Plus, Save, X } from "lucide-react";
import { ErrorNote, PageHeader, Spinner } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function SettingsPage() {
  const { school, reloadSchool } = useAuth();
  const [zones, setZones] = useState<string[]>([]);
  const [f, setF] = useState<null | { name: string; address: string; timezone: string; dest: string[]; day: number; week: number; minutes: number; pin: string }>(null);
  const [newDest, setNewDest] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<string[]>("/api/v1/schools/timezones").then(setZones).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (school) setF({ name: school.name, address: school.address ?? "", timezone: school.timezone, dest: [...school.kiosk_destinations_json], day: school.flag_threshold_count, week: school.flag_threshold_weekly_count, minutes: school.flag_duration_minutes, pin: "" });
  }, [school]);
  if (!f || !school) return <Spinner />;

  const move = (i: number, d: number) => {
    const dest = [...f.dest];
    const j = i + d;
    if (j < 0 || j >= dest.length) return;
    [dest[i], dest[j]] = [dest[j], dest[i]];
    setF({ ...f, dest });
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setMsg(null);
    try {
      await api(`/api/v1/schools/${school.id}`, {
        method: "PATCH",
        json: { name: f.name, address: f.address || null, timezone: f.timezone, kiosk_destinations_json: f.dest, flag_threshold_count: f.day, flag_threshold_weekly_count: f.week, flag_duration_minutes: f.minutes, ...(f.pin ? { kiosk_admin_pin: f.pin } : {}) },
      });
      await reloadSchool();
      setMsg("Saved. Kiosks pick up changes on their next heartbeat (≤ 30 s).");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };

  return (
    <form onSubmit={submit} className="max-w-3xl space-y-6">
      <PageHeader title="School settings" actions={<button className="btn-primary"><Save className="h-4 w-4" /> Save changes</button>} />
      <section className="card space-y-4 p-5">
        <h2 className="font-bold">School</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div><label className="label">Name</label><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div><label className="label">Timezone (kiosk LOCAL clock)</label><select className="input" value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })}>{zones.map((z) => <option key={z}>{z}</option>)}</select></div>
        </div>
        <div><label className="label">Address</label><input className="input" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></div>
      </section>
      <section className="card space-y-3 p-5">
        <h2 className="font-bold">Kiosk sign-out destinations <span className="text-sm font-normal text-slate-500">(up to 6, shown in this order)</span></h2>
        <ul className="space-y-2">
          {f.dest.map((d, i) => (
            <li key={d} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2">
              <span className="w-6 text-sm font-bold text-slate-400">{i + 1}</span>
              <span className="flex-1 font-medium">{d}</span>
              <button type="button" className="btn-ghost p-1" onClick={() => move(i, -1)} aria-label="Move up"><ArrowUp className="h-4 w-4" /></button>
              <button type="button" className="btn-ghost p-1" onClick={() => move(i, 1)} aria-label="Move down"><ArrowDown className="h-4 w-4" /></button>
              <button type="button" className="btn-ghost p-1 text-red-600" onClick={() => setF({ ...f, dest: f.dest.filter((x) => x !== d) })} aria-label="Remove" disabled={f.dest.length <= 1}><X className="h-4 w-4" /></button>
            </li>
          ))}
        </ul>
        {f.dest.length < 6 && (
          <div className="flex gap-2">
            <input className="input" maxLength={24} placeholder="New destination (e.g. Nurse)" value={newDest} onChange={(e) => setNewDest(e.target.value)} />
            <button type="button" className="btn-secondary" onClick={() => { if (newDest.trim() && !f.dest.some((x) => x.toLowerCase() === newDest.trim().toLowerCase())) { setF({ ...f, dest: [...f.dest, newDest.trim()] }); setNewDest(""); } }}><Plus className="h-4 w-4" /> Add</button>
          </div>
        )}
        <p className="text-xs text-slate-500">Built-in kiosk icons: Washroom, Office, Library, Guidance, Water, Other (others use a generic icon).</p>
      </section>
      <section className="card grid gap-4 p-5 sm:grid-cols-3">
        <h2 className="font-bold sm:col-span-3">Flag thresholds</h2>
        <div><label className="label">Max sign-outs / day</label><input type="number" min={0} max={50} className="input" value={f.day} onChange={(e) => setF({ ...f, day: +e.target.value })} /></div>
        <div><label className="label">Max sign-outs / week</label><input type="number" min={0} max={200} className="input" value={f.week} onChange={(e) => setF({ ...f, week: +e.target.value })} /></div>
        <div><label className="label">Max minutes out</label><input type="number" min={1} max={240} className="input" value={f.minutes} onChange={(e) => setF({ ...f, minutes: +e.target.value })} /></div>
        <p className="text-xs text-slate-500 sm:col-span-3">A flag is raised when a student exceeds a limit. Set a count to 0 to disable it.</p>
      </section>
      <section className="card p-5">
        <h2 className="font-bold">Kiosk room-admin PIN</h2>
        <p className="mb-3 text-sm text-slate-500">Required to open a kiosk's hidden diagnostics menu (5-second hold on the clock) and to factory-reset it.</p>
        <input className="input max-w-xs" inputMode="numeric" pattern="\d{4,8}" placeholder="New 4–8 digit PIN (leave blank to keep)" value={f.pin} onChange={(e) => setF({ ...f, pin: e.target.value.replace(/\D/g, "").slice(0, 8) })} />
      </section>
      <ErrorNote error={error} />
      {msg && <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{msg}</div>}
    </form>
  );
}
