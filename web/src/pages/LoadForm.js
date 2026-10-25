import { Plus, Trash2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

export const EMPTY_BILLING = {
  billing_company: "", billing_address: "", ap_email: "", use_broker_contact_for_billing: false, submission_channel: null,
  portal_url: "", submission_other_text: "", requires_attachment: null, notice_recipient: "", notice_method: null,
  invoice_deadline_days: null, invoice_deadline_trigger: null, required_documents: [], approval_required: null,
  approval_method: null, approval_rule_text: "", payment_terms_days: null, payment_terms_start: null,
};

export const emptyLoad = () => ({
  load_number: "", carrier_name: "", linehaul_amount: null,
  broker: { name: "", contact_name: "", email: "", phone: "" },
  // Unknown stays unknown: no assumed free time, rate, increment or paperwork rule.
  detention: { free_time_hours: null, hourly_rate: null, billing_increment_minutes: null, rounding_rule: null, cap_amount: null, cap_scope: "per_stop",
    per_day_definition: null, billing_start_rule: null, late_arrival_voids: null,
    notice_after_arrival_minutes: null, notice_before_expiry_minutes: null, notice_rule_text: "", requires_signed_bol: null, clause_text: "" },
  billing_terms: { ...EMPTY_BILLING }, refs: { bol_number: "", pro_number: "", po_number: "", shipment_date: "" },
  term_sources: {}, term_refs: {}, billing_mode: "review", confirm_billing: false,
  stops: [{ type: "pickup", facility_name: "", address: "", appointment: "" }, { type: "delivery", facility_name: "", address: "", appointment: "" }],
  driver: { name: "", phone: "", email: "" }, low_confidence: [],
});

export const fromExtracted = (x) => {
  const base = emptyLoad();
  return {
    ...base, load_number: x.load_number || "", carrier_name: x.carrier_name || "", linehaul_amount: x.linehaul_amount,
    broker: { ...base.broker, ...Object.fromEntries(Object.entries(x.broker || {}).map(([k, v]) => [k, v || ""])) },
    detention: { ...base.detention, ...Object.fromEntries(Object.entries(x.detention || {}).filter(([, v]) => v !== null && v !== undefined)) },
    stops: (x.stops || []).length ? x.stops.map((s) => ({ type: s.type === "delivery" ? "delivery" : "pickup", facility_name: s.facility_name || "", address: s.address || "", appointment: (s.appointment || "").slice(0, 16) })) : base.stops,
    low_confidence: x.low_confidence || [],
    billing_terms: { ...base.billing_terms, ...Object.fromEntries(Object.entries(x.billing || {}).filter(([k, v]) => v !== null && v !== undefined && k !== "stop_terms")) },
    refs: { ...base.refs, ...Object.fromEntries(Object.entries(x.references || {}).filter(([, v]) => v)) },
    term_sources: Object.fromEntries([
      ...Object.entries(x.detention || {}).filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k]) => [`detention.${k}`, "extracted"]),
      ...Object.entries(x.billing || {}).filter(([, v]) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length)).map(([k]) => [`billing.${k}`, "extracted"]),
    ]),
    term_refs: Object.fromEntries(Object.entries(x.source_refs || {}).map(([k, r]) => [k, { ...r, source: `Rate con${r?.page ? ` p.${r.page}` : ""}` }])),
  };
};

export const fromLoad = (l) => ({
  ...emptyLoad(), ...l,
  billing_terms: { ...EMPTY_BILLING, ...(l.billing_terms || {}) }, refs: { ...emptyLoad().refs, ...(l.refs || {}) },
  term_sources: l.term_sources || {}, term_refs: l.term_refs || {},
  billing_mode: l.billing_setup?.mode || "review", confirm_billing: false,
});

const SRC_STYLE = { extracted: "bg-sky-50 text-sky-800", confirmed: "bg-teal-50 text-teal-800", agreement: "bg-violet-50 text-violet-800", default: "bg-slate-100 text-slate-600" };
function Src({ v, path, value }) {
  const src = v.term_sources?.[path] || (value === null || value === undefined || value === "" ? "unknown" : null);
  if (!src) return null;
  return <span data-testid={`term-source-${path}`} className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", src === "unknown" ? "bg-amber-50 text-amber-800" : SRC_STYLE[src] || SRC_STYLE.default)}>{src}</span>;
}

