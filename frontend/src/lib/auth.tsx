import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setAccessToken, setOnAuthLost, tryRefresh, type School, type TokenResponse, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  school: School | null;
  schoolId: string | null;
  setSchoolId: (id: string | null) => void;
  reloadSchool: () => Promise<void>;
  login: (email: string, password: string) => Promise<TokenResponse>;
  verifyMfa: (mfaToken: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);
const SUPER_SCHOOL_KEY = "dt.superSchool"; // only a non-sensitive UI preference is persisted

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [school, setSchool] = useState<School | null>(null);
  const [superSchoolId, setSuperSchoolId] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(SUPER_SCHOOL_KEY);
    } catch {
      return null;
    }
  });

  const schoolId = user?.role === "SUPERSUDO" ? superSchoolId : (user?.school_id ?? null);

  const setSchoolId = useCallback((id: string | null) => {
    setSuperSchoolId(id);
    try {
      if (id) sessionStorage.setItem(SUPER_SCHOOL_KEY, id);
      else sessionStorage.removeItem(SUPER_SCHOOL_KEY);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const reloadSchool = useCallback(async () => {
    if (!schoolId) {
      setSchool(null);
      return;
    }
    try {
      const q = user?.role === "SUPERSUDO" ? `?school_id=${schoolId}` : "";
      setSchool(await api<School>(`/api/v1/schools/current${q}`));
    } catch {
      setSchool(null);
    }
  }, [schoolId, user?.role]);

  useEffect(() => {
    setOnAuthLost(() => {
      setAccessToken(null);
      setUser(null);
    });
    tryRefresh()
      .then((r) => setUser(r?.user ?? null))
      .finally(() => setLoading(false));
    // Proactive refresh so long lockdown sessions never silently expire
    const t = setInterval(() => {
      tryRefresh().then((r) => r?.user && setUser(r.user));
    }, 20 * 60 * 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    reloadSchool();
  }, [reloadSchool]);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api<TokenResponse>("/api/v1/auth/login", { method: "POST", json: { email, password } });
    if (r.access_token && r.user) {
      setAccessToken(r.access_token);
      setUser(r.user);
    }
    return r;
  }, []);

  const verifyMfa = useCallback(async (mfaToken: string, code: string) => {
    const r = await api<TokenResponse>("/api/v1/auth/mfa/verify", { method: "POST", json: { mfa_token: mfaToken, code } });
    setAccessToken(r.access_token);
    setUser(r.user);
  }, []);

  const logout = useCallback(async () => {
    await api("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    setAccessToken(null);
    setUser(null);
    setSchool(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, school, schoolId, setSchoolId, reloadSchool, login, verifyMfa, logout }),
    [user, loading, school, schoolId, setSchoolId, reloadSchool, login, verifyMfa, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

export const isAdminRole = (u: User | null) => !!u && u.role !== "TEACHER";
