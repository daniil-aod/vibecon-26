import { useEffect, useState } from "react";
import { liveBilling, money, clock, fmtClock } from "@/lib/format";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";

export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

// Taxi-meter for one stop on site.
export const DetentionMeter = ({ stop, detention, title, subtitle, tz, compact = false, notice, testid = "detention-meter" }) => {
  const now = useNow(1000);
  const b = liveBilling(stop.arrived_at, stop.departed_at, detention, now);
  if (!b) return null;
  const billable = b.billableSec > 0;
  const cells = 40;
  const totalSpan = Math.max(b.freeSec + 3600, b.dwellSec + 600);
  const fill = Math.round((b.dwellSec / totalSpan) * cells);
  const freeCells = Math.round((b.freeSec / totalSpan) * cells);
  const n = notice || stop.notice || {};
  const [d, c] = money(b.accrued).split(".");
  return (
    <div data-testid={testid} className={cn("rounded-xl border bg-card p-4 md:p-5 card-shadow", billable && "border-emerald-200")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{title}</div>
          {subtitle && <div className="truncate font-mono text-xs text-muted-foreground">{subtitle}</div>}
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          <StatusChip status={billable ? "billable" : "on_site"} live={!stop.departed_at} />
          {n.status === "sent" && <StatusChip status="notice_sent" label={`Notice ${fmtClock(n.sent_at, tz)}`} />}
          {n.status === "awaiting_approval" && <StatusChip status="awaiting_approval" />}
        </div>
      </div>
      <div className={cn("mt-4 grid items-end gap-4", compact ? "grid-cols-2" : "grid-cols-3")}>
        <div className="col-span-1">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{billable ? "Detention earned" : "Billable in"}</div>
          {billable ? (
            <div data-testid={`${testid}-billable-amount`} aria-live="polite"
              className={cn("num font-mono font-semibold leading-none text-emerald-700", compact ? "text-2xl" : "text-3xl md:text-4xl")}>
              {d}<span className="text-lg opacity-70">.{c}</span>
            </div>
          ) : (
            <div data-testid={`${testid}-free-left`} className={cn("num font-mono font-semibold leading-none", compact ? "text-2xl" : "text-3xl md:text-4xl")}>
              {clock(b.freeLeftSec)}
            </div>
          )}
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">On site</div>
          <div className="num font-mono text-lg font-medium">{clock(b.dwellSec)}</div>
        </div>
        {!compact && (
          <div className="text-right">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Rate · cap</div>
            <div className="num font-mono text-sm">{money(b.rate, 0)}/hr · {b.cap ? money(b.cap, 0) : "no cap"}</div>
          </div>
        )}
      </div>
      <div className="mt-4 flex gap-[3px]" aria-hidden>
        {Array.from({ length: cells }).map((_, i) => {
          const on = i < fill;
          const inFree = i < freeCells;
          return <span key={i} className={cn("h-3 flex-1 rounded-[2px]",
            !on ? "bg-muted" : b.capped ? "bg-red-300" : inFree ? (i >= freeCells - 3 ? "bg-amber-300" : "bg-slate-300") : "bg-emerald-400")} />;
        })}
      </div>
      <div className="mt-2 flex justify-between font-mono text-[11px] text-muted-foreground">
        <span>In {fmtClock(stop.arrived_at, tz)}</span>
        <span>Free ends {fmtClock(b.freeExpiresAt, tz)}</span>
        <span>{b.capped ? "Cap reached" : `Billed so far ${money(b.billed)}`}</span>
      </div>
    </div>
  );
};