function Pick({ value, onChange, options, testid, allowEmpty = true }) {
  return (
    <Select value={value === null || value === undefined ? "__unknown" : String(value)} onValueChange={(x) => onChange(x === "__unknown" ? null : x)}>
      <SelectTrigger data-testid={testid} className="bg-white"><SelectValue /></SelectTrigger>
      <SelectContent>{allowEmpty && <SelectItem value="__unknown">Unknown / not stated</SelectItem>}{Object.entries(options).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent>
    </Select>
  );
}

const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

function F({ label, path, lc, children, hint, src }) {
  const flag = lc.includes(path);
  return (
    <div className={cn("space-y-1.5", flag && "rounded-lg bg-amber-50 p-2 ring-1 ring-amber-300")}>
      <Label className="flex items-center gap-2 text-xs">{label}{src}{flag && <span data-testid={`low-confidence-${path}`} className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800"><AlertTriangle className="h-3 w-3" />Check this</span>}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default function LoadForm({ value: v, onChange, showDriver = true }) {
  const lc = v.low_confidence || [];
  const set = (patch) => onChange({ ...v, ...patch });
  const setB = (k, x) => set({ broker: { ...v.broker, [k]: x } });
  const confirmed = (path) => ({ term_sources: { ...(v.term_sources || {}), [path]: "confirmed" } });
  const setD = (k, x) => set({ detention: { ...v.detention, [k]: x }, ...confirmed(`detention.${k}`) });
  const bt = v.billing_terms || EMPTY_BILLING;
  const setT = (k, x) => set({ billing_terms: { ...bt, [k]: x }, ...confirmed(`billing.${k}`), confirm_billing: false });
  const S = (sec, k, val) => <Src v={v} path={`${sec}.${k}`} value={val} />;
  const docs = bt.required_documents || [];
  const setS = (i, k, x) => set({ stops: v.stops.map((s, j) => (j === i ? { ...s, [k]: x } : s)) });
  const d = v.detention;
  return (
    <div className="space-y-8">
      <section>
        <h3 className="mb-3 text-sm font-semibold">Detention terms</h3>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <F label="Free time (hours)" path="detention.free_time_hours" lc={lc} src={S("detention", "free_time_hours", d.free_time_hours)}><Input data-testid="form-free-time-input" type="number" step="0.25" min="0" value={d.free_time_hours ?? ""} onChange={(e) => setD("free_time_hours", num(e.target.value))} /></F>
          <F label="Hourly rate ($)" path="detention.hourly_rate" lc={lc} src={S("detention", "hourly_rate", d.hourly_rate)}><Input data-testid="form-hourly-rate-input" type="number" step="1" min="0" value={d.hourly_rate ?? ""} onChange={(e) => setD("hourly_rate", num(e.target.value))} /></F>
          <F label="Billing increment (min)" path="detention.billing_increment_minutes" lc={lc} src={S("detention", "billing_increment_minutes", d.billing_increment_minutes)}><Input data-testid="form-increment-input" type="number" min="1" value={d.billing_increment_minutes ?? ""} onChange={(e) => setD("billing_increment_minutes", num(e.target.value))} /></F>
          <F label="Cap ($)" path="detention.cap_amount" lc={lc} hint="Leave empty if no cap"><div className="flex gap-2"><Input data-testid="form-cap-input" type="number" min="0" value={d.cap_amount ?? ""} onChange={(e) => setD("cap_amount", num(e.target.value))} />
            <Select value={d.cap_scope || "per_stop"} onValueChange={(x) => setD("cap_scope", x)}><SelectTrigger data-testid="form-cap-scope-select" className="w-[120px]"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="per_stop">per stop</SelectItem><SelectItem value="per_day">per day</SelectItem><SelectItem value="per_load">per load</SelectItem></SelectContent></Select></div></F>
          <F label="Notify within (min after arrival)" path="detention.notice_after_arrival_minutes" lc={lc}><Input data-testid="form-notice-after-input" type="number" min="0" value={d.notice_after_arrival_minutes ?? ""} onChange={(e) => setD("notice_after_arrival_minutes", num(e.target.value))} /></F>
          <F label="Notify before free time ends (min)" path="detention.notice_before_expiry_minutes" lc={lc} hint="0 = any time before it ends. Empty + empty = 30 min before."><Input data-testid="form-notice-before-input" type="number" min="0" value={d.notice_before_expiry_minutes ?? ""} onChange={(e) => setD("notice_before_expiry_minutes", num(e.target.value))} /></F>
          <div className="sm:col-span-2"><F label="Notice rule (plain English)" path="detention.notice_rule_text" lc={lc}><Input data-testid="form-notice-rule-input" value={d.notice_rule_text || ""} onChange={(e) => setD("notice_rule_text", e.target.value)} /></F></div>
        </div>
        <div className="mt-4"><F label="Detention clause (verbatim from the rate con)" path="detention.clause_text" lc={lc}>
          <Textarea data-testid="form-clause-textarea" rows={4} className="clause-mark font-mono text-[13px] leading-relaxed" value={d.clause_text || ""} onChange={(e) => setD("clause_text", e.target.value)} /></F></div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <F label="Rounding" path="detention.rounding_rule" lc={lc} src={S("detention", "rounding_rule", d.rounding_rule)}>
            <Pick testid="form-rounding-select" value={d.rounding_rule} onChange={(x) => setD("rounding_rule", x)} options={{ completed_increment: "Completed increments only", round_up: "Round up", nearest: "Nearest increment", exact: "Exact minutes" }} /></F>
          <F label="Billing starts at" path="detention.billing_start_rule" lc={lc} src={S("detention", "billing_start_rule", d.billing_start_rule)}>
            <Pick testid="form-billing-start-select" value={d.billing_start_rule} onChange={(x) => setD("billing_start_rule", x)} options={{ arrival: "Arrival", appointment_or_arrival_later: "Appointment or arrival, whichever is later" }} /></F>
          {d.cap_scope === "per_day" && <F label="'Per day' means" path="detention.per_day_definition" lc={lc} src={S("detention", "per_day_definition", d.per_day_definition)}>
            <Pick testid="form-per-day-select" value={d.per_day_definition} onChange={(x) => setD("per_day_definition", x)} options={{ calendar_day: "Calendar day", "24h_block": "Each 24 hours on site" }} /></F>}
          <F label="Late arrival voids detention" path="detention.late_arrival_voids" lc={lc} src={S("detention", "late_arrival_voids", d.late_arrival_voids)}>
            <Pick testid="form-late-voids-select" value={d.late_arrival_voids === null || d.late_arrival_voids === undefined ? null : String(d.late_arrival_voids)} onChange={(x) => setD("late_arrival_voids", x === null ? null : x === "true")} options={{ true: "Yes", false: "No" }} /></F>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm"><Switch data-testid="form-requires-bol-switch" checked={!!d.requires_signed_bol} onCheckedChange={(x) => setD("requires_signed_bol", x)} />Signed BOL with in/out times required {S("detention", "requires_signed_bol", d.requires_signed_bol)}</label>
      </section>

      <section data-testid="form-billing-section">
        <h3 className="mb-1 text-sm font-semibold">Billing & submission</h3>
        <p className="mb-3 text-xs text-muted-foreground">Where the finished detention packet goes and what the payor requires. Leave anything the agreement does not state as unknown.</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <F label="Bill to (company)" path="billing.billing_company" lc={lc} src={S("billing", "billing_company", bt.billing_company)}><Input data-testid="form-billing-company-input" value={bt.billing_company || ""} onChange={(e) => setT("billing_company", e.target.value)} /></F>
          <div className="sm:col-span-2"><F label="Billing address" path="billing.billing_address" lc={lc} src={S("billing", "billing_address", bt.billing_address)}><Input data-testid="form-billing-address-input" value={bt.billing_address || ""} onChange={(e) => setT("billing_address", e.target.value)} /></F></div>
          <F label="Submission method" path="billing.submission_channel" lc={lc} src={S("billing", "submission_channel", bt.submission_channel)}>
            <Pick testid="form-submission-channel-select" value={bt.submission_channel} onChange={(x) => setT("submission_channel", x)} options={{ email: "Email to accounts payable", portal: "Payor portal", other: "Other method" }} /></F>
          {bt.submission_channel === "email" && <F label="Accounts-payable email" path="billing.ap_email" lc={lc} src={S("billing", "ap_email", bt.ap_email)}><Input data-testid="form-ap-email-input" type="email" value={bt.ap_email || ""} onChange={(e) => setT("ap_email", e.target.value)} /></F>}
          {bt.submission_channel === "email" && !bt.ap_email && <label className="flex items-center gap-2 self-end text-xs"><Switch data-testid="form-use-broker-contact-switch" checked={!!bt.use_broker_contact_for_billing} onCheckedChange={(x) => setT("use_broker_contact_for_billing", x)} />Broker contact is the billing recipient</label>}
          {bt.submission_channel === "email" && <F label="Payor requires attachments" path="billing.requires_attachment" lc={lc}><Pick testid="form-requires-attachment-select" value={bt.requires_attachment === null || bt.requires_attachment === undefined ? null : String(bt.requires_attachment)} onChange={(x) => setT("requires_attachment", x === null ? null : x === "true")} options={{ true: "Yes - attachments required", false: "No - a link is fine" }} /></F>}
          {bt.submission_channel === "portal" && <F label="Portal URL" path="billing.portal_url" lc={lc}><Input data-testid="form-portal-url-input" value={bt.portal_url || ""} onChange={(e) => setT("portal_url", e.target.value)} /></F>}
          {bt.submission_channel === "other" && <div className="sm:col-span-2"><F label="How to submit" path="billing.submission_other_text" lc={lc}><Input data-testid="form-other-method-input" value={bt.submission_other_text || ""} onChange={(e) => setT("submission_other_text", e.target.value)} /></F></div>}
          <F label="Notice method required" path="billing.notice_method" lc={lc} src={S("billing", "notice_method", bt.notice_method)}>
            <Pick testid="form-notice-method-select" value={bt.notice_method} onChange={(x) => setT("notice_method", x)} options={{ email: "Email", phone: "Phone call", portal: "Portal", other: "Other" }} /></F>
          <F label="Notice recipient" path="billing.notice_recipient" lc={lc}><Input data-testid="form-notice-recipient-input" value={bt.notice_recipient || ""} onChange={(e) => setT("notice_recipient", e.target.value)} /></F>
          <F label="Invoice within (days)" path="billing.invoice_deadline_days" lc={lc} src={S("billing", "invoice_deadline_days", bt.invoice_deadline_days)}><div className="flex gap-2"><Input data-testid="form-invoice-deadline-input" type="number" min="0" value={bt.invoice_deadline_days ?? ""} onChange={(e) => setT("invoice_deadline_days", num(e.target.value))} />
            <Pick testid="form-deadline-trigger-select" value={bt.invoice_deadline_trigger} onChange={(x) => setT("invoice_deadline_trigger", x)} options={{ delivery: "of delivery", departure: "of departure", pod_receipt: "of POD receipt" }} /></div></F>
          <F label="Payment terms (Net days)" path="billing.payment_terms_days" lc={lc} src={S("billing", "payment_terms_days", bt.payment_terms_days)}><div className="flex gap-2"><Input data-testid="form-payment-days-input" type="number" min="0" value={bt.payment_terms_days ?? ""} onChange={(e) => setT("payment_terms_days", num(e.target.value))} />
            <Pick testid="form-payment-start-select" value={bt.payment_terms_start} onChange={(x) => setT("payment_terms_start", x)} options={{ invoice_submission: "from submission", receipt_of_complete_docs: "from receipt of complete docs", delivery: "from delivery" }} /></div></F>
          <F label="Detention needs prior approval" path="billing.approval_required" lc={lc} src={S("billing", "approval_required", bt.approval_required)}>
            <Pick testid="form-approval-required-select" value={bt.approval_required === null || bt.approval_required === undefined ? null : String(bt.approval_required)} onChange={(x) => setT("approval_required", x === null ? null : x === "true")} options={{ true: "Yes", false: "No" }} /></F>
          {bt.approval_required && <F label="Approval by" path="billing.approval_method" lc={lc}><Pick testid="form-approval-method-select" value={bt.approval_method} onChange={(x) => setT("approval_method", x)} options={{ email: "Email", phone: "Phone", portal: "Portal", revised_rate_con: "Revised signed rate con", other: "Other" }} /></F>}
        </div>
        <div className="mt-4 rounded-xl border p-3">
          <div className="flex items-center justify-between"><Label className="text-xs">Required supporting documents {S("billing", "required_documents", docs.length ? docs : null)}</Label>
            <Button data-testid="form-add-doc-button" type="button" variant="outline" size="sm" onClick={() => setT("required_documents", [...docs, { doc: "pod", stop: "final", label: "" }])}><Plus className="mr-1 h-4 w-4" />Add</Button></div>
          {!docs.length && <p className="mt-2 text-xs text-muted-foreground">None recorded. Add each document the agreement requires (a photo is not proof of a signature).</p>}
          {docs.map((r, i) => (
            <div key={i} className="mt-2 grid gap-2 sm:grid-cols-[1fr_1fr_auto]" data-testid={`form-doc-${i}`}>
              <Pick testid={`form-doc-${i}-type`} value={r.doc} allowEmpty={false} onChange={(x) => setT("required_documents", docs.map((d2, j) => (j === i ? { ...d2, doc: x } : d2)))} options={{ signed_bol: "Signed BOL", pod: "Signed POD", lumper_receipt: "Lumper receipt", detention_log: "In/out log", scale_ticket: "Scale ticket", other: "Other" }} />
              <Pick testid={`form-doc-${i}-stop`} value={r.stop} allowEmpty={false} onChange={(x) => setT("required_documents", docs.map((d2, j) => (j === i ? { ...d2, stop: x } : d2)))} options={{ final: "Final delivery", delivery: "Every delivery", pickup: "Every pickup", any: "Any stop" }} />
              <Button type="button" variant="ghost" size="icon" onClick={() => setT("required_documents", docs.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
            </div>))}
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-4">
          {[["bol_number", "BOL #"], ["pro_number", "PRO #"], ["po_number", "PO / reference"], ["shipment_date", "Shipment date"]].map(([k, l]) => (
            <F key={k} label={l} path={`refs.${k}`} lc={[]}><Input data-testid={`form-ref-${k}`} type={k === "shipment_date" ? "date" : "text"} value={(v.refs || {})[k] || ""} onChange={(e) => set({ refs: { ...(v.refs || {}), [k]: e.target.value } })} /></F>))}
        </div>
        <div data-testid="form-billing-confirm" className="mt-4 rounded-xl border border-teal-200 bg-teal-50/60 p-3">
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <span className="font-medium">When the load is complete:</span>
            <Pick testid="form-billing-mode-select" value={v.billing_mode || "review"} allowEmpty={false} onChange={(x) => set({ billing_mode: x, confirm_billing: false })} options={{ review: "Prepare the packet, a dispatcher reviews before it's sent", auto: "Send automatically once nothing is missing" }} />
          </div>
          <label className="mt-3 flex items-start gap-2 text-sm"><Switch data-testid="form-confirm-billing-switch" checked={!!v.confirm_billing} onCheckedChange={(x) => set({ confirm_billing: x })} />
            <span>I confirm the destination: <b>{bt.submission_channel === "email" ? (bt.ap_email || (bt.use_broker_contact_for_billing ? `${v.broker?.email || "broker email"} (broker contact)` : "no AP email yet")) : bt.submission_channel === "portal" ? `portal ${bt.portal_url || ""}` : bt.submission_channel === "other" ? bt.submission_other_text || "other method" : "method not set"}</b>{bt.billing_company ? ` for ${bt.billing_company}` : ""}, using the mode above.</span></label>
        </div>
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
            <F label="Driver email" path="driver.email" lc={[]} hint="The app link and dock-time recaps are emailed here"><Input data-testid="form-driver-email-input" type="email" value={v.driver.email || ""} onChange={(e) => set({ driver: { ...v.driver, email: e.target.value } })} /></F>
          </div>
        </section>
      )}
    </div>
  );
}
