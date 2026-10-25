import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, Circle, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import { Play, Pause, RotateCcw, Crosshair } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Switch } from "@/components/ui/switch";
import { Tooltip as UITooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { TILE, ATTR, FitBounds, truckIcon, pinIcon, geofenceStyle, trailStyle } from "@/components/Maps";
import { fmtTime, clock } from "@/lib/format";

const EV = {
  arrival: ["bg-sky-500", "Arrived"],
  free_time_expired: ["bg-amber-500", "Free time ended"],
  notice_sent: ["bg-teal-600", "Broker notice sent"],
  departure: ["bg-emerald-600", "Departed"],
  bol_uploaded: ["bg-slate-500", "BOL photo"],
};

function Follow({ pos, on }) {
  const map = useMap();
  useEffect(() => { if (on && pos) map.panTo(pos, { animate: false }); }, [on, pos, map]);
  return null;
}

export const TrailPlayback = ({ pings = [], stops = [], events = [], tz, height = 380, testid = "trail-playback" }) => {
  const pts = useMemo(() => pings.map((p) => ({ ...p, t: new Date(p.ts).getTime() })).sort((a, b) => a.t - b.t), [pings]);
  const evs = useMemo(() => events.filter((e) => e.at && EV[e.type]).map((e) => ({ ...e, t: new Date(e.at).getTime() })), [events]);
  const times = [...pts.map((p) => p.t), ...evs.map((e) => e.t)];
  const t0 = times.length ? Math.min(...times) : 0;
  const t1 = times.length ? Math.max(...times) : 0;
  const span = Math.max(1, t1 - t0);
  const [t, setT] = useState(t0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState("60");
  const [follow, setFollow] = useState(false);
  const raf = useRef();
  const last = useRef();

  useEffect(() => { setT(t0); }, [t0]);
  useEffect(() => {
    if (!playing) return;
    const step = (ts) => {
      if (last.current != null) {
        const dt = ts - last.current;
        setT((cur) => {
          const nx = cur + dt * Number(speed);
          if (nx >= t1) { setPlaying(false); return t1; }
          return nx;
        });
      }
      last.current = ts;
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf.current); last.current = null; };
  }, [playing, speed, t1]);

  const pos = useMemo(() => {
    if (!pts.length) return null;
    if (t <= pts[0].t) return [pts[0].lat, pts[0].lng];
    for (let i = 1; i < pts.length; i++) {
      if (pts[i].t >= t) {
        const a = pts[i - 1], b = pts[i];
        const f = (t - a.t) / Math.max(1, b.t - a.t);
        return [a.lat + (b.lat - a.lat) * f, a.lng + (b.lng - a.lng) * f];
      }
    }
    const l = pts[pts.length - 1];
    return [l.lat, l.lng];
  }, [pts, t]);
  const drawn = useMemo(() => {
    const d = pts.filter((p) => p.t <= t).map((p) => [p.lat, p.lng]);
    if (pos) d.push(pos);
    return d;
  }, [pts, t, pos]);
  const bounds = useMemo(() => [...stops.filter((s) => s.lat != null).map((s) => [s.lat, s.lng]), ...pts.map((p) => [p.lat, p.lng])], [stops, pts]);
  const firedEvents = evs.filter((e) => e.t <= t);
  const lastEvent = firedEvents[firedEvents.length - 1];

  if (!times.length) {
    return (
      <div data-testid={`${testid}-empty`} className="grid place-items-center rounded-xl border border-dashed bg-muted/40 p-10 text-center text-sm text-muted-foreground">
        No GPS trail yet. The trail records while the driver keeps the check-in link open.
      </div>
    );
  }

  return (
    <div data-testid={testid} className="overflow-hidden rounded-xl border bg-card">
      <div className="relative map-tiles-soft" style={{ height }}>
        <MapContainer center={bounds[0] || [39.5, -98.35]} zoom={14} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
          <TileLayer url={TILE} attribution={ATTR} />
          <FitBounds points={bounds} />
          <Follow pos={pos} on={follow} />
          {stops.filter((s) => s.lat != null).map((s) => (
            <Circle key={s.id} center={[s.lat, s.lng]} radius={s.radius_m || 45} pathOptions={geofenceStyle}>
              <Tooltip>{s.facility_name} · geofence {Math.round(s.radius_m || 45)} m</Tooltip>
            </Circle>
          ))}
          {stops.filter((s) => s.lat != null).map((s) => (
            <Marker key={`p${s.id}`} position={[s.lat, s.lng]} icon={pinIcon(s.type === "delivery" ? "D" : "P")} />
          ))}
          {pts.length > 1 && <Polyline positions={pts.map((p) => [p.lat, p.lng])} pathOptions={{ ...trailStyle, opacity: 0.18 }} />}
          {drawn.length > 1 && <Polyline positions={drawn} pathOptions={trailStyle} />}
          {pos && <Marker position={pos} icon={truckIcon("billable")} />}
        </MapContainer>
        <div className="absolute right-3 top-3 z-[400] rounded-lg border bg-white px-3 py-2 card-shadow">
          <div data-testid={`${testid}-timecode`} className="num font-mono text-sm font-semibold">{fmtTime(new Date(t).toISOString(), tz, { seconds: true })}</div>
          <div className="text-[11px] text-muted-foreground">{lastEvent ? EV[lastEvent.type][1] : "Start of trail"} · +{clock((t - t0) / 1000)}</div>
        </div>
      </div>
      <div className="border-t bg-slate-50 p-3 md:p-4">
        <div className="relative">
          <input data-testid={`${testid}-scrubber`} aria-label="Playback time" type="range" className="scrub-range"
            min={t0} max={t1} step={1000} value={t} onChange={(e) => { setPlaying(false); setT(Number(e.target.value)); }} />
          <TooltipProvider delayDuration={100}>
            <div className="pointer-events-none absolute inset-x-[7px] top-0 h-full">
              {evs.map((e, i) => (
                <UITooltip key={i}>
                  <TooltipTrigger asChild>
                    <button data-testid={`${testid}-event-${e.type}`} onClick={() => { setPlaying(false); setT(e.t); }}
                      className={`pointer-events-auto absolute top-[3px] h-5 w-1.5 -translate-x-1/2 rounded-full ring-2 ring-white ${EV[e.type][0]}`}
                      style={{ left: `${((e.t - t0) / span) * 100}%` }} aria-label={EV[e.type][1]} />
                  </TooltipTrigger>
                  <TooltipContent>{EV[e.type][1]} · {fmtTime(e.at, tz)}</TooltipContent>
                </UITooltip>
              ))}
            </div>
          </TooltipProvider>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Button data-testid={`${testid}-play-button`} size="sm" onClick={() => { if (t >= t1) setT(t0); setPlaying((p) => !p); }}>
            {playing ? <Pause className="mr-1.5 h-4 w-4" /> : <Play className="mr-1.5 h-4 w-4" />}{playing ? "Pause" : "Play"}
          </Button>
          <Button data-testid={`${testid}-restart-button`} size="sm" variant="outline" onClick={() => { setPlaying(false); setT(t0); }}>
            <RotateCcw className="h-4 w-4" />
          </Button>
          <ToggleGroup type="single" value={speed} onValueChange={(v) => v && setSpeed(v)} className="rounded-lg border bg-white p-0.5">
            {["1", "10", "60", "600"].map((s) => (
              <ToggleGroupItem key={s} value={s} data-testid={`playback-speed-${s}x-toggle`} className="h-7 px-2.5 font-mono text-xs">{s}x</ToggleGroupItem>
            ))}
          </ToggleGroup>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Switch data-testid={`${testid}-follow-switch`} checked={follow} onCheckedChange={setFollow} />
            <Crosshair className="h-3.5 w-3.5" /> Follow truck
          </label>
          <div className="ml-auto hidden flex-wrap gap-3 text-[11px] text-muted-foreground md:flex">
            {Object.entries(EV).filter(([k]) => k !== "bol_uploaded").map(([k, [c, l]]) => (
              <span key={k} className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${c}`} />{l}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
