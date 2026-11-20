import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CheckCircle2, Link2 } from "lucide-react";
import { ErrorNote, PageHeader } from "../components/ui";
import { api, ApiError, type Classroom } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function PairPage() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  return (
    <div className="mx-auto max-w-lg">
      <PageHeader title="Pair a classroom kiosk" subtitle="Assign the kiosk showing this code to a room." />
      <div className="card p-5">
        <PairForm initialCode={params.get("code") ?? ""} deviceUid={params.get("uid") ?? undefined} onPaired={() => setTimeout(() => nav("/kiosks"), 1800)} />
      </div>
    </div>
  );
}

export function PairForm({ initialCode = "", deviceUid, onPaired }: { initialCode?: string; deviceUid?: string; onPaired: () => void }) {
  const { schoolId } = useAuth();
  const [code, setCode] = useState(initialCode);
  const [rooms, setRooms] = useState<Classroom[]>([]);
  const [roomId, setRoomId] = useState("");
  const [newRoom, setNewRoom] = useState("");
  const [newRoomName, setNewRoomName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    if (schoolId) api<Classroom[]>(`/api/v1/schools/${schoolId}/classrooms`).then((r) => {
      setRooms(r);
      if (r.length) setRoomId(r[0].id);
    }).catch(() => undefined);
  }, [schoolId]);

  const format = (v: string) => {
    const c = v.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
    return c.length > 4 ? `${c.slice(0, 4)}-${c.slice(4)}` : c;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const body = roomId === "__new"
        ? { pairing_code: code, device_uid: deviceUid, school_id: schoolId, new_room_number: newRoom, new_room_name: newRoomName || null }
        : { pairing_code: code, device_uid: deviceUid, school_id: schoolId, classroom_id: roomId };
      const r = await api<{ room_number: string }>("/api/v1/kiosks/claim", { method: "POST", json: body });
      setDone(r.room_number);
      onPaired();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Pairing failed");
    }
  };

  if (done) return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <CheckCircle2 className="h-12 w-12 text-emerald-500" />
      <p className="text-lg font-bold">Kiosk paired to Room {done}</p>
      <p className="text-sm text-slate-500">The kiosk will switch to its home screen within a few seconds.</p>
    </div>
  );

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label className="label">Pairing code shown on the kiosk</label>
        <input className="input text-center font-mono text-3xl font-bold tracking-widest" placeholder="XXXX-XXXX" required value={code} onChange={(e) => setCode(format(e.target.value))} autoFocus={!initialCode} />
        {deviceUid && <p className="mt-1 flex items-center gap-1 text-xs text-slate-500"><Link2 className="h-3 w-3" /> Device {deviceUid}</p>}
      </div>
      <div>
        <label className="label">Classroom</label>
        <select className="input" value={roomId} onChange={(e) => setRoomId(e.target.value)}>
          {rooms.map((r) => <option key={r.id} value={r.id}>Room {r.room_number}{r.room_name ? ` · ${r.room_name}` : ""}</option>)}
          <option value="__new">+ New room…</option>
        </select>
      </div>
      {roomId === "__new" && (
        <div className="grid grid-cols-2 gap-3">
          <input className="input" required placeholder="Room # (e.g. 204)" value={newRoom} onChange={(e) => setNewRoom(e.target.value)} />
          <input className="input" placeholder="Name (optional)" value={newRoomName} onChange={(e) => setNewRoomName(e.target.value)} />
        </div>
      )}
      <ErrorNote error={error} />
      <button className="btn-primary w-full py-2.5" disabled={code.length !== 9}>Pair kiosk</button>
    </form>
  );
}
