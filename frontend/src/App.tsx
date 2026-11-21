import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { isAdminRole, useAuth } from "./lib/auth";
import AccountPage from "./pages/AccountPage";
import AuditPage from "./pages/AuditPage";
import BillingPage from "./pages/BillingPage";
import ClassroomPage from "./pages/ClassroomPage";
import ClassroomsPage from "./pages/ClassroomsPage";
import DashboardPage from "./pages/DashboardPage";
import FlagsPage from "./pages/FlagsPage";
import KiosksPage from "./pages/KiosksPage";
import LockdownPage from "./pages/LockdownPage";
import LoginPage from "./pages/LoginPage";
import PairPage from "./pages/PairPage";
import SettingsPage from "./pages/SettingsPage";
import StudentPage from "./pages/StudentPage";
import StudentsPage from "./pages/StudentsPage";
import UsersPage from "./pages/UsersPage";
import OverviewPage from "./pages/admin/OverviewPage";
import SchoolPage from "./pages/admin/SchoolPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Spinner label="Checking session…" />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  return <>{children}</>;
}

function RequireSchool({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  // The platform operator never opens school pages (students, sign-ins, staff, audit logs).
  if (user?.role === "SUPERSUDO") return <Navigate to="/admin" replace />;
  return <>{children}</>;
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (user?.role === "SUPERSUDO") return <Navigate to="/admin" replace />;
  return isAdminRole(user) ? <>{children}</> : <Navigate to="/" replace />;
}

export default function App() {
  const s = (el: ReactNode) => <RequireSchool>{el}</RequireSchool>;
  const a = (el: ReactNode) => (
    <AdminOnly>
      <RequireSchool>{el}</RequireSchool>
    </AdminOnly>
  );
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={s(<DashboardPage />)} />
        <Route path="admin" element={<OverviewPage />} />
        <Route path="admin/schools/:id" element={<SchoolPage />} />
        <Route path="lockdown" element={s(<LockdownPage />)} />
        <Route path="classrooms" element={s(<ClassroomsPage />)} />
        <Route path="classrooms/:id" element={s(<ClassroomPage />)} />
        <Route path="students" element={s(<StudentsPage />)} />
        <Route path="students/:id" element={s(<StudentPage />)} />
        <Route path="flags" element={s(<FlagsPage />)} />
        <Route path="kiosks" element={a(<KiosksPage />)} />
        <Route path="pair" element={a(<PairPage />)} />
        <Route path="users" element={a(<UsersPage />)} />
        <Route path="settings" element={a(<SettingsPage />)} />
        <Route path="billing" element={a(<BillingPage />)} />
        <Route path="audit" element={a(<AuditPage />)} />
        <Route path="account" element={<AccountPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
