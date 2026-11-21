import { useState, type FormEvent } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  BarChart3,
  CreditCard,
  DoorOpen,
  Flag,
  LayoutDashboard,
  LogOut,
  Menu,
  ScrollText,
  Search,
  Settings,
  ShieldAlert,
  Tablet,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { useAuth, isAdminRole } from "../lib/auth";
import { Logo } from "./ui";

export default function Layout() {
  const { user, school, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const admin = isAdminRole(user);

  const platformLinks: { to: string; label: string; icon: typeof BarChart3; end?: boolean }[] = [
    { to: "/admin", label: "Platform Overview", icon: BarChart3, end: true },
  ];
  const schoolLinks = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/lockdown", label: "Emergency Locator", icon: ShieldAlert },
    { to: "/classrooms", label: "Classrooms", icon: DoorOpen },
    { to: "/students", label: "Students", icon: Users },
    { to: "/flags", label: "Flags", icon: Flag },
    ...(admin
      ? [
          { to: "/kiosks", label: "Kiosks", icon: Tablet },
          { to: "/users", label: "Staff", icon: UserCog },
          { to: "/settings", label: "School Settings", icon: Settings },
          { to: "/billing", label: "Billing", icon: CreditCard },
          { to: "/audit", label: "Audit Log", icon: ScrollText },
        ]
      : []),
  ];
  const links = user?.role === "SUPERSUDO" ? platformLinks : schoolLinks;

  const search = (e: FormEvent) => {
    e.preventDefault();
    if (q.trim().length >= 2) nav(`/lockdown?q=${encodeURIComponent(q.trim())}`);
  };

  const billingBanner =
    admin && school && ["past_due", "unpaid", "canceled", "none", "incomplete"].includes(school.subscription_status);

  return (
    <div className="flex min-h-screen">
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 transform bg-navy-900 text-slate-200 transition lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-3 px-5 py-5">
          <Logo />
          <div className="leading-tight">
            <div className="text-sm font-extrabold tracking-wide text-white">DE-TECH-TIVE</div>
            <div className="text-[11px] text-slate-400">TECHNOLOGIES Inc</div>
          </div>
          <button className="ml-auto lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>
        <nav className="space-y-0.5 px-3">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${
                  isActive ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"
                } ${l.to === "/lockdown" ? "text-red-300" : ""}`
              }
            >
              <l.icon className="h-4 w-4" /> {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-white/10 p-4 text-xs">
          <NavLink to="/account" className="block truncate font-semibold text-white hover:underline">
            {user?.full_name}
          </NavLink>
          <div className="truncate text-slate-400">{user?.role.replace("_", " ")}</div>
          <button className="mt-3 flex items-center gap-2 text-slate-300 hover:text-white" onClick={logout}>
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
          {school?.lockdown_active && (
            <NavLink to="/lockdown" className="flex items-center justify-center gap-2 bg-red-600 px-4 py-2 text-sm font-bold text-white">
              <AlertTriangle className="h-4 w-4 animate-pulse" /> LOCKDOWN ACTIVE — open the roll-call
            </NavLink>
          )}
          {billingBanner && (
            <NavLink to="/billing" className="block bg-amber-100 px-4 py-1.5 text-center text-xs font-semibold text-amber-900">
              Subscription {school?.subscription_status.replace("_", " ")} — kiosks and emergency tools keep working. Update billing →
            </NavLink>
          )}
          <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
            <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
              <Menu className="h-6 w-6 text-slate-700" />
            </button>
            <div className="hidden min-w-0 sm:block">
              <div className="truncate text-sm font-bold text-slate-900">{school?.name ?? "No school selected"}</div>
              <div className="text-xs text-slate-500">{school?.timezone}</div>
            </div>
            <form onSubmit={search} className="ml-auto flex w-full max-w-md items-center gap-2 rounded-lg border-2 border-red-200 bg-red-50 px-3 py-1.5 focus-within:border-red-500">
              <Search className="h-4 w-4 shrink-0 text-red-600" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Emergency lookup: where is this student?"
                className="w-full bg-transparent text-sm text-slate-900 placeholder:text-red-400 focus:outline-none"
                aria-label="Emergency student lookup"
              />
            </form>
          </div>
        </header>
        <main className="flex-1 px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
