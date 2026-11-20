import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Ban, Plus, Wifi, WifiOff } from "lucide-react";
import { Empty, Modal, PageHeader, Spinner } from "../components/ui";
import { api, type Classroom, type KioskDevice } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime } from "../lib/live";
import { PairForm } from "./PairPage";

export default function KiosksPage() {
  const { schoolId, school } = useAuth();
  const [devices, setDevices] = useState<KioskDevice[] | null>(null);
  const [rooms, setRooms] = useState<Classroom[]>([]);
  const [pairing, setPairing] = useState(false);

  const load = useCallback(async () => {
    if (!schoolId) return;
    const [d, r] = await Promise.all([
      api<KioskDevice[]>(`/api/v1/kiosks?school_id=${schoolId}`),
      api<Classroom[]>(`/api/v1/schools/${schoolId}/classrooms`),
    ]);
    setDevices(d);
    setRooms(r);
  }, [schoolId]);
  useEffect(() => {
    load().catch(() => undefined);
    const t = setInterval(() => load().catch(() => undefined), 20000);
    return () => clearInterval(t);
  }, [load]);

  const reassign = async (d: KioskDevice, classroom_id: string) => {
    await api(`/api/v1/kiosks/${d.id}`, { method: "PATCH", json: { classroom_id } });
    load();
  };
  const revoke = async (d: KioskDevice) => {
    if (!confirm(`Revoke kiosk ${d.device_uid}? It will stop working until re-paired.`)) return;
    await api(`/api/v1/kiosks/${d.id}/revoke`, { method: "POST" });
    load();
  };

  return (
    <>
      <PageHeader title="Classroom kiosks" subtitle="Enter the XXXX-XXXX code shown on a new kiosk to pair it to a room." actions={<button className="btn-primary" onClick={() => setPairing(true)}><Plus className="h-4 w-4" /> Pair a kiosk</button>} />
      <div className="card overflow-x-auto">
        {!devices ? <Spinner /> : devices.length === 0 ? <Empty title="No kiosks paired yet">Power on a kiosk, finish its setup wizard, then click "Pair a kiosk".</Empty> : (
          <table className="min-w-full divide-y divide-slate-100">
            <thead><tr><th className="th">Status</th><th className="th">Room</th><th className="th">Device</th><th className="th">Last seen</th><th className="th">Wi-Fi</th><th className="th">Offline queue</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-50">
              {devices.map((d) => (
                <tr key={d.id}>
                  <td className="td">
                    {d.pairing_status !== "paired" ? <span className="badge bg-slate-100 text-slate-500">{d.pairing_status}</span> : d.online ? <span className="badge bg-emerald-100 text-emerald-700"><Wifi className="h-3 w-3" /> online</span> : <span className="badge bg-red-100 text-red-700"><WifiOff className="h-3 w-3" /> offline</span>}
                  </td>
                  <td className="td">
                    {d.pairing_status === "paired" ? (
                      <select className="input py-1" value={d.classroom_id ?? ""} onChange={(e) => reassign(d, e.target.value)}>
                        {rooms.map((r) => <option key={r.id} value={r.id}>Room {r.room_number}</option>)}
                      </select>
                    ) : "—"}
                  </td>
                  <td className="td"><div className="font-mono text-xs">{d.device_uid}</div><div className="text-xs text-slate-400">fw {d.firmware_version ?? "?"} · {d.ip_address ?? "?"}</div></td>
                  <td className="td text-xs">{formatDateTime(d.last_seen_at, school?.timezone)}</td>
                  <td className="td text-xs">{d.wifi_rssi != null ? `${d.wifi_rssi} dBm` : "—"}</td>
                  <td className="td">{d.offline_queue_depth > 0 ? <span className="badge bg-amber-100 text-amber-800">{d.offline_queue_depth} pending</span> : "0"}</td>
                  <td className="td text-right">{d.pairing_status === "paired" && <button className="btn-ghost text-red-600" onClick={() => revoke(d)}><Ban className="h-4 w-4" /> Revoke</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">Tip: kiosks also show a QR code during pairing — scanning it with a phone opens <Link className="underline" to="/pair">the pairing page</Link> pre-filled.</p>
      <Modal open={pairing} onClose={() => setPairing(false)} title="Pair a kiosk">
        <PairForm onPaired={() => { setPairing(false); load(); }} />
      </Modal>
    </>
  );
}
