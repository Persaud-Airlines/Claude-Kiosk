import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { ErrorNote, Modal, PageHeader, Spinner } from "../components/ui";
import { api, ApiError, type Classroom, type User } from "../lib/api";
import { isAdminRole, useAuth } from "../lib/auth";

export default function ClassroomsPage() {
  const { schoolId, user } = useAuth();
  const admin = isAdminRole(user);
  const [rooms, setRooms] = useState<Classroom[] | null>(null);
  const [teachers, setTeachers] = useState<User[]>([]);
  const [editing, setEditing] = useState<Classroom | "new" | null>(null);

  const load = useCallback(async () => {
    if (!schoolId) return;
    setRooms(await api<Classroom[]>(`/api/v1/schools/${schoolId}/classrooms`));
    if (admin) setTeachers(await api<User[]>(`/api/v1/users?school_id=${schoolId}`));
  }, [schoolId, admin]);
  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  if (!rooms) return <Spinner />;
  const teacherName = (id: string | null) => teachers.find((t) => t.id === id)?.full_name ?? "—";
  return (
    <>
      <PageHeader title="Classrooms" subtitle="Select a room to open its live sign-in / sign-out feed." actions={admin && <button className="btn-primary" onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> Add classroom</button>} />
      <div className="card overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-100">
          <thead><tr><th className="th">Room</th><th className="th">Name</th>{admin && <th className="th">Teacher</th>}<th className="th">Kiosk</th><th className="th">Out now</th><th className="th" /></tr></thead>
          <tbody className="divide-y divide-slate-50">
            {rooms.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="td font-bold"><Link to={`/classrooms/${r.id}`} className="hover:underline">{r.room_number}</Link></td>
                <td className="td">{r.room_name ?? "—"}</td>
                {admin && <td className="td">{teacherName(r.assigned_teacher_id)}</td>}
                <td className="td">{r.kiosk_online === null ? <span className="text-slate-400">none</span> : r.kiosk_online ? <span className="text-emerald-600">online</span> : <span className="text-red-600">offline</span>}</td>
                <td className="td">{r.out_count}</td>
                <td className="td text-right">{admin && <button className="btn-ghost p-1" onClick={() => setEditing(r)} aria-label="Edit"><Pencil className="h-4 w-4" /></button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <RoomModal room={editing === "new" ? null : editing} teachers={teachers} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
    </>
  );
}

function RoomModal({ room, teachers, onClose, onSaved }: { room: Classroom | null; teachers: User[]; onClose: () => void; onSaved: () => void }) {
  const { schoolId } = useAuth();
  const [num, setNum] = useState(room?.room_number ?? "");
  const [name, setName] = useState(room?.room_name ?? "");
  const [teacher, setTeacher] = useState(room?.assigned_teacher_id ?? "");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const json = { room_number: num, room_name: name || null, assigned_teacher_id: teacher || null };
    try {
      if (room) await api(`/api/v1/schools/classrooms/${room.id}`, { method: "PATCH", json });
      else await api(`/api/v1/schools/${schoolId}/classrooms`, { method: "POST", json });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };
  const remove = async () => {
    if (!room || !confirm(`Delete Room ${room.room_number}?`)) return;
    try {
      await api(`/api/v1/schools/classrooms/${room.id}`, { method: "DELETE" });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };
  return (
    <Modal open onClose={onClose} title={room ? `Edit Room ${room.room_number}` : "Add classroom"}>
      <form onSubmit={submit} className="space-y-4">
        <div><label className="label">Room number</label><input className="input" required value={num} onChange={(e) => setNum(e.target.value)} placeholder="204 or Lab B" /></div>
        <div><label className="label">Room name</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Grade 12 Physics" /></div>
        <div>
          <label className="label">Assigned teacher</label>
          <select className="input" value={teacher} onChange={(e) => setTeacher(e.target.value)}>
            <option value="">— none —</option>
            {teachers.filter((t) => t.is_active).map((t) => <option key={t.id} value={t.id}>{t.full_name}</option>)}
          </select>
        </div>
        <ErrorNote error={error} />
        <div className="flex items-center justify-between">
          {room ? <button type="button" className="btn-ghost text-red-600" onClick={remove}><Trash2 className="h-4 w-4" /> Delete</button> : <span />}
          <div className="flex gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary">Save</button></div>
        </div>
      </form>
    </Modal>
  );
}
