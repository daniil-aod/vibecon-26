import { Platform } from "react-native";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { activateKeepAwakeAsync, deactivateKeepAwake } from "expo-keep-awake";
import storage from "@/src/utils/storage";
import { colors } from "@/src/theme";
import { ApiError, driverApi, DriverPayload, Fix } from "./api";
import { dist } from "./format";
import { t } from "./i18n";

export const LOCATION_TASK = "dockclock-driver-location";
const TRIP_KEY = "dockclock.trip";
const PING_EVERY_MS = 20000; // same throttle as the web driver page: every 20s or 25m moved
const PING_MOVE_M = 25;

export type Trip = { token: string; api: string; startedAt: string; mode: TrackingMode };
export type TrackingMode = "background" | "foreground";

type Events = { fix: Fix; payload: DriverPayload; stopped: { reason: string }; queue: number };
type Listener<K extends keyof Events> = (v: Events[K]) => void;
const listeners: { [K in keyof Events]: Set<Listener<K>> } = { fix: new Set(), payload: new Set(), stopped: new Set(), queue: new Set() };
export function on<K extends keyof Events>(k: K, fn: Listener<K>) {
  listeners[k].add(fn);
  return () => { listeners[k].delete(fn); };
}
function emit<K extends keyof Events>(k: K, v: Events[K]) { listeners[k].forEach((fn) => fn(v)); }

let trip: Trip | null = null;
let last = { t: 0, lat: null as number | null, lng: null as number | null };
let inFlight = false;
let fgSub: Location.LocationSubscription | null = null;

export async function getTrip(): Promise<Trip | null> {
  if (trip) return trip;
  trip = await storage.getJSON<Trip>(TRIP_KEY);
  return trip;
}

const allDone = (p: DriverPayload) => p.stops.length > 0 && p.stops.every((s) => !!s.departed_at);
/** Transport is finished once every stop has a recorded departure (the server is the source of truth).
 *  Missing paperwork never keeps GPS running: the BOL/POD photo can still be added after tracking stops. */
export const tripComplete = (p: DriverPayload) => !!p.transport_completed || allDone(p);
const PENDING_KEY = "dockclock.pendingFlush";

// ---- Offline backup: GPS points taken without signal are saved on the phone (with their real time)
// and sent in order once coverage returns, so no evidence is lost.
const QUEUE_KEY = "dockclock.queue";
const QUEUE_MAX = 5000;
let queue: Fix[] | null = null;
async function loadQueue() { if (!queue) queue = (await storage.getJSON<Fix[]>(QUEUE_KEY)) || []; return queue; }
async function saveQueue() { await storage.setJSON(QUEUE_KEY, queue || []); emit("queue", (queue || []).length); }
export async function queuedCount() { return (await loadQueue()).length; }

/** Sends saved points oldest-first. Returns false if still offline. */
async function flush(t: Trip): Promise<boolean> {
  const q = await loadQueue();
  while (q.length) {
    try {
      const data = await driverApi.ping(t.api, t.token, q[0]);
      q.shift();
      emit("payload", data);
      if (tripComplete(data) && !q.length && trip) { await saveQueue(); await stopTracking("completed"); return true; }

    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 404 && e.status !== 408 && e.status !== 429) { q.shift(); continue; }
      await saveQueue();
      if (e instanceof ApiError && e.status === 404) await stopTracking("invalid");
      return false;
    }
  }
  await saveQueue();
  return true;
}

export async function flushQueue() {
  const t = (await getTrip()) || (await storage.getJSON<Trip>(PENDING_KEY));
  if (!t || inFlight) return;
  inFlight = true;
  try {
    const ok = await flush(t);
    if (ok && !(await getTrip())) { await storage.removeItem(PENDING_KEY); await storage.removeItem(QUEUE_KEY); }
  } finally { inFlight = false; }
}

// ---- Zone crossing detection (same rules as the backend's zone_state in server.py) so a boundary
// crossing is always sent right away, never skipped by the 20 s / 25 m throttle.
const ACC_SLACK_M = 25, EXIT_BUFFER_M = 10, MAX_FIX_ACC_M = 100;
type ZoneState = "inside" | "outside" | null;
export function zoneState(distM: number, acc: number, radius: number): ZoneState {
  if (acc > MAX_FIX_ACC_M) return null;
  const d = distM - Math.min(acc, ACC_SLACK_M);
  if (d <= radius) return "inside";
  if (d > radius + EXIT_BUFFER_M) return "outside";
  return null;
}
let zone: { stopId: string; lat: number; lng: number; radius: number; state: ZoneState } | null = null;
/** Remember the stop whose zone we're watching (current stop from the latest payload). */
export function watchZone(p: DriverPayload) {
  const cur = [...p.stops].sort((a, b) => a.seq - b.seq).find((s) => !s.departed_at);
  if (!cur || cur.lat == null || cur.lng == null) { zone = null; return; }
  const state: ZoneState = cur.arrived_at ? "inside" : "outside";
  if (!zone || zone.stopId !== cur.id) zone = { stopId: cur.id, lat: cur.lat, lng: cur.lng, radius: cur.radius_m || 45, state };
  else zone.state = state;
}
on("payload", watchZone);

