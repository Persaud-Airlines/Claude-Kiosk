import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, LogIn, LogOut, Radio } from "lucide-react";
import { EventFeed, OutNowList } from "../components/feeds";
import { ErrorNote, Modal, PageHeader, Spinner } from "../components/ui";
import { api, ApiError, type Classroom, type HallEvent, type OutNow, type Student } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLiveFeed } from "../lib/live";

export default function ClassroomPage() {
  const { id } = useParams();
  const { schoolId, school } = useAuth();
  const [room, setRoom] = useState<Classroom | null>(null);
  const [events, setEvents] = useState<HallEvent[]>([]);
  const [out, setOut] = useState<OutNow[]>([]);
  const [manual, setManual] = useState<"SIGN_OUT" | "SIGN_IN" | null>(null);

  const load = useCallback(async () => {
    if (!schoolId || !id) return;
    const [rooms, ev, o] = await Promise.all([
      api<Classroom[]>(`/api/v1/schools/${schoolId}/classrooms`),
      api<HallEvent[]>(`/api/v1/classrooms/${id}/events?limit=200`),
      api<OutNow[]>(`/api/v1/schools/${schoolId}/out-now?classroom_id=${id}`),
    ]);
    setRoom(rooms.find((r) => r.id === id) ?? null);
    setEvents(ev);
    setOut(o);
  }, [schoolId, id]);

  useEffect(() => {
    load().catch(() => undefined);
    const t = setInterval(() => load().catch(() => undefined), 30000);
    return () => clearInterval(t);
  }, [load]);
  const live = useLiveFeed(schoolId, () => load().catch(() => undefined), () => load().catch(() => undefined));

  if (!room) return <Spinner />;
  return (
    <>
      <Link to="/classrooms" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> All classrooms
      </Link>
      <PageHeader
        title={`Room ${room.room_number}`}
        subtitle={
          <span className="inline-flex items-center gap-2">
            {room.room_name}
            <Radio className={`h-3.5 w-3.5 ${live ? "text-emerald-500" : "text-amber-500"}`} />
            <span className={room.kiosk_online ? "text-emerald-600" : "text-slate-400"}>
              {room.kiosk_online === null ? "no kiosk paired" : room.kiosk_online ? "kiosk online" : "kiosk offline"}
            </span>
          </span>
        }
        actions={
          <>
            <button className="btn-secondary" onClick={() => setManual("SIGN_OUT")}><LogOut className="h-4 w-4" /> Manual sign-out</button>
            <button className="btn-secondary" onClick={() => setManual("SIGN_IN")}><LogIn className="h-4 w-4" /> Manual sign-in</button>
          </>
        }
      />
      <div className="grid gap-6 xl:grid-cols-5">
        <section className="card xl:col-span-2">
          <h2 className="border-b border-slate-100 px-4 py-3 font-bold">Out of this room now ({out.length})</h2>
          <OutNowList items={out} tz={school?.timezone} showRoom={false} />
        </section>
        <section className="card xl:col-span-3">
          <h2 className="border-b border-slate-100 px-4 py-3 font-bold">Today's activity</h2>
          <EventFeed events={events} tz={school?.timezone} showRoom={false} />
        </section>
      </div>
      {manual && (
        <ManualEventModal
          type={manual}
          classroomId={room.id}
          destinations={school?.kiosk_destinations_json ?? []}
          onClose={() => setManual(null)}
          onDone={() => {
            setManual(null);
            load();
          }}
        />
      )}
    </>
  );
}

export function ManualEventModal({ type, classroomId, destinations, onClose, onDone, presetStudent }: {
  type: "SIGN_OUT" | "SIGN_IN";
  classroomId: string;
  destinations: string[];
  onClose: () => void;
  onDone: () => void;
  presetStudent?: Student;
}) {
  const { schoolId } = useAuth();
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<Student[]>([]);
  const [student, setStudent] = useState<Student | null>(presetStudent ?? null);
  const [dest, setDest] = useState(destinations[0] ?? "Other");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (q.trim().length < 2 || !schoolId) return setMatches([]);
    const t = setTimeout(() => {
      api<Student[]>(`/api/v1/students?school_id=${schoolId}&q=${encodeURIComponent(q)}&limit=8`).then(setMatches).catch(() => undefined);
    }, 250);
    return () => clearTimeout(t);
  }, [q, schoolId]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!student) return setError("Choose a student");
    try {
      await api("/api/v1/events/staff", {
        method: "POST",
        json: { student_id: student.id, classroom_id: classroomId, event_type: type, destination: type === "SIGN_OUT" ? dest : null, notes: notes || null },
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };

  return (
    <Modal open onClose={onClose} title={type === "SIGN_OUT" ? "Manual sign-out" : "Manual sign-in"}>
      <form onSubmit={submit} className="space-y-4">
        {student ? (
          <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
            <span className="font-semibold">{student.first_name} {student.last_name}</span>
            {!presetStudent && <button type="button" className="text-sm text-brand-600" onClick={() => setStudent(null)}>change</button>}
          </div>
        ) : (
          <div>
            <label className="label">Student</label>
            <input className="input" autoFocus placeholder="Search by name or student number" value={q} onChange={(e) => setQ(e.target.value)} />
            <ul className="mt-1 max-h-48 overflow-y-auto rounded-lg border border-slate-100">
              {matches.map((m) => (
                <li key={m.id}>
                  <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-slate-50" onClick={() => setStudent(m)}>
                    {m.first_name} {m.last_name} {m.student_number && <span className="text-slate-400">· {m.student_number}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {type === "SIGN_OUT" && (
          <div>
            <label className="label">Destination</label>
            <select className="input" value={dest} onChange={(e) => setDest(e.target.value)}>
              {destinations.map((d) => <option key={d}>{d}</option>)}
            </select>
          </div>
        )}
        <div>
          <label className="label">Note (optional)</label>
          <input className="input" maxLength={300} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        <ErrorNote error={error} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary">Record</button>
        </div>
      </form>
    </Modal>
  );
}
