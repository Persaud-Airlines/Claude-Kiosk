import { Link } from "react-router-dom";
import { ArrowRightLeft, Clock, CloudOff, DoorOpen } from "lucide-react";
import type { HallEvent, OutNow } from "../lib/api";
import { formatTime, formatUtc } from "../lib/live";
import { AccommodationBadge, Empty, EventBadge } from "./ui";

export function OutNowList({ items, tz, showRoom = true }: { items: OutNow[]; tz?: string; showRoom?: boolean }) {
  if (!items.length) return <Empty icon={<DoorOpen className="h-8 w-8 text-slate-300" />} title="Everyone is in class" />;
  return (
    <ul className="divide-y divide-slate-100">
      {items.map((o) => (
        <li key={o.event_id} className="flex flex-wrap items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <Link to={`/students/${o.student_id}`} className="font-semibold text-slate-900 hover:underline">
              {o.first_name} {o.last_name}
            </Link>
            <div className="text-xs text-slate-500">
              → {o.destination ?? "—"}
              {showRoom && o.room_number && <> · from Room {o.room_number}</>} · out since {formatTime(o.signed_out_at_utc, tz)}
            </div>
            {o.has_accommodation && <div className="mt-1"><AccommodationBadge /></div>}
          </div>
          <span className={`badge ${o.overdue ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-800"}`}>
            <Clock className="h-3.5 w-3.5" /> {o.minutes_out} min
          </span>
        </li>
      ))}
    </ul>
  );
}

export function EventFeed({ events, tz, showRoom = true }: { events: HallEvent[]; tz?: string; showRoom?: boolean }) {
  if (!events.length) return <Empty title="No activity yet today" />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-100">
        <thead>
          <tr>
            <th className="th">Time (local / UTC)</th>
            <th className="th">Student</th>
            <th className="th">Action</th>
            {showRoom && <th className="th">Room</th>}
            <th className="th">Destination</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {events.map((e) => (
            <tr key={e.id} className={e.is_lockdown_cross_room ? "bg-amber-50" : undefined}>
              <td className="td whitespace-nowrap">
                <div className="font-medium tabular-nums">{formatTime(e.occurred_at_utc, tz)}</div>
                <div className="text-xs text-slate-400 tabular-nums">{formatUtc(e.occurred_at_utc)}</div>
              </td>
              <td className="td">
                <Link to={`/students/${e.student_id}`} className="font-semibold text-slate-900 hover:underline">
                  {e.student_name ?? `${e.scanned_first_name} ${e.scanned_last_name}`}
                </Link>
                <div className="flex flex-wrap gap-1">
                  {e.was_offline_queued && (
                    <span className="badge bg-slate-100 text-slate-600" title="Recorded while the kiosk was offline">
                      <CloudOff className="h-3 w-3" /> offline
                    </span>
                  )}
                  {e.entry_method !== "CARD_OCR" && <span className="badge bg-slate-100 text-slate-600">{e.entry_method.toLowerCase()}</span>}
                </div>
              </td>
              <td className="td">
                <EventBadge type={e.event_type} />
                {e.is_lockdown_cross_room && (
                  <div className="mt-1 badge bg-amber-200 text-amber-900" title="Signed into a room other than their homeroom / origin room">
                    <ArrowRightLeft className="h-3 w-3" /> cross-room
                  </div>
                )}
              </td>
              {showRoom && <td className="td">{e.room_number ?? "—"}</td>}
              <td className="td">{e.destination ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
