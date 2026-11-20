import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Pencil, ShieldCheck, ShieldPlus } from "lucide-react";
import { ErrorNote, Modal, Spinner } from "../components/ui";
import { api, ApiError, type Classroom, type Exemption, type Flag, type LocateResult } from "../lib/api";
import { isAdminRole, useAuth } from "../lib/auth";
import { formatDateTime } from "../lib/live";
import { LocateCard } from "./LockdownPage";
import { StudentModal } from "./StudentsPage";
import { FlagRow } from "./FlagsPage";

const CATEGORIES = ["Medical Accommodation", "IEP / Special Education", "Administrative Pass", "Counseling / Guidance", "Other"];

export default function StudentPage() {
  const { id } = useParams();
  const { schoolId, school, user } = useAuth();
  const admin = isAdminRole(user);
  const [loc, setLoc] = useState<LocateResult | null>(null);
  const [exemptions, setExemptions] = useState<Exemption[]>([]);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [rooms, setRooms] = useState<Classroom[]>([]);
  const [addEx, setAddEx] = useState(false);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    if (!id || !schoolId) return;
    const [l, ex, fl] = await Promise.all([
      api<LocateResult>(`/api/v1/students/${id}/locate`),
      api<Exemption[]>(`/api/v1/students/${id}/exemptions`),
      api<Flag[]>(`/api/v1/flags?school_id=${schoolId}&student_id=${id}&include_suppressed=true`),
    ]);
    setLoc(l);
    setExemptions(ex);
    setFlags(fl);
  }, [id, schoolId]);
  useEffect(() => {
    load().catch(() => undefined);
    if (schoolId) api<Classroom[]>(`/api/v1/schools/${schoolId}/classrooms`).then(setRooms).catch(() => undefined);
  }, [load, schoolId]);

  if (!loc) return <Spinner />;
  const deactivate = async (ex: Exemption) => {
    if (!confirm("End this accommodation now?")) return;
    await api(`/api/v1/exemptions/${ex.id}`, { method: "PATCH", json: { is_active: false } });
    load();
  };

  return (
    <>
      <div className="mb-3 flex items-center justify-between">
        <Link to="/students" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" /> Students</Link>
        {admin && <button className="btn-secondary" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" /> Edit profile</button>}
      </div>
      <LocateCard r={loc} tz={school?.timezone} />

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section className="card">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <h2 className="font-bold">Approved accommodations</h2>
            <button className="btn-secondary py-1.5" onClick={() => setAddEx(true)}><ShieldPlus className="h-4 w-4" /> Add Exemption / Reason</button>
          </div>
          {exemptions.length === 0 ? <p className="p-4 text-sm text-slate-500">None on file.</p> : (
            <ul className="divide-y divide-slate-100">
              {exemptions.map((ex) => (
                <li key={ex.id} className="space-y-1 px-4 py-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-2 font-semibold text-emerald-700">
                      <ShieldCheck className="h-4 w-4" />
                      {ex.redacted ? "Approved Accommodation on File" : ex.reason_category}
                    </span>
                    <span className={`badge ${ex.is_active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{ex.is_active ? "active" : "ended"}</span>
                  </div>
                  <div className="text-slate-600">Applies to: {ex.applies_to_destinations.join(", ")}</div>
                  <div className="text-xs text-slate-500">From {formatDateTime(ex.valid_from, school?.timezone)} {ex.valid_until ? `until ${formatDateTime(ex.valid_until, school?.timezone)}` : "· no end date (school year)"}</div>
                  {!ex.redacted && ex.reason_notes && <div className="rounded bg-slate-50 p-2 text-slate-700">{ex.reason_notes}</div>}
                  {ex.redacted && <div className="text-xs italic text-slate-400">Details are restricted to school administrators.</div>}
                  {ex.is_active && admin && <button className="text-xs font-semibold text-red-600" onClick={() => deactivate(ex)}>End accommodation</button>}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card">
          <h2 className="border-b border-slate-100 px-4 py-3 font-bold">Flags</h2>
          {flags.length === 0 ? <p className="p-4 text-sm text-slate-500">No flags.</p> : (
            <ul className="divide-y divide-slate-100">{flags.map((f) => <FlagRow key={f.id} f={f} onChanged={load} hideName />)}</ul>
          )}
        </section>
      </div>
      {addEx && <ExemptionModal studentId={loc.student.id} destinations={school?.kiosk_destinations_json ?? []} onClose={() => setAddEx(false)} onSaved={() => { setAddEx(false); load(); }} />}
      {editing && <StudentModal rooms={rooms} student={loc.student} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); load(); }} />}
    </>
  );
}

function ExemptionModal({ studentId, destinations, onClose, onSaved }: { studentId: string; destinations: string[]; onClose: () => void; onSaved: () => void }) {
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [notes, setNotes] = useState("");
  const [scope, setScope] = useState<string[]>(["ALL"]);
  const [until, setUntil] = useState("");
  const [error, setError] = useState<string | null>(null);
  const toggle = (d: string) => {
    if (d === "ALL") return setScope(["ALL"]);
    const next = scope.filter((x) => x !== "ALL");
    setScope(next.includes(d) ? next.filter((x) => x !== d) : [...next, d]);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/v1/exemptions", {
        method: "POST",
        json: {
          student_id: studentId,
          reason_category: category,
          reason_notes: notes || null,
          applies_to_destinations: scope.length ? scope : ["ALL"],
          valid_until: until ? new Date(`${until}T23:59:59`).toISOString() : null,
        },
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };
  return (
    <Modal open onClose={onClose} title="Add exemption / reason">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label">Category</label>
          <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>
        </div>
        <div>
          <label className="label">Applies to destinations</label>
          <div className="flex flex-wrap gap-2">
            {["ALL", ...destinations].map((d) => (
              <button type="button" key={d} onClick={() => toggle(d)} className={`badge px-3 py-1 ${scope.includes(d) ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600"}`}>{d}</button>
            ))}
          </div>
        </div>
        <div>
          <label className="label">Notes (encrypted, admins only)</label>
          <textarea className="input" rows={3} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Approved medical accommodation: frequent washroom access required" />
        </div>
        <div>
          <label className="label">Valid until (leave blank for the school year)</label>
          <input type="date" className="input" value={until} onChange={(e) => setUntil(e.target.value)} />
        </div>
        <p className="text-xs text-slate-500">While active, matching sign-outs will not raise behavioural flags. Staff only see "Approved Accommodation on File".</p>
        <ErrorNote error={error} />
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary">Save</button></div>
      </form>
    </Modal>
  );
}
