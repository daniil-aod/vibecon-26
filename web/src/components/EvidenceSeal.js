import { ShieldCheck, ShieldAlert, Shield } from "lucide-react";
import { fmtTime } from "@/lib/format";

export const EvidenceSeal = ({ verification, tz }) => {
  const v = verification || { state: "unsealed" };
  if (v.state === "verified") {
    return (
      <div data-testid="evidence-seal-verified" className="rounded-lg border-2 border-double border-emerald-600 bg-emerald-50 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800"><ShieldCheck className="h-5 w-5" />Evidence fingerprint verified</div>
        <p className="mt-1 text-xs text-emerald-900/80">Timestamps, GPS trail, BOL photos, clause and notice log match the seal made {fmtTime(v.sealed_at, tz, { zone: true })}.</p>
        <div className="mt-2 break-all font-mono text-[11px] text-emerald-900">SHA-256 {v.fingerprint}</div>
      </div>
    );
  }
  if (v.state === "changed") {
    return (
      <div data-testid="evidence-seal-changed" className="rounded-lg border-2 border-double border-red-600 bg-red-50 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-red-800"><ShieldAlert className="h-5 w-5" />Evidence changed since it was sealed</div>
        <p className="mt-1 text-xs text-red-900/80">Changed: {(v.changed_fields || []).join(", ") || "unknown"}</p>
        <div className="mt-2 break-all font-mono text-[11px] text-red-900">Sealed {v.fingerprint}<br />Now {v.current}</div>
      </div>
    );
  }
  return (
    <div data-testid="evidence-seal-unsealed" className="rounded-lg border border-dashed bg-muted/50 p-4">
      <div className="flex items-center gap-2 text-sm font-semibold"><Shield className="h-5 w-5" />Not sealed yet</div>
      <p className="mt-1 text-xs text-muted-foreground">The evidence fingerprint is sealed when the invoice is sent. Any later change will show on the broker's page.</p>
    </div>
  );
};
