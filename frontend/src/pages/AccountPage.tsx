import { useState, type FormEvent } from "react";
import { QRCodeSVG } from "qrcode.react";
import { KeyRound, ShieldCheck } from "lucide-react";
import { ErrorNote, PageHeader } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function AccountPage() {
  const { user, logout } = useAuth();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [enroll, setEnroll] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [mfaOn, setMfaOn] = useState(user?.mfa_enabled ?? false);

  const changePw = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/v1/auth/change-password", { method: "POST", json: { current_password: cur, new_password: next } });
      setMsg("Password changed. Please sign in again.");
      setTimeout(logout, 1500);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };
  const startMfa = async () => {
    setError(null);
    try {
      setEnroll(await api("/api/v1/auth/mfa/enroll", { method: "POST" }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  };
  const confirmMfa = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api(mfaOn ? "/api/v1/auth/mfa/disable" : "/api/v1/auth/mfa/confirm", { method: "POST", json: { code } });
      if (mfaOn) {
        setMsg("Two-factor authentication disabled. Please sign in again.");
        setTimeout(logout, 1500);
      } else {
        setMfaOn(true);
        setEnroll(null);
        setMsg("Two-factor authentication is now on.");
      }
      setCode("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invalid code");
    }
  };

  return (
    <div className="max-w-xl space-y-6">
      <PageHeader title="My account" subtitle={`${user?.full_name} · ${user?.email}`} />
      <form onSubmit={changePw} className="card space-y-3 p-5">
        <h2 className="flex items-center gap-2 font-bold"><KeyRound className="h-4 w-4" /> Change password</h2>
        <input className="input" type="password" autoComplete="current-password" placeholder="Current password" required value={cur} onChange={(e) => setCur(e.target.value)} />
        <input className="input" type="password" autoComplete="new-password" placeholder="New password (12+ chars)" minLength={12} required value={next} onChange={(e) => setNext(e.target.value)} />
        <button className="btn-primary">Update password</button>
      </form>
      <div className="card space-y-3 p-5">
        <h2 className="flex items-center gap-2 font-bold"><ShieldCheck className="h-4 w-4" /> Two-factor authentication {mfaOn && <span className="badge bg-emerald-100 text-emerald-700">on</span>}</h2>
        {!mfaOn && !enroll && <button className="btn-secondary" onClick={startMfa}>Set up authenticator app</button>}
        {enroll && (
          <div className="flex flex-col items-center gap-3">
            <QRCodeSVG value={enroll.otpauth_uri} size={180} />
            <code className="break-all text-xs text-slate-500">{enroll.secret}</code>
          </div>
        )}
        {(enroll || mfaOn) && (
          <form onSubmit={confirmMfa} className="flex gap-2">
            <input className="input" inputMode="numeric" maxLength={6} placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            <button className={mfaOn ? "btn-danger" : "btn-primary"}>{mfaOn ? "Disable" : "Confirm"}</button>
          </form>
        )}
      </div>
      <ErrorNote error={error} />
      {msg && <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{msg}</div>}
    </div>
  );
}
