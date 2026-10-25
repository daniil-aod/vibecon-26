import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Circle, Marker, Polyline, Tooltip, useMap, useMapEvents } from "react-leaflet";

export const TILE = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
export const ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

export const truckIcon = (kind = "") => L.divIcon({
  className: "", iconSize: [18, 18], iconAnchor: [9, 9],
  html: `<div class="truck-pin ${kind}"><div class="halo"></div><div class="core"></div></div>`,
});

export const pinIcon = (label = "", color = "#0f172a") => L.divIcon({
  className: "", iconSize: [26, 26], iconAnchor: [13, 13],
  html: `<div style="width:26px;height:26px;border-radius:9999px;background:${color};color:#fff;display:grid;place-items:center;font:600 11px 'IBM Plex Mono',monospace;border:2px solid #fff;box-shadow:0 2px 6px rgba(2,6,23,.35)">${label}</div>`,
});

export function FitBounds({ points, padding = 40, maxZoom = 16 }) {
  const map = useMap();
  const key = JSON.stringify(points);
  useEffect(() => {
    const pts = points.filter((p) => p && p[0] != null && p[1] != null);
    if (!pts.length) return;
    if (pts.length === 1) map.setView(pts[0], Math.min(maxZoom, 15));
    else map.fitBounds(pts, { padding: [padding, padding], maxZoom });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return null;
}

function ClickToMove({ onMove }) {
  useMapEvents({ click: (e) => onMove && onMove(e.latlng.lat, e.latlng.lng) });
  return null;
}

export const geofenceStyle = { color: "#F59E0B", weight: 2, opacity: 0.9, fillColor: "#F59E0B", fillOpacity: 0.12 };
export const trailStyle = { color: "#0F766E", weight: 4, opacity: 0.85 };

// Facility geofence map; editable lets the dispatcher click to move the pin.
export const FacilityMap = ({ stops = [], trail = [], truck, height = 260, editable = false, onMove, testid = "facility-map" }) => {
  const pts = useMemo(() => [...stops.map((s) => [s.lat, s.lng]), ...trail.map((p) => [p.lat, p.lng]), ...(truck ? [[truck.lat, truck.lng]] : [])], [stops, trail, truck]);
  const center = pts.find((p) => p[0] != null) || [39.5, -98.35];
  return (
    <div data-testid={testid} className="overflow-hidden rounded-xl border map-tiles-soft" style={{ height }}>
      <MapContainer center={center} zoom={pts.length ? 14 : 4} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer url={TILE} attribution={ATTR} />
        <FitBounds points={pts} />
        {editable && <ClickToMove onMove={onMove} />}
        {stops.filter((s) => s.lat != null).map((s, i) => (
          <Circle key={s.id || i} center={[s.lat, s.lng]} radius={s.radius_m || 45} pathOptions={geofenceStyle}>
            <Tooltip direction="top">{s.facility_name}</Tooltip>
          </Circle>
        ))}
        {stops.filter((s) => s.lat != null).map((s, i) => (
          <Marker key={`m${s.id || i}`} position={[s.lat, s.lng]} icon={pinIcon(s.type === "delivery" ? "D" : "P", s.type === "delivery" ? "#0f766e" : "#0f172a")} />
        ))}
        {trail.length > 1 && <Polyline positions={trail.map((p) => [p.lat, p.lng])} pathOptions={trailStyle} />}
        {truck && <Marker position={[truck.lat, truck.lng]} icon={truckIcon()} />}
      </MapContainer>
    </div>
  );
};

// Dashboard fleet map: geofences of known facilities + live truck pins.
export const FleetMap = ({ facilities = [], trucks = [], height = 420 }) => {
  const pts = [...trucks.map((t) => [t.lat, t.lng]), ...facilities.slice(0, 30).map((f) => [f.lat, f.lng])];
  return (
    <div data-testid="dashboard-fleet-map" className="relative overflow-hidden rounded-xl border map-tiles-soft" style={{ height }}>
      <MapContainer center={[39.5, -98.35]} zoom={4} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer url={TILE} attribution={ATTR} />
        <FitBounds points={pts} maxZoom={12} />
        {facilities.map((f) => (
          <Circle key={f.id} center={[f.lat, f.lng]} radius={f.radius_m || 45} pathOptions={geofenceStyle}>
            <Tooltip>{f.name}</Tooltip>
          </Circle>
        ))}
        {trucks.map((t) => (
          <Marker key={t.load_id} position={[t.lat, t.lng]} icon={truckIcon(t.status === "on_site" ? "billable" : "idle")}>
            <Tooltip direction="top">Load {t.load_number}{t.driver ? ` · ${t.driver}` : ""}</Tooltip>
          </Marker>
        ))}
      </MapContainer>
      <div className="pointer-events-none absolute bottom-3 left-3 z-[400] flex gap-3 rounded-lg border bg-white px-3 py-2 text-[11px] text-slate-700 card-shadow">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-emerald-600" />On site</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-sky-600" />Rolling</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full border-2 border-amber-500 bg-amber-100" />Geofence</span>
      </div>
    </div>
  );
};
