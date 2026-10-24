import { Platform } from "react-native";
import * as Location from "expo-location";

export type LocIssue = null | "services" | "blocked";

/** True when the OS gives us exact GPS (iOS "Precise Location" on, Android "fine"). */
export function isPrecise(p: Location.LocationPermissionResponse) {
  if (Platform.OS === "ios") return p.ios?.accuracy !== "reduced";
  if (Platform.OS === "android") return p.android?.accuracy !== "coarse";
  return true;
}

/**
 * Makes sure location is precise. On iOS this shows Apple's "temporary precise location" prompt
 * when the driver chose Approximate; on Android it re-asks so the driver can pick "Precise".
 */
export async function ensurePrecise(p: Location.LocationPermissionResponse): Promise<boolean> {
  if (isPrecise(p)) return true;
  try {
    if (Platform.OS === "ios") {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const next = require("expo-location/next");
      await next.Location.requestForegroundPermissions({ accuracy: next.RequestPermissionsAccuracyOption.FULL });
    } else if (Platform.OS === "android" && p.canAskAgain) {
      await Location.requestForegroundPermissionsAsync();
    }
  } catch {}
  return isPrecise(await Location.getForegroundPermissionsAsync());
}

/** Foreground permission flow: services → check → ask (only if allowed to ask). */
export async function ensureForeground(): Promise<{ issue: LocIssue; perm?: Location.LocationPermissionResponse }> {
  try {
    if (!(await Location.hasServicesEnabledAsync())) return { issue: "services" };
  } catch {}
  let fg = await Location.getForegroundPermissionsAsync();
  if (!fg.granted && fg.canAskAgain) fg = await Location.requestForegroundPermissionsAsync();
  if (!fg.granted) return { issue: "blocked", perm: fg };
  return { issue: null, perm: fg };
}

export async function backgroundState(): Promise<{ granted: boolean; canAsk: boolean }> {
  if (Platform.OS === "web") return { granted: false, canAsk: false };
  try {
    const bg = await Location.getBackgroundPermissionsAsync();
    return { granted: bg.granted, canAsk: bg.canAskAgain };
  } catch { return { granted: false, canAsk: false }; }
}

export async function requestBackground(): Promise<boolean> {
  try { return (await Location.requestBackgroundPermissionsAsync()).granted; } catch { return false; }
}
