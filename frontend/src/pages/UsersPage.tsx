import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Plus, ShieldCheck } from "lucide-react";
import { ErrorNote, Modal, PageHeader, Spinner } from "../components/ui";
import { api, ApiError, type Role, type User } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime } from "../lib/live";

const CREATABLE: Record<Role, Role[]> = {
  SUPERSUDO: ["PRINCIPAL", "SCHOOL_ADMIN", "TEACHER"],
  PRINCIPAL: ["PRINCIPAL", "SCHOOL_ADMIN", "TEACHER"],
  SCHOOL_ADMIN: ["TEACHER"],
  TEACHER: [],
};

export default function UsersPage() {
  const { schoolId, user, school } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [adding, setAdding] = useState(false);
  const load = useCallback(async () => {
    if (schoolId) setUsers(await api<User[]>(`/api/v1/users?school_id=${schoolId}`));
  }, [schoolId]);
  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);
  const toggleActive = async (u: User) => {
    try {
      await api(`/api/v1/users/${u.id}`, { method: "PATCH", json: { is_active: !u.is_active } });
      load();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed");
    }
  };
  if (!users || !user) return <Spinner />;
  return (
    <>
      <PageHeader title="Staff accounts" actions={CREATABLE[user.role].length > 0 && <button className="btn-primary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> Add staff</button>} />
      <div className="card overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-100">
          <thead><tr><th className="th">Name</th><th className="th">Email</th><th className="th">Role</th><th className="th">MFA</th><th className="th">Last login</th><th className="th" /></tr></thead>
          <tbody className="divide-y divide-slate-50">
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "opacity-50"}>
                <td className="td font-semibold">{u.full_name}</td>
                <td className="td">{u.email}</td>
                <td className="td"><span className="badge bg-slate-100 text-slate-700">{u.role.replace("_", " ")}</span></td>
                <td className="td">{u.mfa_enabled ? <ShieldCheck className="h-4 w-4 text-emerald-600" /> : <span className="text-xs text-slate-400">off</span>}</td>
                <td className="td text-xs">{formatDateTime(u.last_login_at, school?.timezone)}</td>
                <td className="td text-right">{u.id !== user.id && CREATABLE[user.role].includes(u.role) && <button className="btn-ghost text-xs" onClick={() => toggleActive(u)}>{u.is_active ? "Deactivate" : "Reactivate"}</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {adding && <AddUser roles={CREATABLE[user.role]} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); load(); }} />}
    </>
  );
}

function AddUser({ roles, onClose, onSaved }: { roles: Role[]; onClose: () => void; onSaved: () => void }) {
  const { schoolId } = useAuth();
  const [f, setF] = useState({ full_name: "", email: "", role: roles[roles.length - 1], password: "" });
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/v1/users", { method: "POST", json: { ...f, school_id: schoolId } });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };
  return (
    <Modal open onClose={onClose} title="Add staff account">
      <form onSubmit={submit} className="space-y-3">
        <div><label className="label">Full name</label><input className="input" required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
        <div><label className="label">Email</label><input className="input" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
        <div><label className="label">Role</label><select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>{roles.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}</select></div>
        <div><label className="label">Temporary password</label><input className="input" type="text" minLength={12} required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /><p className="mt-1 text-xs text-slate-500">12+ characters with 3 of: lowercase, uppercase, digit, symbol. Ask them to change it at first login.</p></div>
        <ErrorNote error={error} />
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary">Create</button></div>
      </form>
    </Modal>
  );
}
