import { Plus, Trash2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

export const emptyLoad = () => ({
  load_number: "", carrier_name: "", linehaul_amount: null,
  broker: { name: "", contact_name: "", email: "", phone: "" },
  detention: { free_time_hours: 2, hourly_rate: null, billing_increment_minutes: 15, cap_amount: null, cap_scope: "per_stop",
    notice_after_arrival_minutes: null, notice_before_expiry_minutes: null, notice_rule_text: "", requires_signed_bol: true, clause_text: "" },
  stops: [{ type: "pickup", facility_name: "", address: "", appointment: "" }, { type: "delivery", facility_name: "", address: "", appointment: "" }],
  driver: { name: "", phone: "" }, low_confidence: [],
});

export const fromExtracted = (x) => {
  const base = emptyLoad();
  return {
    ...base, load_number: x.load_number || "", carrier_name: x.carrier_name || "", linehaul_amount: x.linehaul_amount,
    broker: { ...base.broker, ...Object.fromEntries(Object.entries(x.broker || {}).map(([k, v]) => [k, v || ""])) },
    detention: { ...base.detention, ...Object.fromEntries(Object.entries(x.detention || {}).filter(([, v]) => v !== null && v !== undefined)) },
    stops: (x.stops || []).length ? x.stops.map((s) => ({ type: s.type === "delivery" ? "delivery" : "pickup", facility_name: s.facility_name || "", address: s.address || "", appointment: (s.appointment || "").slice(0, 16) })) : base.stops,
    low_confidence: x.low_confidence || [],
  };
};

const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

function F({ label, path, lc, children, hint }) {
  const flag = lc.includes(path);
  return (
    <div className={cn("space-y-1.5", flag && "rounded-lg bg-amber-50 p-2 ring-1 ring-amber-300")}>
      <Label className="flex items-center gap-2 text-xs">{label}{flag && <span data-testid={`low-confidence-${path}`} className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800"><AlertTriangle className="h-3 w-3" />Check this</span>}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default function LoadForm({ value: v, onChange, showDriver = true }) {
  const lc = v.low_confidence || [];
  const set = (patch) => onChange({ ...v, ...patch });
  const setB = (k, x) => set({ broker: { ...v.broker, [k]: x } });
  const setD = (k, x) => set({ detention: { ...v.detention, [k]: x } });
  const setS = (i, k, x) => set({ stops: v.stops.map((s, j) => (j === i ? { ...s, [k]: x } : s)) });
  const d = v.detention;
  return (
    <div className="space-y-8">
      <section>
        <h3 className="mb-3 text-sm font-semibold">Detention terms</h3>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <F label="Free time (hours)" path="detention.free_time_hours" lc={lc}><Input data-testid="form-free-time-input" type="number" step="0.25" min="0" value={d.free_time_hours ?? ""} onChange={(e) => setD("free_time_hours", num(e.target.value))} /></F>
          <F label="Hourly rate ($)" path="detention.hourly_rate" lc={lc}><Input data-testid="form-hourly-rate-input" type="number" step="1" min="0" value={d.hourly_rate ?? ""} onChange={(e) => setD("hourly_rate", num(e.target.value))} /></F>
          <F label="Billing increment (min)" path="detention.billing_increment_minutes" lc={lc}><Input data-testid="form-increment-input" type="number" min="1" value={d.billing_increment_minutes ?? ""} onChange={(e) => setD("billing_increment_minutes", num(e.target.value))} /></F>
          <F label="Cap ($)" path="detention.cap_amount" lc={lc} hint="Leave empty if no cap"><div className="flex gap-2"><Input data-testid="form-cap-input" type="number" min="0" value={d.cap_amount ?? ""} onChange={(e) => setD("cap_amount", num(e.target.value))} />
            <Select value={d.cap_scope || "per_stop"} onValueChange={(x) => setD("cap_scope", x)}><SelectTrigger data-testid="form-cap-scope-select" className="w-[120px]"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="per_stop">per stop</SelectItem><SelectItem value="per_day">per day</SelectItem><SelectItem value="per_load">per load</SelectItem></SelectContent></Select></div></F>
          <F label="Notify within (min after arrival)" path="detention.notice_after_arrival_minutes" lc={lc}><Input data-testid="form-notice-after-input" type="number" min="0" value={d.notice_after_arrival_minutes ?? ""} onChange={(e) => setD("notice_after_arrival_minutes", num(e.target.value))} /></F>
          <F label="Notify before free time ends (min)" path="detention.notice_before_expiry_minutes" lc={lc} hint="0 = any time before it ends. Empty + empty = 30 min before."><Input data-testid="form-notice-before-input" type="number" min="0" value={d.notice_before_expiry_minutes ?? ""} onChange={(e) => setD("notice_before_expiry_minutes", num(e.target.value))} /></F>
          <div className="sm:col-span-2"><F label="Notice rule (plain English)" path="detention.notice_rule_text" lc={lc}><Input data-testid="form-notice-rule-input" value={d.notice_rule_text || ""} onChange={(e) => setD("notice_rule_text", e.target.value)} /></F></div>
        </div>
        <div className="mt-4"><F label="Detention clause (verbatim from the rate con)" path="detention.clause_text" lc={lc}>
          <Textarea data-testid="form-clause-textarea" rows={4} className="clause-mark font-mono text-[13px] leading-relaxed" value={d.clause_text || ""} onChange={(e) => setD("clause_text", e.target.value)} /></F></div>
        <label className="mt-3 flex items-center gap-2 text-sm"><Switch data-testid="form-requires-bol-switch" checked={!!d.requires_signed_bol} onCheckedChange={(x) => setD("requires_signed_bol", x)} />Signed BOL with in/out times required</label>
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold">Load & broker</h3>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <F label="Load number" path="load_number" lc={lc}><Input data-testid="form-load-number-input" value={v.load_number || ""} onChange={(e) => set({ load_number: e.target.value })} /></F>
          <F label="Broker" path="broker.name" lc={lc}><Input data-testid="form-broker-name-input" value={v.broker.name || ""} onChange={(e) => setB("name", e.target.value)} /></F>
          <F label="Broker email (notices & invoices)" path="broker.email" lc={lc}><Input data-testid="form-broker-email-input" type="email" value={v.broker.email || ""} onChange={(e) => setB("email", e.target.value)} /></F>
          <F label="Broker contact" path="broker.contact_name" lc={lc}><Input data-testid="form-broker-contact-input" value={v.broker.contact_name || ""} onChange={(e) => setB("contact_name", e.target.value)} /></F>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">Stops</h3>
          <Button data-testid="form-add-stop-button" type="button" variant="outline" size="sm" onClick={() => set({ stops: [...v.stops, { type: "delivery", facility_name: "", address: "", appointment: "" }] })}><Plus className="mr-1 h-4 w-4" />Add stop</Button></div>
        <div className="space-y-3">
          {v.stops.map((s, i) => (
            <div key={s.id || i} data-testid={`form-stop-${i}`} className="grid gap-3 rounded-xl border bg-slate-50 p-3 md:grid-cols-[120px_1fr_1.4fr_190px_auto]">
              <Select value={s.type} onValueChange={(x) => setS(i, "type", x)} disabled={!!s.arrived_at}>
                <SelectTrigger data-testid={`form-stop-${i}-type`} className="bg-white"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="pickup">Pickup</SelectItem><SelectItem value="delivery">Delivery</SelectItem></SelectContent></Select>
              <Input data-testid={`form-stop-${i}-facility`} className="bg-white" placeholder="Facility name" value={s.facility_name || ""} disabled={!!s.arrived_at} onChange={(e) => setS(i, "facility_name", e.target.value)} />
              <Input data-testid={`form-stop-${i}-address`} className="bg-white" placeholder="Street, city, state ZIP" value={s.address || ""} disabled={!!s.arrived_at} onChange={(e) => setS(i, "address", e.target.value)} />
              <Input data-testid={`form-stop-${i}-appointment`} className="bg-white" type="datetime-local" value={(s.appointment || "").slice(0, 16)} onChange={(e) => setS(i, "appointment", e.target.value)} />
              <Button type="button" variant="ghost" size="icon" disabled={v.stops.length <= 1 || !!s.arrived_at} data-testid={`form-stop-${i}-remove`} onClick={() => set({ stops: v.stops.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
        </div>
      </section>

      {showDriver && (
        <section>
          <h3 className="mb-3 text-sm font-semibold">Driver</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <F label="Driver name" path="driver.name" lc={[]}><Input data-testid="form-driver-name-input" value={v.driver.name || ""} onChange={(e) => set({ driver: { ...v.driver, name: e.target.value } })} /></F>
            <F label="Driver mobile" path="driver.phone" lc={[]} hint="US numbers can be 10 digits"><Input data-testid="form-driver-phone-input" type="tel" value={v.driver.phone || ""} onChange={(e) => set({ driver: { ...v.driver, phone: e.target.value } })} /></F>
          </div>
        </section>
      )}
    </div>
  );
}