async function handleFix(loc: Location.LocationObject) {
  const fix: Fix = { lat: loc.coords.latitude, lng: loc.coords.longitude, accuracy: loc.coords.accuracy ?? 50, ts: new Date(loc.timestamp || Date.now()).toISOString() };
  emit("fix", fix);
  const t = await getTrip();
  if (!t) return;
  const moved = last.lat == null ? Infinity : dist({ lat: last.lat, lng: last.lng as number }, fix);
  const zs = zone ? zoneState(dist(fix, zone), fix.accuracy, zone.radius) : null;
  const crossing = !!(zone && zs && zs !== zone.state);
  if (crossing && zone) zone.state = zs;
  if (!crossing && Date.now() - last.t < PING_EVERY_MS && moved < PING_MOVE_M) return;
  const q = await loadQueue();
  if (q.length && q[q.length - 1].ts === fix.ts) return; // same GPS point re-delivered (e.g. after resume)
  last = { t: Date.now(), lat: fix.lat, lng: fix.lng };
  q.push(fix);
  if (q.length > QUEUE_MAX) q.splice(0, q.length - QUEUE_MAX);
  if (inFlight) { await saveQueue(); return; } // a send is running; it will pick this point up
  inFlight = true;
  try {
    await flush(t);
  } finally {
    inFlight = false;
  }
}

// Must be defined at module scope so the OS can wake the app with location batches.
if (Platform.OS !== "web") {
  try {
    TaskManager.defineTask<{ locations: Location.LocationObject[] }>(LOCATION_TASK, async ({ data, error }) => {
      if (error || !data?.locations?.length) return;
      for (const l of data.locations) await handleFix(l); // every point, so no boundary crossing is missed
    });
  } catch {
    // Task manager unavailable (e.g. some Expo Go builds) — foreground mode is used instead.
  }
}

async function backgroundAllowed() {
  if (Platform.OS === "web") return false;
  try {
    const bg = await Location.getBackgroundPermissionsAsync();
    return bg.granted && (await TaskManager.isAvailableAsync());
  } catch { return false; }
}

async function startBackground() {
  await Location.startLocationUpdatesAsync(LOCATION_TASK, {
    accuracy: Location.Accuracy.BestForNavigation,
    timeInterval: 10000,
    distanceInterval: 0,
    activityType: Location.ActivityType.AutomotiveNavigation,
    pausesUpdatesAutomatically: false,
    showsBackgroundLocationIndicator: true,
    foregroundService: {
      notificationTitle: t("fgTitle"),
      notificationBody: t("fgBody"),
      notificationColor: colors.accent,
      killServiceOnDestroy: false,
    },
  });
}

async function startForeground() {
  fgSub?.remove();
  fgSub = await Location.watchPositionAsync(
    { accuracy: Location.Accuracy.BestForNavigation, timeInterval: 5000, distanceInterval: 0 },
    (loc) => { handleFix(loc); },
  );
  try { await activateKeepAwakeAsync("dockclock"); } catch {}
}

/** Starts GPS tracking for a load. Prefers OS-managed background updates; falls back to on-screen tracking. */
export async function startTracking(token: string, api: string): Promise<TrackingMode> {
  const prev = await getTrip();
  if (prev && prev.token !== token) { queue = []; await saveQueue(); } // never send one load's saved points to another
  let mode: TrackingMode = "foreground";
  if (await backgroundAllowed()) {
    try { await startBackground(); mode = "background"; } catch { mode = "foreground"; }
  }
  if (mode === "foreground") await startForeground();
  // Keep the ride's original start time when tracking is re-attached (app reopened).
  trip = { token, api, startedAt: prev?.token === token ? prev.startedAt : new Date().toISOString(), mode };
  await storage.removeItem(rideKey(token));
  last = { t: 0, lat: null, lng: null };
  await storage.setJSON(TRIP_KEY, trip);
  return mode;
}

/** Re-attaches tracking after the app is reopened. */
export async function resumeTracking(): Promise<TrackingMode | null> {
  const t = await getTrip();
  if (!t) return null;
  if (Platform.OS !== "web") {
    try {
      if (await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK)) return "background";
    } catch {}
  }
  return startTracking(t.token, t.api);
}

export type Ride = { startedAt: string; endedAt?: string };
const rideKey = (tok: string) => `dockclock.ride.${tok}`;
/** The ride for this load: running (from the active trip) or the last ended one. */
export async function getRide(tok: string): Promise<Ride | null> {
  const t = await getTrip();
  if (t?.token === tok) return { startedAt: t.startedAt };
  return storage.getJSON<Ride>(rideKey(tok));
}
export async function clearRide(tok: string) { await storage.removeItem(rideKey(tok)); }

export async function stopTracking(reason = "stopped") {
  const ending = trip || (await getTrip());
  if (ending && reason === "ended") await storage.setJSON(rideKey(ending.token), { startedAt: ending.startedAt, endedAt: new Date().toISOString() });
  fgSub?.remove();
  fgSub = null;
  try { await deactivateKeepAwake("dockclock"); } catch {}
  if (Platform.OS !== "web") {
    try {
      if (await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK)) await Location.stopLocationUpdatesAsync(LOCATION_TASK);
    } catch {}
  }
  // Preserve and flush evidence already collected offline before clearing it (never for an invalid/reset link).
  if (ending && reason !== "invalid" && reason !== "reset") {
    const q = await loadQueue();
    if (q.length) {
      let sent = false;
      try { sent = await flush(ending); } catch { sent = false; }
      if (!sent && (queue || []).length) {
        await storage.setJSON(PENDING_KEY, ending); // keep the saved points; flushQueue() sends them when signal returns
        trip = null;
        await storage.removeItem(TRIP_KEY);
        emit("stopped", { reason });
        return;
      }
    }
  }
  trip = null;
  queue = [];
  await storage.removeItem(QUEUE_KEY);
  await storage.removeItem(TRIP_KEY);
  await storage.removeItem(PENDING_KEY);
  emit("queue", 0);
  emit("stopped", { reason });
}
