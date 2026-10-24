import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { MapPin, LogIn, LogOut, Camera, CheckCircle2, Navigation, Loader2, AlertTriangle, Satellite } from "lucide-react";
import { publicApi, errMsg } from "@/lib/api";
import { clock, fmtClock, hrs } from "@/lib/format";
import { FacilityMap } from "@/components/Maps";
import { useNow } from "@/components/DetentionMeter";
import { Logo } from "@/components/AppShell";

const dist = (a, b) => {
  const R = 6371000, r = Math.PI / 180;
  const dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
};

export default function Driver() {
  const { token } = useParams();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [pos, setPos] = useState(null);
  const [gpsErr, setGpsErr] = useState(null);
  const [busy, setBusy] = useState("");
  const lastSent = useRef({ t: 0, lat: null, lng: null });
  const fileRef = useRef();
  const now = useNow(1000);

  const load = useCallback(() => publicApi.get(`/driver/${token}`).then((r) => setD(r.data)).catch((e) => setErr(errMsg(e, "This link is not valid"))), [token]);
  useEffect(() => { load(); }, [load]);

  // GPS watch + throttled pings (every 20s or 25m moved)
  useEffect(() => {
    if (!navigator.geolocation) { setGpsErr("This phone's browser doesn't share location."); return; }
    const id = navigator.geolocation.watchPosition(
      (p) => { setGpsErr(null); setPos({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }); },
      (e) => setGpsErr(e.code === 1 ? "Location is blocked. Allow location for this page so the dock can stamp your time." : "Waiting for GPS signal…"),
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 30000 });
    return () => navigator.geolocation.clearWatch(id);
  }, []);
  useEffect(() => {
    if (!pos) return;
    const l = lastSent.current;
    const moved = l.lat == null ? Infinity : dist(l, pos);
    if (Date.now() - l.t < 20000 && moved < 25) return;
    lastSent.current = { t: Date.now(), lat: pos.lat, lng: pos.lng };
    publicApi.post(`/driver/${token}/ping`, pos).then(({ data }) => {
      setD(data);
      if (data.event === "arrived") toast.success("Arrival stamped by geofence. Free time is running.");
      if (data.event === "departed") toast.success("Departure stamped. Don't forget the BOL photo.");
    }).catch(() => {});
  }, [pos, token]);
  // keep screen awake
  useEffect(() => {
    let lock;
    const req = async () => { try { lock = await navigator.wakeLock?.request("screen"); } catch {} };
    req();
    const vis = () => document.visibilityState === "visible" && req();
    document.addEventListener("visibilitychange", vis);
    return () => { document.removeEventListener("visibilitychange", vis); lock?.release?.(); };
  }, []);

  const getFix = () => new Promise((res, rej) => {
    if (pos && pos.accuracy < 1000) return res(pos);
    if (!navigator.geolocation) return rej(new Error("Location unavailable"));
    navigator.geolocation.getCurrentPosition((p) => res({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
      () => rej(new Error("Turn on location so your tap is stamped with GPS")), { enableHighAccuracy: true, timeout: 15000 });
  });
  const tap = async (stop, action) => {
    setBusy(action);
    try {
      const fix = await getFix();
      const { data } = await publicApi.post(`/driver/${token}/stops/${stop.id}/tap/${action}`, fix);
      setD(data);
      toast.success(action === "arrive" ? "Arrival stamped with GPS" : "Departure stamped with GPS");
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); }
  };
  const uploadBol = async (stop, file) => {
    if (!file) return;
    setBusy("bol");
    try {
      const fd = new FormData(); fd.append("file", file);
      const { data } = await publicApi.post(`/driver/${token}/stops/${stop.id}/bol`, fd);
      setD(data); toast.success("BOL photo attached to the load");
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); if (fileRef.current) fileRef.current.value = ""; }
  };

  if (err) return <div className="grid min-h-screen place-items-center p-6 text-center"><div><AlertTriangle className="mx-auto h-10 w-10 text-amber-600" /><p className="mt-3 text-lg font-semibold">{err}</p><p className="text-sm text-muted-foreground">Ask your dispatcher to text you a new link.</p></div></div>;
  if (!d) return <div className="grid min-h-screen place-items-center"><Loader2 className="h-8 w-8 animate-spin" /></div>;

  const stops = [...d.stops].sort((a, b) => a.seq - b.seq);
  const cur = stops.find((s) => !s.departed_at);
  const lastDone = [...stops].reverse().find((s) => s.departed_at);
  const bolStop = cur?.arrived_at ? cur : lastDone || cur;
  const onSite = cur?.arrived_at && !cur?.departed_at;
  const dwell = onSite ? (now - new Date(cur.arrived_at).getTime()) / 1000 : 0;
  const freeLeft = onSite && cur.free_expires_at ? (new Date(cur.free_expires_at).getTime() - now) / 1000 : 0;
  const away = cur && pos && cur.lat != null ? Math.max(0, dist(pos, cur) - (cur.radius_m || 300)) : null;

  return (
    <div data-testid="driver-page" className="mx-auto min-h-screen max-w-md bg-white pb-10">
      <header className="flex items-center justify-between border-b px-4 py-3"><Logo /><span className="font-mono text-sm font-semibold">{d.load_number}</span></header>
      <div className="px-4 pt-4">
        <p className="text-base">Hi {d.driver_name || "driver"} · <span className="text-muted-foreground">{d.fleet_name}</span></p>
        <div data-testid="driver-gps-status" className={`mt-3 flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${gpsErr ? "bg-amber-50 text-amber-900" : "bg-emerald-50 text-emerald-900"}`}>
          <Satellite className="h-4 w-4" />{gpsErr || (pos ? `GPS on · ±${Math.round(pos.accuracy)} m · keep this page open at the dock` : "Finding your location…")}
        </div>
      </div>

      {cur ? (
        <section className="px-4 pt-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{onSite ? "At the dock" : "Heading to"} · {cur.type}</div>
          <h1 data-testid="driver-facility-name" className="mt-1 font-display text-2xl font-semibold leading-tight">{cur.facility_name}</h1>
          <p className="mt-1 flex items-start gap-1 text-base text-slate-700"><MapPin className="mt-1 h-4 w-4 shrink-0" />{cur.address}</p>
          {onSite ? (
            <div data-testid="driver-on-site-timer" className="mt-4 rounded-2xl bg-slate-950 p-5 text-white">
              <div className="text-sm text-slate-400">On site since {fmtClock(cur.arrived_at)}</div>
              <div className="num mt-1 font-mono text-5xl font-semibold">{clock(dwell)}</div>
              <div className={`mt-2 text-base font-medium ${freeLeft > 0 ? "text-amber-300" : "text-emerald-300"}`}>{freeLeft > 0 ? `Free time left ${clock(freeLeft)}` : "Detention is running — broker notified"}</div>
            </div>
          ) : away !== null && (
            <div className="mt-3 flex items-center gap-2 text-base text-slate-700"><Navigation className="h-4 w-4" />{away < 50 ? "You're at the gate" : `${(away / 1609).toFixed(1)} mi from the geofence`}</div>
          )}
          <div className="mt-4"><FacilityMap testid="driver-map" stops={[cur]} truck={pos} height={200} /></div>
          <div className="mt-5 space-y-3">
            {!cur.arrived_at && <button data-testid="driver-arrived-button" disabled={!!busy} onClick={() => tap(cur, "arrive")}
              className="flex min-h-16 w-full items-center justify-center gap-3 rounded-2xl bg-slate-950 text-xl font-semibold text-white active:scale-[0.98] disabled:opacity-60">
              {busy === "arrive" ? <Loader2 className="h-6 w-6 animate-spin" /> : <LogIn className="h-6 w-6" />}I'm at the dock</button>}
            {onSite && <button data-testid="driver-departed-button" disabled={!!busy} onClick={() => tap(cur, "depart")}
              className="flex min-h-16 w-full items-center justify-center gap-3 rounded-2xl bg-emerald-700 text-xl font-semibold text-white active:scale-[0.98] disabled:opacity-60">
              {busy === "depart" ? <Loader2 className="h-6 w-6 animate-spin" /> : <LogOut className="h-6 w-6" />}I'm leaving</button>}
            {!cur.arrived_at && <p className="text-center text-sm text-muted-foreground">Arrival is stamped automatically when you enter the facility. Tap only if it doesn't.</p>}
          </div>
        </section>
      ) : (
        <section className="px-4 pt-6 text-center"><CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" /><h1 className="mt-3 font-display text-2xl font-semibold">All stops done</h1><p className="text-base text-muted-foreground">Thanks! Your times are saved.</p></section>
      )}

      {bolStop && (bolStop.arrived_at) && (
        <section className="px-4 pt-5">
          <input ref={fileRef} data-testid="driver-bol-file-input" type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => uploadBol(bolStop, e.target.files?.[0])} />
          <button data-testid="driver-upload-bol-button" disabled={busy === "bol"} onClick={() => fileRef.current?.click()}
            className={`flex min-h-16 w-full items-center justify-center gap-3 rounded-2xl border-2 text-lg font-semibold active:scale-[0.98] ${bolStop.bol_count ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-900 bg-white text-slate-900"}`}>
            {busy === "bol" ? <Loader2 className="h-6 w-6 animate-spin" /> : bolStop.bol_count ? <CheckCircle2 className="h-6 w-6" /> : <Camera className="h-6 w-6" />}
            {bolStop.bol_count ? `BOL attached (${bolStop.bol_count}) · add another` : "Photo of signed BOL"}
          </button>
          <p className="mt-2 text-center text-sm text-muted-foreground">For {bolStop.facility_name}. Make sure the in and out times are readable.</p>
        </section>
      )}

      <section className="px-4 pt-6">
        <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">All stops</div>
        <ol className="mt-2 space-y-2">
          {stops.map((s, i) => (
            <li key={s.id} data-testid={`driver-stop-${i}`} className="flex items-center gap-3 rounded-xl border p-3">
              <span className={`grid h-8 w-8 place-items-center rounded-full font-mono text-sm font-semibold ${s.departed_at ? "bg-emerald-600 text-white" : s.arrived_at ? "bg-sky-600 text-white" : "bg-slate-100"}`}>{i + 1}</span>
              <div className="min-w-0 flex-1"><div className="truncate text-base font-medium">{s.facility_name}</div>
                <div className="text-sm text-muted-foreground">{s.departed_at ? `In ${fmtClock(s.arrived_at)} · Out ${fmtClock(s.departed_at)} · ${hrs((new Date(s.departed_at) - new Date(s.arrived_at)) / 60000)}` : s.arrived_at ? `In ${fmtClock(s.arrived_at)}` : s.type}</div></div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
