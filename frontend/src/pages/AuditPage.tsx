import { useCallback, useEffect, useState } from "react";
import { PageHeader, Spinner } from "../components/ui";
import { api, type AuditEntry, type User } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime } from "../lib/live";

const ACTIONS = ["", "LOGIN_SUCCESS", "LOGIN_FAILED", "VIEW_STUDENT_EXEMPTION", "CREATE_EXEMPTION", "LOCKDOWN_SEARCH", "LOCKDOWN_START", "LOCKDOWN_END", "PAIR_KIOSK", "REVOKE_KIOSK", "UPDATE_SUBSCRIPTION", "CREATE_USER", "UPDATE_USER", "IMPORT_ROSTER", "STAFF_EVENT", "KIOSK_PIN_FAILED"];

export default function AuditPage() {
  const { schoolId, school } = useAuth();
  const [action, setAction] = useState("");
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [users, setUsers] = useState<Record<string, string>>({});
  const load = useCallback(async () => {
    if (!schoolId) return;
    setRows(await api<AuditEntry[]>(`/api/v1/audit-logs?school_id=${schoolId}&limit=500${action ? `&action=${action}` : ""}`));
  }, [schoolId, action]);
  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);
  useEffect(() => {
    if (schoolId) api<User[]>(`/api/v1/users?school_id=${schoolId}`).then((u) => setUsers(Object.fromEntries(u.map((x) => [x.id, x.full_name])))).catch(() => undefined);
  }, [schoolId]);
  return (
    <>
      <PageHeader title="Security audit log" subtitle="Every sensitive read and change is recorded and cannot be edited." actions={<select className="input" value={action} onChange={(e) => setAction(e.target.value)}>{ACTIONS.map((a) => <option key={a} value={a}>{a || "All actions"}</option>)}</select>} />
      <div className="card overflow-x-auto">
        {!rows ? <Spinner /> : (
          <table className="min-w-full divide-y divide-slate-100">
            <thead><tr><th className="th">When</th><th className="th">Action</th><th className="th">Actor</th><th className="th">Target</th><th className="th">IP</th></tr></thead>
            <tbody className="divide-y divide-slate-50">
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="td whitespace-nowrap text-xs">{formatDateTime(r.created_at, school?.timezone)}</td>
                  <td className="td"><span className="badge bg-slate-100 font-mono text-slate-700">{r.action}</span></td>
                  <td className="td text-xs">{r.actor_user_id ? users[r.actor_user_id] ?? r.actor_user_id.slice(0, 8) : r.actor_device_id ? `kiosk ${r.actor_device_id.slice(0, 8)}` : "system"}</td>
                  <td className="td font-mono text-xs">{r.target_resource ?? "—"}</td>
                  <td className="td text-xs">{r.ip_address ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
