import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, DoorOpen, Flag, Radio, Tablet } from "lucide-react";
import { EventFeed, OutNowList } from "../components/feeds";
import { PageHeader, Spinner, Stat } from "../components/ui";
import { api, type Classroom, type HallEvent, type OutNow } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLiveFeed } from "../lib/live";

interface Dash {
  sign_outs_today: number;
  sign_ins_today: number;
  currently_out: number;
  overdue: number;
  open_flags: number;
  kiosks_total: number;
  kiosks_online: number;
}

export default function DashboardPage() {
  const { schoolId, school, user, reloadSchool } = useAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [out, setOut] = useState<OutNow[]>([]);
  const [events, setEvents] = useState<HallEvent[]>([]);
  const [rooms, setRooms] = useState<Classroom[]>([]);

  const load = useCallback(async () => {
    if (!schoolId) return;
    const [d, o, e, r] = await Promise.all([
      api<Dash>(`/api/v1/schools/${schoolId}/dashboard`),
      api<OutNow[]>(`/api/v1/schools/${schoolId}/out-now`),
      api<HallEvent[]>(`/api/v1/schools/${schoolId}/events?limit=25`),
      api<Classroom[]>(`/api/v1/schools/${schoolId}/classrooms`),
    ]);
    setDash(d);
    setOut(o);
    setEvents(e);
    setRooms(r);
  }, [schoolId]);

  useEffect(() => {
    load().catch(() => undefined);
    const t = setInterval(() => load().catch(() => undefined), 30000); // keep "minutes out" fresh
    return () => clearInterval(t);
  }, [load]);

  const live = useLiveFeed(schoolId, (m) => {
    if (m.type === "lockdown") reloadSchool();
    load().catch(() => undefined);
  }, () => load().catch(() => undefined));

  if (!dash) return <Spinner />;
  const myRoom = rooms.find((r) => r.assigned_teacher_id === user?.id);
  const tz = school?.timezone;

  return (
    <>
      <PageHeader
        title="Today at a glance"
        subtitle={
          <span className="inline-flex items-center gap-1.5">
            <Radio className={`h-3.5 w-3.5 ${live ? "text-emerald-500" : "text-amber-500"}`} />
            {live ? "Live updates connected" : "Reconnecting — polling every 5 s"}
          </span>
        }
        actions={myRoom && <Link className="btn-primary" to={`/classrooms/${myRoom.id}`}>My classroom: Room {myRoom.room_number}</Link>}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Out right now" value={dash.currently_out} tone={dash.currently_out ? "amber" : "slate"} icon={<DoorOpen className="h-4 w-4" />} />
        <Stat label="Overdue" value={dash.overdue} tone={dash.overdue ? "red" : "slate"} />
        <Stat label="Sign-outs today" value={dash.sign_outs_today} icon={<Activity className="h-4 w-4" />} />
        <Stat label="Open flags" value={dash.open_flags} tone={dash.open_flags ? "red" : "slate"} icon={<Flag className="h-4 w-4" />} />
        <Stat label="Kiosks online" value={`${dash.kiosks_online}/${dash.kiosks_total}`} tone={dash.kiosks_online < dash.kiosks_total ? "amber" : "green"} icon={<Tablet className="h-4 w-4" />} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-5">
        <section className="card xl:col-span-2">
          <h2 className="border-b border-slate-100 px-4 py-3 font-bold text-slate-900">Currently out of class</h2>
          <OutNowList items={out} tz={tz} />
        </section>
        <section className="card xl:col-span-3">
          <h2 className="border-b border-slate-100 px-4 py-3 font-bold text-slate-900">Latest sign-ins &amp; sign-outs</h2>
          <EventFeed events={events} tz={tz} />
        </section>
      </div>

      <section className="mt-6">
        <h2 className="mb-3 font-bold text-slate-900">Classrooms</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {rooms.map((r) => (
            <Link key={r.id} to={`/classrooms/${r.id}`} className="card p-3 hover:border-brand-500">
              <div className="flex items-center justify-between">
                <span className="text-lg font-bold text-slate-900">{r.room_number}</span>
                <span className={`h-2.5 w-2.5 rounded-full ${r.kiosk_online === null ? "bg-slate-300" : r.kiosk_online ? "bg-emerald-500" : "bg-red-500"}`} title={r.kiosk_online === null ? "No kiosk" : r.kiosk_online ? "Kiosk online" : "Kiosk offline"} />
              </div>
              <div className="truncate text-xs text-slate-500">{r.room_name ?? "—"}</div>
              <div className={`mt-2 text-xs font-semibold ${r.out_count ? "text-amber-600" : "text-slate-400"}`}>{r.out_count} out</div>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
