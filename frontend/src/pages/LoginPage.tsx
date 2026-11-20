import { useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { KeyRound, Loader2 } from "lucide-react";
import { ErrorNote, Logo } from "../components/ui";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function LoginPage() {
  const { user, login, verifyMfa } = useAuth();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const next = params.get("next");
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  if (user) return <Navigate to={user.role === "SUPERSUDO" && safeNext === "/" ? "/admin" : safeNext} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mfaToken) await verifyMfa(mfaToken, code);
      else {
        const r = await login(email, password);
        if (r.mfa_required && r.mfa_token) setMfaToken(r.mfa_token);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to reach the server");
      if (err instanceof ApiError && mfaToken && err.message.includes("expired")) setMfaToken(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-navy-900 via-navy-800 to-brand-900 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center text-white">
          <Logo className="h-16 w-16" />
          <h1 className="mt-3 text-xl font-extrabold tracking-wide">DE-TECH-TIVE TECHNOLOGIES Inc</h1>
          <p className="text-sm text-slate-300">Classroom Safety &amp; Accountability Systems</p>
        </div>
        <form onSubmit={submit} className="card space-y-4 p-6">
          {!mfaToken ? (
            <>
              <div>
                <label className="label" htmlFor="email">Email</label>
                <input id="email" className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div>
                <label className="label" htmlFor="pw">Password</label>
                <input id="pw" className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </>
          ) : (
            <div>
              <div className="mb-3 flex items-center gap-2 text-sm text-slate-600">
                <KeyRound className="h-4 w-4" /> Enter the 6-digit code from your authenticator app.
              </div>
              <input className="input text-center text-2xl tracking-[0.5em]" inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            </div>
          )}
          <ErrorNote error={error} />
          <button className="btn-primary w-full py-2.5" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />} {mfaToken ? "Verify" : "Sign in"}
          </button>
        </form>
        <p className="mt-4 text-center text-xs text-slate-400">Authorized school staff only. All access is logged.</p>
      </div>
    </div>
  );
}
