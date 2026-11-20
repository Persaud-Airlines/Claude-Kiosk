import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowRightLeft, CheckCircle2, HelpCircle, MapPin, Search, ShieldAlert, ShieldOff } from "lucide-react";
import { Empty, ErrorNote, EventBadge, PageHeader } from "../components/ui";
import { api, ApiError, type LocateResult } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatTime, formatUtc, useLiveFeed } from "../lib/live";

interface RollStudent {
  student_id: string;
  first_name: string;
  last_name: string;
  homeroom: string | null;
  room_number?: string | null;
  destination?: string | null;
  last_event_at?: string;
  is_cross_room?: boolean;
}
interface RollCall {
  lockdown_active: boolean;
  window_start_utc: string;
  total_students: number;
  accounted_count: number;
  out_of_room_count: number;
  unaccounted_count: number;
  rooms: { classroom_id: string; room_number: string; room_name: string | null; students: RollStudent[] }[];
  out_of_room: RollStudent[];
  unaccounted: RollStudent[];
}

export default function LockdownPage() {
  const { schoolId, school, user, reloadSchool } = useAuth();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [results, setResults] = useState<LocateResult[] | null>(null);
  const [roll, setRoll] = useState<RollCall | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tz = school?.timezone;

  const search = useCallback(async (term: string) => {
    if (!schoolId || term.trim().length < 2) return;
    setError(null);
    try {
      setResults(await api<LocateResult[]>(`/api/v1/schools/${schoolId}/locate?q=${encodeURIComponent(term.trim())}`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Lookup failed");
    }
  }, [schoolId]);

  const loadRoll = useCallback(async () => {
    if (schoolId) setRoll(await api<RollCall>(`/api/v1/schools/${schoolId}/roll-call`));
  }, [schoolId]);

  useEffect(() => {
    const initial = params.get("q");
    if (initial) {
      setQ(initial);
      search(initial);
    }
  }, [params, search]);
  useEffect(() => {
    loadRoll().catch(() => undefined);
  }, [loadRoll]);
  useLiveFeed(schoolId, (m) => {
    if (m.type === "lockdown") reloadSchool();
    loadRoll().catch(() => undefined);
    if (q.trim().length >= 2) search(q);
  }, () => loadRoll().catch(() => undefined), 4000);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams(q ? { q } : {});
    search(q);
  };

  const toggle = async (active: boolean) => {
    if (!schoolId) return;
    if (!confirm(active ? "START a lockdown roll-call for the whole school?" : "END the lockdown roll-call?")) return;
    try {
      await api(`/api/v1/schools/${schoolId}/lockdown?active=${active}`, { method: "POST" });
      await reloadSchool();
      await loadRoll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };

  return (
    <>
      <PageHeader
        title="Emergency / Lockdown Locator"
        subtitle="Find any student's current confirmed location and see who is accounted for in every classroom."
        actions={
          school?.lockdown_active ? (
            user?.role !== "TEACHER" && <button className="btn-secondary" onClick={() => toggle(false)}><ShieldOff className="h-4 w-4" /> End lockdown</button>
          ) : (
            <button className="btn-danger" onClick={() => toggle(true)}><ShieldAlert className="h-4 w-4" /> Start lockdown roll-call</button>
          )
        }
      />

      <form onSubmit={submit} className="card flex items-center gap-3 border-2 border-red-300 p-3">
        <Search className="h-6 w-6 text-red-600" />
        <input autoFocus className="w-full bg-transparent text-xl font-semibold text-slate-900 placeholder:text-slate-400 focus:outline-none" placeholder="Type a student's name or number…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn-danger px-6 py-3 text-base">Locate</button>
      </form>
      <div className="mt-2"><ErrorNote error={error} /></div>

      {results && (
        <div className="mt-4 space-y-4">
          {results.length === 0 && <div className="card"><Empty title="No matching student">Check the spelling, or try the student number.</Empty></div>}
          {results.map((r) => <LocateCard key={r.student.id} r={r} tz={tz} />)}
        </div>
      )}

      {roll && (
        <section className="mt-8">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-lg font-bold text-slate-900">{roll.lockdown_active ? "Lockdown Roll-Call" : "Today's Roll-Call"}</h2>
              <p className="text-xs text-slate-500">Counting sign-ins since {formatTime(roll.window_start_utc, tz)} ({formatUtc(roll.window_start_utc)})</p>
            </div>
            <div className="flex gap-2 text-sm">
              <span className="badge bg-emerald-100 px-3 py-1 text-emerald-800"><CheckCircle2 className="h-4 w-4" /> {roll.accounted_count} accounted</span>
              <span className="badge bg-amber-100 px-3 py-1 text-amber-800">{roll.out_of_room_count} signed out</span>
              <span className="badge bg-red-100 px-3 py-1 text-red-800"><HelpCircle className="h-4 w-4" /> {roll.unaccounted_count} unknown</span>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {roll.rooms.map((room) => (
              <div key={room.classroom_id} className="card">
                <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
                  <Link to={`/classrooms/${room.classroom_id}`} className="font-bold hover:underline">Room {room.room_number}</Link>
                  <span className="text-xs text-slate-500">{room.room_name} · {room.students.length}</span>
                </div>
                <ul className="max-h-56 divide-y divide-slate-50 overflow-y-auto">
                  {room.students.length === 0 && <li className="px-4 py-2 text-xs text-slate-400">No check-ins</li>}
                  {room.students.map((s) => (
                    <li key={s.student_id} className="flex items-center justify-between px-4 py-1.5 text-sm">
                      <Link to={`/students/${s.student_id}`} className="hover:underline">{s.first_name} {s.last_name}</Link>
                      {s.is_cross_room && <span className="badge bg-amber-100 text-amber-800" title={`Homeroom ${s.homeroom ?? "?"}`}><ArrowRightLeft className="h-3 w-3" /> HR {s.homeroom ?? "?"}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <RollList title="Signed out (not yet back)" tone="amber" items={roll.out_of_room} detail={(s) => `→ ${s.destination ?? "?"} from Room ${s.room_number ?? "?"}`} />
            <RollList title="Not checked in" tone="red" items={roll.unaccounted} detail={(s) => (s.homeroom ? `Homeroom ${s.homeroom}` : "")} />
          </div>
        </section>
      )}
    </>
  );
}

function RollList({ title, items, tone, detail }: { title: string; items: RollStudent[]; tone: "amber" | "red"; detail: (s: RollStudent) => string }) {
  return (
    <div className="card">
      <h3 className={`border-b border-slate-100 px-4 py-2 text-sm font-bold ${tone === "red" ? "text-red-700" : "text-amber-700"}`}>{title} ({items.length})</h3>
      <ul className="max-h-72 divide-y divide-slate-50 overflow-y-auto">
        {items.map((s) => (
          <li key={s.student_id} className="flex justify-between px-4 py-1.5 text-sm">
            <Link to={`/students/${s.student_id}`} className="hover:underline">{s.first_name} {s.last_name}</Link>
            <span className="text-xs text-slate-500">{detail(s)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function LocateCard({ r, tz }: { r: LocateResult; tz?: string }) {
  const tone = r.state === "IN_ROOM" ? "border-emerald-400 bg-emerald-50" : r.state === "OUT" ? "border-amber-400 bg-amber-50" : "border-slate-300 bg-slate-50";
  return (
    <div className={`card border-2 ${tone} p-5`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to={`/students/${r.student.id}`} className="text-2xl font-extrabold text-slate-900 hover:underline">{r.student.first_name} {r.student.last_name}</Link>
          <div className="text-sm text-slate-500">
            {r.student.student_number && <>#{r.student.student_number} · </>}Homeroom {r.homeroom_number ?? "—"}
          </div>
        </div>
        {r.is_cross_room && <span className="badge bg-amber-200 px-3 py-1 text-amber-900"><AlertTriangle className="h-4 w-4" /> Not in homeroom</span>}
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <div className="label">Current confirmed location</div>
          <div className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <MapPin className="h-6 w-6 text-red-600" />
            {r.state === "IN_ROOM" && <>Room {r.current_room_number}{r.current_room_name && <span className="text-base font-medium text-slate-500">({r.current_room_name})</span>}</>}
            {r.state === "OUT" && <>Out → {r.destination} <span className="text-base font-medium text-slate-500">(left Room {r.current_room_number})</span></>}
            {r.state === "NO_ACTIVITY" && <span className="text-slate-500">No kiosk activity today</span>}
          </div>
        </div>
        <div>
          <div className="label">Last action</div>
          {r.last_event_type ? (
            <div className="text-lg font-semibold text-slate-800">
              {r.last_event_type === "SIGN_IN" ? "SIGNED IN" : "SIGNED OUT"} at {formatTime(r.last_event_at_utc, tz)} <span className="text-sm font-normal text-slate-500">({formatUtc(r.last_event_at_utc)})</span>
            </div>
          ) : <div className="text-slate-500">—</div>}
        </div>
      </div>
      {r.timeline.length > 0 && (
        <div className="mt-4">
          <div className="label">Movement timeline</div>
          <ol className="relative ml-2 border-l-2 border-slate-200">
            {r.timeline.slice(0, 12).map((e) => (
              <li key={e.id} className="mb-2 ml-4">
                <span className={`absolute -left-[7px] mt-1.5 h-3 w-3 rounded-full ${e.event_type === "SIGN_IN" ? "bg-teal-500" : "bg-orange-500"}`} />
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono tabular-nums text-slate-600">{formatTime(e.occurred_at_utc, tz)}</span>
                  <EventBadge type={e.event_type} />
                  <span>Room {e.room_number}{e.destination && <> → {e.destination}</>}</span>
                  {e.is_lockdown_cross_room && <span className="badge bg-amber-100 text-amber-800">cross-room</span>}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
