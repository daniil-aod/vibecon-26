import storage from "@/src/utils/storage";
import { uploadForm } from "@/src/utils/upload";

const DEFAULT_API = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
const EXTRA_HOSTS = (process.env.EXPO_PUBLIC_EXTRA_API_HOSTS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);

export type Stop = {
  id: string; seq: number; type: string; facility_name: string; address?: string; appointment?: string;
  lat?: number | null; lng?: number | null; radius_m?: number | null;
  arrived_at?: string | null; departed_at?: string | null; bol_count: number;
  free_expires_at?: string | null; notice_sent_at?: string | null;
};
export type DriverPayload = {
  load_number: string; fleet_name: string; driver_name?: string | null;
  free_time_hours?: number; requires_signed_bol?: boolean; stops: Stop[]; event?: string | null;
};
export type Fix = { lat: number; lng: number; accuracy: number };

/** Only accept a backend origin (from the texted link) that we trust — location data is sensitive. */
export function resolveApi(raw?: string | null): string {
  if (!raw) return DEFAULT_API;
  const m = String(raw).trim().match(/^https:\/\/([a-z0-9.-]+)(:\d+)?\/?$/i);
  if (!m) return DEFAULT_API;
  const host = m[1].toLowerCase();
  const defaultHost = DEFAULT_API.replace(/^https?:\/\//, "").split("/")[0].toLowerCase();
  const ok = host === defaultHost || EXTRA_HOSTS.includes(host);
  return ok ? `https://${host}${m[2] || ""}` : DEFAULT_API;
}

/** Extract {token, api} from a texted link, a deep link or a raw token. */
export function parseLink(input: string): { token: string; api?: string } | null {
  const s = input.trim();
  const m = s.match(/(?:\/d\/|\/api\/open\/|dockclock:\/\/d\/)([A-Za-z0-9_-]{16,})/);
  if (m) {
    const origin = s.match(/^(https:\/\/[^/?#]+)/i)?.[1];
    const q = s.match(/[?&]api=([^&#]+)/)?.[1];
    return { token: m[1], api: origin || (q ? decodeURIComponent(q) : undefined) };
  }
  if (/^[A-Za-z0-9_-]{16,}$/.test(s)) return { token: s };
  return null;
}

export class ApiError extends Error {
  status: number;
  constructor(msg: string, status: number) { super(msg); this.status = status; }
}

async function request<T>(api: string, path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${api}/api${path}`, init);
  } catch {
    throw new ApiError("No connection — we'll keep trying", 0);
  }
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError((data && (data.detail as string)) || "Something went wrong", r.status);
  return data as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const driverApi = {
  get: (api: string, tok: string) => request<DriverPayload>(api, `/driver/${tok}`),
  ping: (api: string, tok: string, fix: Fix) => request<DriverPayload>(api, `/driver/${tok}/ping`, json(fix)),
  tap: (api: string, tok: string, stopId: string, action: "arrive" | "depart", fix: Fix) =>
    request<DriverPayload>(api, `/driver/${tok}/stops/${stopId}/tap/${action}`, json(fix)),
  async bol(api: string, tok: string, stopId: string, uri: string, mime: string) {
    const ext = mime.includes("png") ? "png" : mime.includes("heic") ? "heic" : "jpg";
    const r = await uploadForm(`${api}/api/driver/${tok}/stops/${stopId}/bol`, [{ field: "file", uri, filename: `bol.${ext}`, type: mime }]);
    const data = await r.json().catch(() => null);
    if (!r.ok) throw new ApiError((data && data.detail) || "Upload failed", r.status);
    return data as DriverPayload;
  },
};

const apiKey = (tok: string) => `dockclock.api.${tok}`;
export async function rememberApi(tok: string, api: string) { await storage.setItem(apiKey(tok), api); }
export async function recallApi(tok: string) { return resolveApi(await storage.getItem(apiKey(tok))); }

export const errMsg = (e: unknown, fallback = "Something went wrong") => (e instanceof Error && e.message) || fallback;
