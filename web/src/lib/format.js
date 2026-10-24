export const money = (n, digits = 2) =>
  `$${Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

export const hrs = (minutes) => {
  const m = Math.max(0, Math.round(minutes || 0));
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return h ? `${h}h ${String(mm).padStart(2, "0")}m` : `${mm}m`;
};

export const clock = (seconds) => {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
};

export const fmtTime = (iso, tz, opts = {}) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", {
      timeZone: tz || undefined, month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      ...(opts.seconds ? { second: "2-digit" } : {}), ...(opts.zone ? { timeZoneName: "short" } : {}),
    });
  } catch {
    return new Date(iso).toLocaleString();
  }
};

export const fmtClock = (iso, tz) => {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: tz || undefined, hour: "numeric", minute: "2-digit" });
};

export const ago = (iso) => {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
};

// Client mirror of backend core.stop_billing for the live meter.
export function liveBilling(arrivedAt, departedAt, det = {}, nowMs = Date.now()) {
  if (!arrivedAt) return null;
  const a = new Date(arrivedAt).getTime();
  const end = departedAt ? new Date(departedAt).getTime() : nowMs;
  const dwellSec = Math.max(0, (end - a) / 1000);
  const freeSec = (Number(det.free_time_hours) || 0) * 3600;
  const rate = Number(det.hourly_rate) || 0;
  const inc = Number(det.billing_increment_minutes) || 15;
  const billableSec = Math.max(0, dwellSec - freeSec);
  const billedMin = Math.floor(billableSec / 60 / inc) * inc;
  let accrued = (billableSec / 3600) * rate; // continuous (taxi meter)
  let billed = (billedMin / 60) * rate; // what invoices use
  let capped = false;
  const cap = Number(det.cap_amount) || 0;
  if (cap && det.cap_scope !== "per_load") {
    const c = det.cap_scope === "per_day" ? cap * Math.max(1, Math.ceil(dwellSec / 86400)) : cap;
    if (accrued >= c) { accrued = c; capped = true; }
    if (billed > c) billed = c;
  }
  return {
    dwellSec, freeSec, billableSec, freeLeftSec: Math.max(0, freeSec - dwellSec), accrued, billed, billedMin, capped, rate, cap,
    freeExpiresAt: new Date(a + freeSec * 1000).toISOString(), pctFree: freeSec ? Math.min(1, dwellSec / freeSec) : 1,
  };
}

export const TIMEZONES = [
  "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles",
  "America/Anchorage", "Pacific/Honolulu", "America/Toronto", "America/Vancouver", "America/Mexico_City",
];
