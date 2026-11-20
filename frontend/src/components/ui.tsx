import { useEffect, type ReactNode } from "react";
import { Loader2, ShieldCheck, X } from "lucide-react";

export function Logo({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <path d="M32 4 8 13v17c0 15 10 26 24 30 14-4 24-15 24-30V13L32 4z" fill="#14213d" stroke="#38bdf8" strokeWidth="2" />
      <circle cx="29" cy="29" r="10" fill="none" stroke="#38bdf8" strokeWidth="4" />
      <path d="m36 36 9 9" stroke="#38bdf8" strokeWidth="5" strokeLinecap="round" />
    </svg>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <Loader2 className="h-4 w-4 animate-spin" /> {label ?? "Loading…"}
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center text-slate-500">
      {icon}
      <p className="font-semibold text-slate-700">{title}</p>
      {children && <div className="text-sm">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>;
}

export function Stat({ label, value, tone = "slate", icon }: { label: string; value: ReactNode; tone?: "slate" | "amber" | "red" | "green" | "blue"; icon?: ReactNode }) {
  const tones = {
    slate: "text-slate-900",
    amber: "text-amber-600",
    red: "text-red-600",
    green: "text-emerald-600",
    blue: "text-brand-600",
  };
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
        {icon}
      </div>
      <div className={`mt-2 text-3xl font-bold tabular-nums ${tones[tone]}`}>{value}</div>
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 sm:items-center" role="dialog" aria-modal>
      <div className={`card w-full ${wide ? "max-w-2xl" : "max-w-md"} p-0`}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-base font-bold text-slate-900">{title}</h2>
          <button className="btn-ghost p-1" onClick={onClose} aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function AccommodationBadge() {
  return (
    <span className="badge bg-emerald-50 text-emerald-700" title="An approved accommodation is on file">
      <ShieldCheck className="h-3.5 w-3.5" /> Approved Accommodation on File
    </span>
  );
}

export function EventBadge({ type }: { type: "SIGN_OUT" | "SIGN_IN" }) {
  return type === "SIGN_OUT" ? (
    <span className="badge bg-orange-100 text-orange-700">SIGNED OUT</span>
  ) : (
    <span className="badge bg-teal-100 text-teal-700">SIGNED IN</span>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
