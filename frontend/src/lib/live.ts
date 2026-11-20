import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "./api";

export interface LiveMessage {
  type: "event" | "flag" | "lockdown" | "hello";
  [k: string]: unknown;
}

/**
 * Subscribes to the school's WebSocket feed. Calls `onMessage` for each push, and falls back to calling
 * `onPoll` every `pollMs` whenever the socket is down, so the views stay current even through proxies
 * that block WebSockets.
 */
export function useLiveFeed(schoolId: string | null, onMessage: (m: LiveMessage) => void, onPoll: () => void, pollMs = 5000) {
  const [connected, setConnected] = useState(false);
  const msgRef = useRef(onMessage);
  const pollRef = useRef(onPoll);
  msgRef.current = onMessage;
  pollRef.current = onPoll;

  useEffect(() => {
    if (!schoolId) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;
    let attempt = 0;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/v1/ws/schools/${schoolId}`);
      ws.onopen = () => {
        ws?.send(JSON.stringify({ token: getAccessToken() }));
      };
      ws.onmessage = (ev) => {
        if (ev.data === "pong") return;
        try {
          const m = JSON.parse(ev.data) as LiveMessage;
          if (m.type === "hello") {
            attempt = 0;
            setConnected(true);
            pollRef.current();
          } else msgRef.current(m);
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempt++));
      };
      ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(ping);
      ws?.close();
    };
  }, [schoolId]);

  useEffect(() => {
    if (connected || !schoolId) return;
    const t = setInterval(() => pollRef.current(), pollMs);
    return () => clearInterval(t);
  }, [connected, schoolId, pollMs]);

  return connected;
}

export function formatTime(iso: string | null | undefined, tz?: string) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZone: tz,
  }).format(new Date(iso));
}

export function formatDateTime(iso: string | null | undefined, tz?: string) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: tz,
  }).format(new Date(iso));
}

export function formatUtc(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toISOString().substring(11, 19) + " UTC";
}

export function minutesSince(iso: string) {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
}
