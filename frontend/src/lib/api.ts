// Typed API client. Access token lives in memory only (never localStorage); the refresh token is an
// httpOnly, SameSite=Strict cookie scoped to /api/v1/auth, so XSS cannot exfiltrate long-lived credentials.

export type Role = "SUPERSUDO" | "PRINCIPAL" | "SCHOOL_ADMIN" | "TEACHER";
export type EventType = "SIGN_OUT" | "SIGN_IN";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  school_id: string | null;
  mfa_enabled: boolean;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface School {
  id: string;
  board_id: string | null;
  name: string;
  address: string | null;
  timezone: string;
  subscription_status: string;
  subscription_current_period_end: string | null;
  kiosk_destinations_json: string[];
  flag_threshold_count: number;
  flag_threshold_weekly_count: number;
  flag_duration_minutes: number;
  lockdown_active: boolean;
  lockdown_started_at: string | null;
  created_at: string;
}

export interface Classroom {
  id: string;
  school_id: string;
  room_number: string;
  room_name: string | null;
  assigned_teacher_id: string | null;
  out_count: number;
  kiosk_online: boolean | null;
}

export interface HallEvent {
  id: string;
  classroom_id: string;
  student_id: string;
  scanned_first_name: string;
  scanned_last_name: string;
  event_type: EventType;
  destination: string | null;
  entry_method: string;
  recorded_at_utc: string;
  occurred_at_utc: string;
  was_offline_queued: boolean;
  is_lockdown_cross_room: boolean;
  during_lockdown: boolean;
  notes: string | null;
  room_number: string | null;
  student_name: string | null;
}

export interface OutNow {
  event_id: string;
  student_id: string;
  first_name: string;
  last_name: string;
  destination: string | null;
  classroom_id: string;
  room_number: string | null;
  signed_out_at_utc: string;
  minutes_out: number;
  overdue: boolean;
  has_accommodation: boolean;
}

export interface Student {
  id: string;
  school_id: string;
  student_number: string | null;
  first_name: string;
  last_name: string;
  homeroom_classroom_id: string | null;
  grade: string | null;
  auto_registered: boolean;
  is_active: boolean;
  created_at: string;
  has_accommodation: boolean;
}

export interface LocateResult {
  student: Student;
  state: "IN_ROOM" | "OUT" | "NO_ACTIVITY";
  current_room_number: string | null;
  current_room_name: string | null;
  current_classroom_id: string | null;
  destination: string | null;
  last_event_type: EventType | null;
  last_event_at_utc: string | null;
  last_event_local: string | null;
  homeroom_number: string | null;
  is_cross_room: boolean;
  timeline: HallEvent[];
}

export interface Exemption {
  id: string;
  student_id: string;
  applies_to_destinations: string[];
  valid_from: string;
  valid_until: string | null;
  is_active: boolean;
  created_at: string;
  redacted: boolean;
  reason_category: string | null;
  reason_notes: string | null;
}

export interface Flag {
  id: string;
  student_id: string;
  student_name: string;
  flag_type: "EXCESSIVE_FREQUENCY" | "EXTENDED_DURATION" | "UNRETURNED_SESSION";
  trigger_details: string;
  is_suppressed_by_exemption: boolean;
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "SUPPRESSED_BY_EXEMPTION";
  reviewed_at: string | null;
  created_at: string;
}

export interface KioskDevice {
  id: string;
  device_uid: string;
  classroom_id: string | null;
  pairing_status: string;
  firmware_version: string | null;
  last_seen_at: string | null;
  ip_address: string | null;
  wifi_rssi: number | null;
  offline_queue_depth: number;
  paired_at: string | null;
  online: boolean;
  room_number: string | null;
}

export interface AuditEntry {
  id: string;
  actor_user_id: string | null;
  actor_device_id: string | null;
  action: string;
  target_resource: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string | null;
  expires_in: number;
  mfa_required: boolean;
  mfa_token: string | null;
  user: User | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onAuthLost: (() => void) | null = null;

export function setAccessToken(t: string | null) {
  accessToken = t;
}
export function getAccessToken() {
  return accessToken;
}
export function setOnAuthLost(fn: () => void) {
  onAuthLost = fn;
}

export async function tryRefresh(): Promise<TokenResponse | null> {
  const r = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" });
  if (!r.ok) return null;
  const body = (await r.json()) as TokenResponse;
  accessToken = body.access_token;
  return body;
}

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length) {
      const first = d[0] as { msg?: string; loc?: unknown[] };
      return `${first.msg ?? "Invalid input"}${first.loc ? ` (${first.loc.slice(1).join(".")})` : ""}`;
    }
  }
  return fallback;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const res = await fetch(path, { ...init, headers, body, credentials: "same-origin" });
  if (res.status === 401 && retry && !path.startsWith("/api/v1/auth/")) {
    refreshing ??= tryRefresh().then((r) => !!r).finally(() => (refreshing = null));
    if (await refreshing) return api<T>(path, init, false);
    onAuthLost?.();
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) throw new ApiError(res.status, detailMessage(data, res.statusText));
  return data as T;
}

export const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};
