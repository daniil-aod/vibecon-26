import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { FileDown, ShieldCheck, AlertTriangle, CheckCircle2, Send, Upload, PhoneCall, RefreshCcw, Flag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { errMsg } from "@/lib/api";
import { money, fmtTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE = { ok: "bg-teal-50 text-teal-800 ring-teal-200", warn: "bg-amber-50 text-amber-900 ring-amber-200", bad: "bg-rose-50 text-rose-800 ring-rose-200", idle: "bg-slate-50 text-slate-600 ring-slate-200" };
const SUB = {
  not_started: ["Not started", "idle"], blocked: ["Blocked", "warn"], awaiting_review: ["Awaiting dispatcher review", "warn"],
  revision_review: ["Revision awaiting review", "warn"], queued: ["Queued", "idle"], sending: ["Sending", "idle"],
  accepted: ["Accepted", "ok"], failed: ["Failed", "bad"], uncertain: ["Uncertain - reconcile", "bad"],
  awaiting_portal: ["Awaiting portal submission", "warn"], awaiting_manual: ["Awaiting manual submission", "warn"], not_needed: ["Not needed (no detention)", "ok"],
};
const OBL = { on_time: ["On time", "ok"], late: ["Late", "bad"], missed: ["Missed", "bad"], pending: ["Pending", "idle"], not_needed: ["Not needed", "idle"],
  missing: ["Not recorded", "warn"], not_recorded: ["Not recorded", "warn"], recorded: ["Recorded", "ok"], accepted: ["Accepted", "ok"] };
const localNow = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const toIso = (v) => (v ? new Date(v).toISOString() : null);

function Chip({ label, value, tone, testid }) {
  return <div data-testid={testid} className={cn("rounded-xl px-3 py-2 ring-1", TONE[tone] || TONE.idle)}><div className="text-[10px] uppercase tracking-wide opacity-70">{label}</div><div className="text-sm font-medium">{value}</div></div>;
}

export function BillingPanel({ api, loadId, tz, stops, onChanged }) {
  const [b, setB] = useState(null);
  const [busy, setBusy] = useState("");
  const [f, setF] = useState({ ref: "", reason: "", arrived: "", departed: localNow(), approver: "", amethod: "email", aref: "", aat: localNow(),
    doc: "pod", docStop: "", callAt: localNow(), callTo: "", callStop: "", adjNote: "" });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const refresh = useCallback(async () => { try { setB((await api.get(`/loads/${loadId}/billing`)).data); } catch { /* keep last */ } }, [api, loadId]);
  useEffect(() => { refresh(); const t = setInterval(refresh, 15000); return () => clearInterval(t); }, [refresh]);
  const run = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); if (r?.data?.completion) setB(r.data); else await refresh(); if (ok) toast.success(ok); onChanged?.(); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); }
  };
  const openPdf = async (p) => { try { const r = await api.get(`/packets/${p.id}/pdf`, { responseType: "blob" }); window.open(URL.createObjectURL(r.data), "_blank"); } catch (e) { toast.error(errMsg(e)); } };
  if (!b) return null;
  const c = b.completion || {};
  const tr = b.transport || {};
  const sub = c.submission || { state: "not_started" };
  const [subLabel, subTone] = SUB[sub.state] || [sub.state, "idle"];
  const blockers = c.blockers || [];
  const docs = b.documents || {};
  const pay = c.payment || {};
  const unverified = (stops || []).flatMap((s) => (s.bol || []).filter((d) => !d.signature_verified && ["signed_bol", "pod", "bol_photo", undefined].includes(d.doc_type)).map((d) => ({ ...d, stop: s })));
  const phoneObl = (b.obligations || []).filter((o) => o.kind?.startsWith("notice_") && o.kind !== "notice_email");
  const finalOpen = (stops || []).some((s) => !s.departed_at);
  const canSubmit = !blockers.length && ["awaiting_review", "revision_review"].includes(sub.state);
  const job = (b.outbox || []).find((j) => j.kind === "billing_submission");

  return (
    <div data-testid="billing-panel" className="rounded-2xl border bg-card p-5 card-shadow">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Completion & billing packet</h2>
        <span className="text-xs text-muted-foreground">Mode: <b data-testid="billing-mode-label">{b.setup?.mode === "auto" ? "Send automatically" : "Dispatcher review"}</b>{b.setup?.confirmed_at ? " · confirmed" : " · not confirmed"}</span>
      </div>
      {b.submission_mode !== "live" && <p data-testid="billing-simulated-banner" className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">Test mode: submissions and broker emails are SIMULATED - nothing is sent to real recipients.</p>}

      <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-6">
        <Chip testid="state-transport" label="Transport" value={tr.state === "completed" ? "Load completed" : tr.state === "in_progress" ? "In progress" : "Not started"} tone={tr.state === "completed" ? "ok" : "idle"} />
        <Chip testid="state-documents" label="Documents" value={docs.state === "complete" ? "Complete" : docs.state === "none_required" ? "None required" : `${(docs.missing || []).length + (docs.unverified || []).length} open`} tone={docs.state === "missing" ? "warn" : "ok"} />
        <Chip testid="state-approvals" label="Approvals" value={{ approved: "Recorded", not_required: "Not required", missing: "Missing", unknown: "Not stated" }[c.approvals?.state] || "-"} tone={c.approvals?.state === "missing" ? "warn" : c.approvals?.state === "unknown" ? "idle" : "ok"} />
        <Chip testid="state-packet" label="Packet" value={c.packet?.state === "issued" ? `Issued v${c.packet.version}` : c.packet?.state === "draft" ? `Draft v${c.packet.version}` : "None"} tone={c.packet?.state === "issued" ? "ok" : "idle"} />
        <Chip testid="state-submission" label="Submission" value={subLabel + (sub.simulated ? " (simulated)" : "")} tone={subTone} />
        <Chip testid="state-payment" label="Payment" value={pay.state === "n/a" ? "-" : `${pay.state} · ${money(pay.outstanding || 0)} open`} tone={pay.state === "paid" ? "ok" : "idle"} />
      </div>
      {tr.state === "completed" && <p className="mt-2 text-xs text-muted-foreground">Completed {fmtTime(tr.completed_at, tz)} via {tr.manual ? `manual completion by dispatcher (${tr.manual.reason})` : ({ geofence: "GPS geofence exit", driver_tap: "driver tap", dispatcher_edit: "dispatcher adjustment" }[tr.source] || tr.source)}. Detention calculated: <b>{money(c.billing_total || 0)}</b>.</p>}
      {c.summary && <p data-testid="completion-summary" className="mt-2 rounded-lg bg-slate-50 p-2 text-xs">{c.summary.text}</p>}

      {!!blockers.length && (
        <div data-testid="billing-blockers" className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-900"><AlertTriangle className="h-4 w-4" />What's missing before billing can be submitted</div>
          <ul className="mt-2 space-y-1.5">{blockers.map((x, i) => <li key={i} data-testid={`blocker-${x.code}`} className="text-xs"><span className="font-medium">{x.message}</span> <span className="text-amber-800">→ {x.action}</span></li>)}</ul>
        </div>
      )}

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border p-3 text-xs">
          <div className="font-semibold">Destination</div>
          <div className="mt-1" data-testid="billing-destination">{b.destination.channel === "email" ? `Email: ${b.destination.recipient || "no valid AP email"} (${b.destination.basis || "not set"})` : b.destination.channel === "portal" ? `Portal: ${b.destination.portal_url || "-"}` : b.destination.channel === "other" ? b.destination.other_text || "Other method" : "Not set"}</div>
          <div className="text-muted-foreground">{b.destination.company || ""}{!b.attachments_supported && b.destination.channel === "email" ? " · sent as a secure PDF link (attachments not supported)" : ""}</div>
          {!b.setup?.confirmed_at && <div className="mt-2 flex gap-2">
            {["review", "auto"].map((mo) => <Button key={mo} data-testid={`billing-confirm-${mo}`} size="sm" variant={mo === "review" ? "default" : "outline"} disabled={!!busy} onClick={() => run("setup", () => api.post(`/loads/${loadId}/billing/setup`, { mode: mo }), "Billing setup confirmed")}>Confirm · {mo === "review" ? "review first" : "send automatically"}</Button>)}
          </div>}
        </div>
        <div className="rounded-xl border p-3 text-xs">
          <div className="font-semibold">Packet versions</div>
          {!(b.packets || []).length && <div className="mt-1 text-muted-foreground">A draft is generated as soon as the load is completed.</div>}
          {(b.packets || []).map((p) => (
            <div key={p.id} className="mt-1 flex items-center justify-between gap-2" data-testid={`packet-v${p.version}`}>
              <span>v{p.version} · {p.status}{p.issued_at ? ` ${fmtTime(p.issued_at, tz)}` : ""}{p.supplements?.length ? ` · ${p.supplements.length} late-evidence supplement(s)` : ""}</span>
              <Button size="sm" variant="ghost" data-testid={`packet-download-v${p.version}`} onClick={() => openPdf(p)}><FileDown className="h-4 w-4" /></Button>
            </div>))}
          {b.issued_verification?.state && b.issued_verification.state !== "none" && <div className="mt-1 flex items-center gap-1 text-teal-800" data-testid="packet-verification"><ShieldCheck className="h-3.5 w-3.5" />Issued packet {b.issued_verification.state}{b.source_comparison?.state === "amended" ? ` · source records amended since issue (${b.source_comparison.changed.join(", ")})` : ""}</div>}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {canSubmit && <Button data-testid="billing-submit-button" disabled={!!busy} onClick={() => run("submit", () => api.post(`/loads/${loadId}/billing/submit`), "Billing packet submitted")}><Send className="mr-2 h-4 w-4" />{sub.state === "revision_review" ? "Issue revised packet & submit" : "Approve & submit"}</Button>}
        {["awaiting_portal", "awaiting_manual"].includes(sub.state) && <>
          <Input data-testid="portal-ref-input" className="w-56" placeholder="Portal confirmation #" value={f.ref} onChange={(e) => set("ref", e.target.value)} />
          <Button data-testid="portal-done-button" variant="outline" disabled={!!busy} onClick={() => run("portal", () => api.post(`/loads/${loadId}/billing/portal-submitted`, { reference: f.ref }), "Submission recorded")}>Record submission</Button></>}
        {job && ["uncertain", "failed"].includes(job.status) && <>
          <span className="self-center text-xs text-rose-700">{job.status === "uncertain" ? "The provider did not confirm. Check with the payor before resending." : `Failed: ${job.error}`}</span>
          <Input data-testid="reconcile-ref-input" className="w-56" placeholder="How you confirmed it arrived" value={f.recRef || ""} onChange={(e) => set("recRef", e.target.value)} />
          <Button size="sm" variant="outline" data-testid="reconcile-accepted-button" onClick={() => run("rec", () => api.post(`/outbox/${job.id}/resolve`, { action: "mark_accepted", reference: f.recRef }), "Marked as received")}><CheckCircle2 className="mr-1 h-4 w-4" />It arrived</Button>
          <Button size="sm" variant="outline" data-testid="reconcile-retry-button" onClick={() => run("rec", () => api.post(`/outbox/${job.id}/resolve`, { action: "retry" }), "Retry started")}><RefreshCcw className="mr-1 h-4 w-4" />Send again</Button></>}
      </div>
      {sub.state === "accepted" && <p data-testid="submission-accepted-note" className="mt-2 text-xs text-muted-foreground">{sub.simulated ? "SIMULATED submission recorded" : "Accepted by the email provider"} {fmtTime(sub.accepted_at, tz)} to {sub.to || sub.channel} · ref {sub.provider_ref}. Acceptance is not proof of delivery, approval or payment.</p>}

      <div className="mt-5">
        <div className="text-sm font-semibold">Obligations</div>
        <div className="mt-2 overflow-x-auto"><table className="w-full text-xs" data-testid="obligations-table"><thead><tr className="text-left text-muted-foreground"><th className="py-1">Obligation</th><th>Stop</th><th>Method</th><th>Due</th><th>Status</th></tr></thead>
          <tbody>{(b.obligations || []).map((o, i) => { const [l, t] = OBL[o.status] || [String(o.status).replace(/_/g, " "), "idle"]; return (
            <tr key={i} className="border-t"><td className="py-1.5">{o.label}{o.note ? <div className="text-[10px] text-amber-800">{o.note}</div> : null}</td><td>{o.stop || "Load"}</td><td>{o.method}</td><td>{o.due_at ? fmtTime(o.due_at, tz) : "-"}</td>
              <td><span className={cn("rounded-full px-2 py-0.5 ring-1", TONE[t])}>{l}</span></td></tr>); })}</tbody></table></div>
        {!!phoneObl.length && <div className="mt-2 flex flex-wrap items-center gap-2 text-xs"><PhoneCall className="h-4 w-4" />
          <Select value={f.callStop || phoneObl[0].stop_id} onValueChange={(x) => set("callStop", x)}><SelectTrigger className="w-40" data-testid="call-stop-select"><SelectValue /></SelectTrigger><SelectContent>{phoneObl.map((o) => <SelectItem key={o.stop_id} value={o.stop_id}>{o.stop}</SelectItem>)}</SelectContent></Select>
          <Input type="datetime-local" className="w-48" data-testid="call-at-input" value={f.callAt} onChange={(e) => set("callAt", e.target.value)} />
          <Input className="w-40" placeholder="Who you spoke to" data-testid="call-to-input" value={f.callTo} onChange={(e) => set("callTo", e.target.value)} />
          <Button size="sm" variant="outline" data-testid="record-call-button" onClick={() => run("call", () => api.post(`/loads/${loadId}/stops/${f.callStop || phoneObl[0].stop_id}/notice-record`, { method: phoneObl[0].kind.replace("notice_", ""), at: toIso(f.callAt), to: f.callTo }), "Notice recorded")}>Record notice</Button></div>}
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border p-3 text-xs">
          <div className="font-semibold">Supporting documents</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Select value={f.docStop || (stops || []).slice(-1)[0]?.id} onValueChange={(x) => set("docStop", x)}><SelectTrigger className="w-40" data-testid="doc-stop-select"><SelectValue /></SelectTrigger><SelectContent>{(stops || []).map((s) => <SelectItem key={s.id} value={s.id}>{s.type} · {s.facility_name}</SelectItem>)}</SelectContent></Select>
            <Select value={f.doc} onValueChange={(x) => set("doc", x)}><SelectTrigger className="w-36" data-testid="doc-type-select"><SelectValue /></SelectTrigger><SelectContent>{[["pod", "Signed POD"], ["signed_bol", "Signed BOL"], ["lumper_receipt", "Lumper receipt"], ["detention_log", "In/out log"], ["other", "Other"]].map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent></Select>
            <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1.5"><Upload className="h-3.5 w-3.5" />Upload<input data-testid="doc-file-input" type="file" accept="image/*,application/pdf" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; if (!file) return; const fd = new FormData(); fd.append("file", file); run("doc", () => api.post(`/loads/${loadId}/stops/${f.docStop || stops.slice(-1)[0].id}/documents?doc_type=${f.doc}`, fd), "Document added"); e.target.value = ""; }} /></label>
          </div>
          {unverified.map((d) => <div key={d.file_id} className="mt-2 flex items-center justify-between gap-2" data-testid={`unverified-doc-${d.file_id}`}><span>{d.doc_type || "BOL photo"} · {d.stop.facility_name} · signature not confirmed</span>
            <Button size="sm" variant="outline" data-testid={`verify-signature-${d.file_id}`} onClick={() => run("sig", () => api.post(`/loads/${loadId}/stops/${d.stop.id}/documents/${d.file_id}/verify-signature`), "Signature confirmed")}>I checked: signed</Button></div>)}
        </div>
        <div className="rounded-xl border p-3 text-xs">
          <div className="font-semibold">Accessorial approval</div>
          {(b.approvals || []).map((a) => <div key={a.id} className="mt-1">{a.method} · {a.approver} · {fmtTime(a.at, tz)} {a.reference}</div>)}
          <div className="mt-2 grid grid-cols-2 gap-2">
            <Input placeholder="Approved by" data-testid="approval-by-input" value={f.approver} onChange={(e) => set("approver", e.target.value)} />
            <Input placeholder="Reference / email subject" value={f.aref} onChange={(e) => set("aref", e.target.value)} />
            <Select value={f.amethod} onValueChange={(x) => set("amethod", x)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{["email", "phone", "portal", "revised_rate_con"].map((k) => <SelectItem key={k} value={k}>{k.replace(/_/g, " ")}</SelectItem>)}</SelectContent></Select>
            <Input type="datetime-local" value={f.aat} onChange={(e) => set("aat", e.target.value)} />
          </div>
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="outline" data-testid="record-approval-button" onClick={() => run("appr", () => api.post(`/loads/${loadId}/approvals`, { method: f.amethod, approver: f.approver, reference: f.aref, at: toIso(f.aat) }), "Approval recorded")}>Record approval</Button>
            <Button size="sm" variant="ghost" data-testid="request-approval-button" onClick={() => run("req", async () => { const r = await api.post(`/loads/${loadId}/approvals/request`); toast.info(r.data.sent ? `Approval request queued${r.data.simulated ? " (simulated)" : ""}` : r.data.detail); })}>Request approval</Button>
          </div>
        </div>
      </div>

      {(tr.review_flags || []).map((x) => <div key={x.stop_id} className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-amber-50 p-2 text-xs" data-testid={`review-flag-${x.code}`}><span><Flag className="mr-1 inline h-3.5 w-3.5" />{x.message}</span>
        <Button size="sm" variant="outline" onClick={() => run("flag", () => api.post(`/loads/${loadId}/flags/${x.stop_id}/confirm`, { note: "Confirmed by dispatcher" }), "Departure confirmed")}>Confirm departure</Button></div>)}
      {(b.conflicts || []).filter((x) => !x.resolved).map((x) => <div key={x.field} className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-rose-50 p-2 text-xs" data-testid={`conflict-${x.field}`}>
        <span>Documents disagree on <b>{x.field}</b>: rate con “{String(x.ratecon)}” vs agreement “{String(x.agreement)}”. You decide which applies.</span>
        <Button size="sm" variant="outline" onClick={() => run("cf", () => api.post(`/loads/${loadId}/conflicts/resolve`, { field: x.field, value: "ratecon" }), "Resolved")}>Use rate con</Button>
        <Button size="sm" variant="outline" onClick={() => run("cf", () => api.post(`/loads/${loadId}/conflicts/resolve`, { field: x.field, value: "agreement" }), "Resolved")}>Use agreement</Button></div>)}
      {(b.invoices || []).filter((i) => i.pending_adjustment).map((i) => <div key={i.id} className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-2 text-xs" data-testid={`pending-adjustment-${i.number}`}>
        <span>{i.number} was issued at {money(i.amount)}; the corrected amount is {money(i.pending_adjustment.new_amount)}. The original stays unchanged; a correction bills or credits only the difference.</span>
        <Input className="w-48" placeholder="Reason" value={f.adjNote} onChange={(e) => set("adjNote", e.target.value)} />
        <Button size="sm" variant="outline" onClick={() => run("adj", () => api.post(`/invoices/${i.id}/adjust`, { note: f.adjNote }), "Correction issued")}>Issue correction</Button></div>)}

      <div className="mt-5 grid gap-3 md:grid-cols-2">
        {finalOpen && <div className="rounded-xl border p-3 text-xs" data-testid="manual-complete-card">
          <div className="font-semibold">GPS failed? Complete the load manually</div>
          <p className="mt-1 text-muted-foreground">Times are entered in your computer's time zone.</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <label>Final stop arrival<Input type="datetime-local" data-testid="manual-arrived-input" value={f.arrived} onChange={(e) => set("arrived", e.target.value)} /></label>
            <label>Final stop departure<Input type="datetime-local" data-testid="manual-departed-input" value={f.departed} onChange={(e) => set("departed", e.target.value)} /></label>
          </div>
          <Input className="mt-2" placeholder="Reason (required)" data-testid="manual-reason-input" value={f.reason} onChange={(e) => set("reason", e.target.value)} />
          <Button size="sm" className="mt-2" variant="outline" data-testid="manual-complete-button" onClick={() => run("mc", () => api.post(`/loads/${loadId}/complete`, { reason: f.reason, arrived_at: toIso(f.arrived), departed_at: toIso(f.departed) }), "Load completed")}>Mark load completed</Button>
        </div>}
        <div className="rounded-xl border p-3 text-xs">
          <div className="font-semibold">Broker-carrier agreement (optional)</div>
          <p className="mt-1 text-muted-foreground">Fills terms the rate con leaves out. Differences are shown for you to resolve.</p>
          <label className="mt-2 inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1.5"><Upload className="h-3.5 w-3.5" />{busy === "agr" ? "Reading..." : "Upload agreement PDF"}<input data-testid="agreement-file-input" type="file" accept="application/pdf" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; if (!file) return; const fd = new FormData(); fd.append("file", file); run("agr", () => api.post(`/loads/${loadId}/agreement`, fd), "Agreement read"); e.target.value = ""; }} /></label>
        </div>
      </div>
    </div>
  );
}
