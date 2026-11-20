import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Plus, Upload } from "lucide-react";
import { AccommodationBadge, ErrorNote, Modal, PageHeader, Spinner } from "../components/ui";
import { api, ApiError, type Classroom, type Student } from "../lib/api";
import { isAdminRole, useAuth } from "../lib/auth";

export default function StudentsPage() {
  const { schoolId, user } = useAuth();
  const admin = isAdminRole(user);
  const [q, setQ] = useState("");
  const [students, setStudents] = useState<Student[] | null>(null);
  const [rooms, setRooms] = useState<Classroom[]>([]);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    if (!schoolId) return;
    setStudents(await api<Student[]>(`/api/v1/students?school_id=${schoolId}&limit=500${q.trim().length >= 2 ? `&q=${encodeURIComponent(q.trim())}` : ""}`));
  }, [schoolId, q]);
  useEffect(() => {
    const t = setTimeout(() => load().catch(() => undefined), 250);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => {
    if (schoolId) api<Classroom[]>(`/api/v1/schools/${schoolId}/classrooms`).then(setRooms).catch(() => undefined);
  }, [schoolId]);

  const roomNo = (id: string | null) => rooms.find((r) => r.id === id)?.room_number ?? "—";
  return (
    <>
      <PageHeader
        title="Students"
        subtitle="Students are auto-registered the first time their card is scanned, or bulk-imported from a CSV roster."
        actions={admin && (
          <>
            <button className="btn-secondary" onClick={() => setImporting(true)}><Upload className="h-4 w-4" /> Import CSV</button>
            <button className="btn-primary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> Add student</button>
          </>
        )}
      />
      <input className="input mb-4 max-w-sm" placeholder="Filter by name or number…" value={q} onChange={(e) => setQ(e.target.value)} />
      {!students ? <Spinner /> : (
        <div className="card overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-100">
            <thead><tr><th className="th">Name</th><th className="th">Student #</th><th className="th">Homeroom</th><th className="th">Grade</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-50">
              {students.map((s) => (
                <tr key={s.id} className="hover:bg-slate-50">
                  <td className="td"><Link to={`/students/${s.id}`} className="font-semibold text-slate-900 hover:underline">{s.last_name}, {s.first_name}</Link></td>
                  <td className="td">{s.student_number ?? "—"}</td>
                  <td className="td">{roomNo(s.homeroom_classroom_id)}</td>
                  <td className="td">{s.grade ?? "—"}</td>
                  <td className="td space-x-1 text-right">
                    {s.has_accommodation && <AccommodationBadge />}
                    {s.auto_registered && <span className="badge bg-slate-100 text-slate-600" title="Created automatically from a card scan">auto</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {students.length === 0 && <p className="p-6 text-center text-sm text-slate-500">No students yet.</p>}
        </div>
      )}
      {adding && <StudentModal rooms={rooms} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); load(); }} />}
      {importing && <ImportModal onClose={() => setImporting(false)} onDone={load} />}
    </>
  );
}

export function StudentModal({ rooms, student, onClose, onSaved }: { rooms: Classroom[]; student?: Student; onClose: () => void; onSaved: () => void }) {
  const { schoolId } = useAuth();
  const [f, setF] = useState({
    first_name: student?.first_name ?? "",
    last_name: student?.last_name ?? "",
    student_number: student?.student_number ?? "",
    homeroom_classroom_id: student?.homeroom_classroom_id ?? "",
    grade: student?.grade ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const json = { ...f, student_number: f.student_number || null, homeroom_classroom_id: f.homeroom_classroom_id || null, grade: f.grade || null };
    try {
      if (student) await api(`/api/v1/students/${student.id}`, { method: "PATCH", json });
      else await api(`/api/v1/students?school_id=${schoolId}`, { method: "POST", json });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open onClose={onClose} title={student ? "Edit student" : "Add student"}>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label">First name</label><input className="input" required value={f.first_name} onChange={set("first_name")} /></div>
          <div><label className="label">Last name</label><input className="input" required value={f.last_name} onChange={set("last_name")} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label">Student number</label><input className="input" value={f.student_number} onChange={set("student_number")} /></div>
          <div><label className="label">Grade</label><input className="input" value={f.grade} onChange={set("grade")} /></div>
        </div>
        <div>
          <label className="label">Homeroom</label>
          <select className="input" value={f.homeroom_classroom_id} onChange={set("homeroom_classroom_id")}>
            <option value="">— none —</option>
            {rooms.map((r) => <option key={r.id} value={r.id}>Room {r.room_number} {r.room_name && `· ${r.room_name}`}</option>)}
          </select>
        </div>
        <ErrorNote error={error} />
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary">Save</button></div>
      </form>
    </Modal>
  );
}

function ImportModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { schoolId } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<{ created: number; updated: number; skipped: number; errors: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      setResult(await api(`/api/v1/students/import?school_id=${schoolId}`, { method: "POST", body: fd }));
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Import failed");
    }
  };
  return (
    <Modal open onClose={onClose} title="Import roster (CSV)">
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-slate-600">Header row required. Columns: <code className="rounded bg-slate-100 px-1">first_name, last_name</code> and optionally <code className="rounded bg-slate-100 px-1">student_number, homeroom, grade</code>. Existing students are matched by number, then by name.</p>
        <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm" />
        <ErrorNote error={error} />
        {result && (
          <div className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
            Created {result.created}, updated {result.updated}, skipped {result.skipped}.
            {result.errors.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-amber-800">{result.errors.map((x) => <li key={x}>{x}</li>)}</ul>}
          </div>
        )}
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Close</button><button className="btn-primary" disabled={!file}>Import</button></div>
      </form>
    </Modal>
  );
}
