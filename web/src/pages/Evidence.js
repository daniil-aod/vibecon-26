import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { CreditCard, FileDown, Loader2, CheckCircle2, MapPin, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { publicApi, API, errMsg } from "@/lib/api";
import { money, fmtTime, hrs } from "@/lib/format";
import { EvidenceSeal } from "@/components/EvidenceSeal";
import { TrailPlayback } from "@/components/TrailPlayback";
import { StatusChip } from "@/components/StatusChip";

const SRC = { geofence: "Phone entered/left geofence", driver_tap: "Driver tap with GPS", dispatcher_edit: "Dispatcher correction" };
const Ex = ({ id, title, children, testid }) => (
  <section data-testid={testid} className="rounded-xl border bg-white p-5 md:p-6">
    <div className="mb-4 flex items-baseline gap-3 border-b pb-3"><span className="font-mono text-xs font-semibold text-slate-500">EXHIBIT {id}</span><h2 className="text-sm font-semibold uppercase tracking-wide">{title}</h2></div>
    {children}
  </section>
);

export default function Evidence() {
  const { token } = useParams();
  const [sp] = useSearchParams();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [paying, setPaying] = useState(false);
  useEffect(() => { publicApi.get(`/public/evidence/${token}`).then((r) => setD(r.data)).catch((e) => setErr(errMsg(e, "Invoice not found"))); }, [token]);
  useEffect(() => { if (sp.get("payment") === "cancelled") toast.info("Payment cancelled. You can try again anytime."); }, [sp]);

  const pay = async () => {
    setPaying(true);
    try { const { data } = await publicApi.post(`/public/evidence/${token}/checkout`, { origin_url: window.location.origin }); window.location.href = data.checkout_url; }
    catch (e) { toast.error(errMsg(e)); setPaying(false); }
  };

  if (err) return <div className="grid min-h-screen place-items-center p-6 text-center"><div><AlertTriangle className="mx-auto h-10 w-10 text-amber-600" /><p className="mt-3 font-semibold">{err}</p></div></div>;
  if (!d) return <div className="mx-auto max-w-6xl space-y-4 p-6"><Skeleton className="h-28" /><Skeleton className="h-96" /></div>;
  const { invoice: inv, stop: s, terms: t, carrier, broker } = d;
  const tz = carrier.timezone;
  const b = s.billing;
  const paid = inv.status === "paid";

  return (
    <div className="min-h-screen bg-slate-100">
      <div className="bg-white">
        <div className="mx-auto max-w-6xl px-4 py-6 md:px-6 md:py-8">
          <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="font-mono text-xs uppercase tracking-wider text-slate-500">Detention claim · evidence packet</div>
              <h1 data-testid="evidence-title" className="mt-2 font-display text-2xl font-semibold md:text-3xl">Invoice {inv.number} · Load {inv.load_number}</h1>
              <div className="mt-3 grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
                <div><span className="text-slate-500">Carrier </span>{carrier.name}</div>
                <div><span className="text-slate-500">Bill to </span>{broker?.name}</div>
                <div><span className="text-slate-500">Facility </span>{s.facility_name}</div>
                <div><span className="text-slate-500">Date </span>{fmtTime(s.arrived_at, tz)} – {fmtTime(s.departed_at, tz)}</div>
              </div>
            </div>
            <div className="w-full rounded-xl border-2 border-slate-900 p-5 md:w-[300px]">
              <div className="flex items-center justify-between"><span className="text-xs uppercase tracking-wider text-slate-500">Amount due</span><StatusChip status={inv.status} testid="evidence-status" /></div>
              <div data-testid="evidence-amount" className="num mt-1 font-mono text-4xl font-semibold">{money(inv.amount)}</div>
              {paid ? (
                <div data-testid="evidence-paid-banner" className="mt-4 flex items-center gap-2 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800"><CheckCircle2 className="h-4 w-4" />Paid {fmtTime(inv.paid_at, tz)}{inv.paid_method ? ` · ${inv.paid_method}` : ""}</div>
              ) : (
                <Button data-testid="broker-pay-by-card-button" className="mt-4 w-full" size="lg" onClick={pay} disabled={paying || inv.status === "written_off"}>
                  {paying ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CreditCard className="mr-2 h-4 w-4" />}Pay by card</Button>
              )}
              <Button asChild variant="outline" className="mt-2 w-full"><a data-testid="broker-download-pdf-button" href={`${API}/public/evidence/${token}/pdf`}><FileDown className="mr-2 h-4 w-4" />Download PDF packet</a></Button>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 md:px-6">
        <EvidenceSeal verification={d.verification} tz={tz} />
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-5">
            <Ex id="A" title="In / out timestamps" testid="evidence-exhibit-timestamps">
              <dl className="space-y-3 text-sm">
                {[["Arrived (in)", s.arrived_at, s.arrived_source, s.arrived_coords], ["Departed (out)", s.departed_at, s.departed_source, s.departed_coords]].map(([k, at, src, c]) => (
                  <div key={k} className="grid grid-cols-[120px_1fr] gap-2"><dt className="text-slate-500">{k}</dt>
                    <dd><div className="font-mono font-medium">{fmtTime(at, tz, { seconds: true, zone: true })}</div><div className="text-xs text-slate-500">{SRC[src] || src}{c?.lat ? ` · ${c.lat.toFixed(5)}, ${c.lng.toFixed(5)} ±${Math.round(c.accuracy || 0)} m` : ""}</div></dd></div>))}
                <div className="grid grid-cols-[120px_1fr] gap-2"><dt className="text-slate-500">Location</dt><dd className="flex items-start gap-1"><MapPin className="mt-0.5 h-3.5 w-3.5" />{s.address} · geofence {Math.round(s.radius_m || 45)} m</dd></div>
              </dl>
              <div className="mt-5 rounded-lg bg-slate-50 p-4 font-mono text-sm">
                <div className="flex justify-between"><span>Time on site</span><span>{hrs(b.dwell_minutes)}</span></div>
                <div className="flex justify-between"><span>Free time</span><span>− {t.free_time_hours} h</span></div>
                <div className="flex justify-between"><span>Billed ({b.increment || 15}-min increments)</span><span>{(b.billed_minutes / 60).toFixed(2)} h</span></div>
                <div className="flex justify-between"><span>× Rate</span><span>{money(t.hourly_rate)}/hr</span></div>
                {b.capped && <div className="flex justify-between text-amber-700"><span>Cap applied</span><span>{money(t.cap_amount)}</span></div>}
                <div className="mt-2 flex justify-between border-t pt-2 font-semibold"><span>Detention due</span><span data-testid="evidence-calc-total">{money(inv.amount)}</span></div>
              </div>
            </Ex>
            <Ex id="C" title="Rate confirmation clause" testid="evidence-exhibit-clause">
              <blockquote className="clause-mark rounded-r-lg p-4 font-mono text-[13px] leading-relaxed">{t.clause_text || "Clause not captured."}</blockquote>
              {t.notice_rule_text && <p className="mt-3 text-xs text-slate-500">Notice requirement: {t.notice_rule_text}</p>}
            </Ex>
            <Ex id="D" title="Broker notice log" testid="evidence-exhibit-notices">
              {d.notices.length === 0 ? <p className="text-sm text-slate-500">No notice recorded.</p> : (
                <ul className="space-y-2 text-sm">{d.notices.map((n, i) => (
                  <li key={i} className="flex items-start justify-between gap-3 rounded-lg border p-3"><div><div className="font-mono">{fmtTime(n.sent_at, tz, { seconds: true, zone: true })}</div><div className="text-xs text-slate-500">Emailed to {n.to}</div></div>
                    {n.on_time ? <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800">Before free time ended</span> : <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">Logged</span>}</li>))}</ul>)}
            </Ex>
          </div>
          <div className="space-y-5">
            <Ex id="E" title="GPS trail playback" testid="evidence-exhibit-playback">
              <TrailPlayback testid="evidence-playback" pings={d.playback.pings} stops={d.playback.stops} events={d.playback.events} tz={tz} height={340} />
            </Ex>
            <Ex id="B" title="Signed bill of lading" testid="evidence-exhibit-bol">
              {s.bol.length === 0 ? <p className="text-sm text-slate-500">No BOL photo on file.</p> : (
                <div className="grid gap-3 sm:grid-cols-2">{s.bol.map((f) => (
                  <a key={f.file_id} href={`${API}/public/evidence/${token}/files/${f.file_id}`} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border">
                    <img data-testid="evidence-bol-image" src={`${API}/public/evidence/${token}/files/${f.file_id}`} alt="Signed bill of lading" className="h-64 w-full bg-slate-50 object-contain" />
                    <div className="border-t p-2 font-mono text-[10px] text-slate-500">Uploaded {fmtTime(f.uploaded_at, tz)} · {f.sha256.slice(0, 16)}…</div></a>))}</div>)}
            </Ex>
          </div>
        </div>
        <p className="pb-6 text-center text-xs text-slate-500">Questions? Reply to the invoice email or write to {carrier.reply_to_email}. Prepared with DockClock.</p>
      </div>
    </div>
  );
}
