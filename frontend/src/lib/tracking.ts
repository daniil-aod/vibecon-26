import { Platform } from "react-native";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { activateKeepAwakeAsync, deactivateKeepAwake } from "expo-keep-awake";
import storage from "@/src/utils/storage";
import { colors } from "@/src/theme";
import { ApiError, driverApi, DriverPayload, Fix } from "./api";
import { dist } from "./format";

export const LOCATION_TASK = "dockclock-driver-location";
const TRIP_KEY = "dockclock.trip";
const PING_EVERY_MS = 20000; // same throttle as the web driver page: every 20s or 25m moved
const PING_MOVE_M = 25;

export type Trip = { token: string; api: string; startedAt: string; mode: TrackingMode };
export type TrackingMode = "background" | "foreground";

type Events = { fix: Fix; payload: DriverPayload; stopped: { reason: string } };
type Listener<K extends keyof Events> = (v: Events[K]) => void;
const listeners: { [K in keyof Events]: Set<Listener<K>> } = { fix: new Set(), payload: new Set(), stopped: new Set() };
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

async function handleFix(loc: Location.LocationObject) {
  const fix: Fix = { lat: loc.coords.latitude, lng: loc.coords.longitude, accuracy: loc.coords.accuracy ?? 50 };
  emit("fix", fix);
  const t = await getTrip();
  if (!t || inFlight) return;
  const moved = last.lat == null ? Infinity : dist({ lat: last.lat, lng: last.lng as number }, fix);
  if (Date.now() - last.t < PING_EVERY_MS && moved < PING_MOVE_M) return;
  inFlight = true;
  last = { t: Date.now(), lat: fix.lat, lng: fix.lng };
  try {
    const data = await driverApi.ping(t.api, t.token, fix);
    emit("payload", data);
    if (allDone(data)) await stopTracking("delivered");
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) await stopTracking("invalid");
    else last.t = 0; // retry on next fix when offline
  } finally {
    inFlight = false;
  }
}

// Must be defined at module scope so the OS can wake the app with location batches.
if (Platform.OS !== "web") {
  try {
    TaskManager.defineTask<{ locations: Location.LocationObject[] }>(LOCATION_TASK, async ({ data, error }) => {
      if (error || !data?.locations?.length) return;
      await handleFix(data.locations[data.locations.length - 1]);
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
      notificationTitle: "DockClock is tracking this load",
      notificationBody: "Your dock arrival and departure are stamped automatically.",
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
  let mode: TrackingMode = "foreground";
  if (await backgroundAllowed()) {
    try { await startBackground(); mode = "background"; } catch { mode = "foreground"; }
  }
  if (mode === "foreground") await startForeground();
  trip = { token, api, startedAt: new Date().toISOString(), mode };
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

export async function stopTracking(reason = "stopped") {
  fgSub?.remove();
  fgSub = null;
  try { await deactivateKeepAwake("dockclock"); } catch {}
  if (Platform.OS !== "web") {
    try {
      if (await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK)) await Location.stopLocationUpdatesAsync(LOCATION_TASK);
    } catch {}
  }
  trip = null;
  await storage.removeItem(TRIP_KEY);
  emit("stopped", { reason });
}
