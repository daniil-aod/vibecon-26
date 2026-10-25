import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { toast } from "sonner";
import { Pencil, FileText, Trash2, BellRing, Clock, MapPin, Camera, LogIn, LogOut, Send, Crosshair } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { useApi, errMsg } from "@/lib/api";
import { useFleet } from "@/lib/fleet";
import { money, fmtTime, hrs } from "@/lib/format";
import { StatusChip } from "@/components/StatusChip";
import { DetentionMeter } from "@/components/DetentionMeter";
import { FacilityMap } from "@/components/Maps";
import { TrailPlayback } from "@/components/TrailPlayback";
import { AuthImage } from "@/components/AuthImage";
import LoadForm from "@/pages/LoadForm";
import { DriverEmailCard } from "@/components/DriverEmailCard";

const EVL = { arrival: [LogIn, "Arrived (entered zone)"], departure: [LogOut, "Departed (left zone)"], free_time_expired: [Clock, "Free time ended"], notice_sent: [BellRing, "Broker notice sent"], bol_uploaded: [Camera, "BOL photo uploaded"], ride_started: [Send, "Driver started ride"], ride_ended: [Clock, "Driver ended ride"] };
const SRC = { geofence: "geofence", driver_tap: "driver tap + GPS", dispatcher_edit: "dispatcher edit", ride_end: "driver ended ride" };
const toLocalInput = (iso) => { if (!iso) return ""; const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

export default function LoadDetail() {
  const { id } = useParams();
  const api = useApi();
  const nav = useNavigate();
  const { fleet } = useFleet();
  const tz = fleet?.timezone;
  const [load, setLoad] = useState(null);
  const [pb, setPb] = useState(null);
  const [edit, setEdit] = useState(null);
  const [adjust, setAdjust] = useState(null);
  const [geo, setGeo] = useState(null);
  const [confirmDel, setConfirmDel] = useState(false);
  const [busy, setBusy] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [l, p] = await Promise.all([api.get(`/loads/${id}`), api.get(`/loads/${id}/playback`)]);
      setLoad(l.data); setPb(p.data);
    } catch (e) { toast.error(errMsg(e)); if (e?.response?.status === 404) nav("/app/loads"); }
  }, [api, id, nav]);
  useEffect(() => { refresh(); const t = setInterval(refresh, 15000); return () => clearInterval(t); }, [refresh]);

  const act = async (key, fn, ok) => { setBusy(key); try { await fn(); if (ok) toast.success(ok); await refresh(); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); } };
  const openRatecon = async () => {
    try { const r = await api.get(`/loads/${id}/ratecon`, { responseType: "blob" }); window.open(URL.createObjectURL(r.data), "_blank"); } catch (e) { toast.error(errMsg(e)); }
  };
  const saveEdit = () => act("edit", async () => { await api.put(`/loads/${id}`, edit); setEdit(null); }, "Load updated");
  const saveAdjust = () => act("adjust", async () => {
    await api.post(`/loads/${id}/stops/${adjust.stop.id}/adjust`, {
      arrived_at: adjust.arrived ? new Date(adjust.arrived).toISOString() : null,
      departed_at: adjust.departed ? new Date(adjust.departed).toISOString() : null, reason: adjust.reason });
    setAdjust(null);
  }, "Times updated");
  const saveGeo = () => act("geo", async () => { await api.patch(`/facilities/${geo.facility_id}`, { lat: geo.lat, lng: geo.lng, radius_m: geo.radius_m }); setGeo(null); }, "Geofence saved");
  const sendNotice = (s) => act(`n${s.id}`, () => api.post(`/loads/${id}/stops/${s.id}/notice`), "Broker notice sent");
  const sendInvoice = (inv) => act(`i${inv.id}`, () => api.post(`/invoices/${inv.id}/send`), "Invoice emailed to broker");
  const del = () => act("del", async () => { await api.delete(`/loads/${id}`); nav("/app/loads"); }, "Load deleted");

  if (!load) return <div className="space-y-4"><Skeleton className="h-24" /><Skeleton className="h-80" /></div>;
  const det = load.detention || {};
  const events = [
    ...load.stops.flatMap((s) => (s.events || []).map((e) => ({ ...e, facility: s.facility_name }))),
    ...(load.ride?.started_at ? [{ type: "ride_started", at: load.ride.started_at, facility: "driver app" }] : []),
    ...(load.ride?.ended_at ? [{ type: "ride_ended", at: load.ride.ended_at, facility: "driver app" }] : []),
  ].sort((a, b) => (a.at || "").localeCompare(b.at || ""));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 data-testid="load-detail-number" className="font-mono text-2xl font-semibold">{load.load_number}</h1>
            <StatusChip status={load.status} live={load.status === "on_site"} testid="load-detail-status" />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{load.broker?.name || "No broker"}{load.broker?.email ? ` · ${load.broker.email}` : ""}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {load.ratecon_file_id && <Button data-testid="load-view-ratecon-button" variant="outline" size="sm" onClick={openRatecon}><FileText className="mr-1.5 h-4 w-4" />Rate con</Button>}
          <Button data-testid="load-edit-button" variant="outline" size="sm" onClick={() => setEdit({ ...load, stops: load.stops.map(({ billing, ...s }) => s) })}><Pencil className="mr-1.5 h-4 w-4" />Edit terms</Button>
          <Button data-testid="load-delete-button" variant="ghost" size="sm" onClick={() => setConfirmDel(true)}><Trash2 className="h-4 w-4" /></Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {load.stops.map((s, i) => {
            const onSite = s.arrived_at && !s.departed_at;
            const n = s.notice || {};
            return (
              <div key={s.id} data-testid={`stop-card-${i}`} className="rounded-2xl border bg-card p-5 card-shadow">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Stop {i + 1} · {s.type}</div>
                    <div className="font-display text-lg font-semibold">{s.facility_name}</div>
                    <div className="flex items-center gap-1 text-xs text-muted-foreground"><MapPin className="h-3 w-3" />{s.address}{s.appointment ? ` · Appt ${s.appointment.replace("T", " ")}` : ""}</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <StatusChip testid={`stop-${i}-notice-status`} status={n.status || "pending"} label={n.status === "sent" ? `Notice sent ${fmtTime(n.sent_at, tz)}` : n.status === "pending" && n.due_at ? `Notice due ${fmtTime(n.due_at, tz)}` : undefined} />
                  </div>
                </div>
                {onSite && <div className="mt-4"><DetentionMeter testid={`stop-${i}-meter`} stop={s} detention={det} title="Live detention meter" subtitle={`Arrived via ${SRC[s.arrived_source] || s.arrived_source}`} tz={tz} /></div>}
                <div className="mt-4 grid gap-4 md:grid-cols-[1fr_1.1fr]">
                  <div className="space-y-2 text-sm">
                    <Row k="In" v={s.arrived_at ? `${fmtTime(s.arrived_at, tz, { zone: true })}` : "Not yet"} sub={SRC[s.arrived_source]} testid={`stop-${i}-in`} />
                    <Row k="Out" v={s.departed_at ? `${fmtTime(s.departed_at, tz, { zone: true })}` : onSite ? "On site" : "Not yet"} sub={SRC[s.departed_source]} testid={`stop-${i}-out`} />
                    <Row k="On site" v={s.arrived_at ? hrs(s.billing.dwell_minutes) : "—"} />
                    <Row k="Billed time" v={s.billing.billed_minutes ? hrs(s.billing.billed_minutes) : "—"} />
                    <Row k="Detention" v={money(s.billing.amount)} strong testid={`stop-${i}-amount`} sub={s.billing.capped ? "cap reached" : ""} />
                    <div className="flex flex-wrap gap-2 pt-2">
                      <Button data-testid={`stop-${i}-adjust-button`} size="sm" variant="outline" onClick={() => setAdjust({ stop: s, arrived: toLocalInput(s.arrived_at), departed: toLocalInput(s.departed_at), reason: "" })}><Clock className="mr-1.5 h-3.5 w-3.5" />Adjust times</Button>
                      <Button data-testid={`stop-${i}-geofence-button`} size="sm" variant="outline" onClick={() => setGeo({ facility_id: s.facility_id, name: s.facility_name, lat: s.lat ?? 39.5, lng: s.lng ?? -98.35, radius_m: s.radius_m || 45, type: s.type })}><Crosshair className="mr-1.5 h-3.5 w-3.5" />Geofence</Button>
                      {onSite && !n.sent_at && <Button data-testid={`stop-${i}-send-notice-button`} size="sm" disabled={busy === `n${s.id}`} onClick={() => sendNotice(s)}><BellRing className="mr-1.5 h-3.5 w-3.5" />{n.status === "awaiting_approval" ? "Approve & send notice" : "Send notice now"}</Button>}
                    </div>
                  </div>
                  <FacilityMap testid={`stop-${i}-map`} stops={[s]} height={220} trail={(pb?.pings || []).filter((p) => p.stop_id === s.id)} />
                </div>
                {s.lat == null && <div className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">This address wasn't found on the map. Set the geofence pin so arrival can be stamped automatically.</div>}
                {(s.bol || []).length > 0 && (
                  <div className="mt-4"><div className="mb-2 text-xs font-medium text-muted-foreground">Signed BOL photos</div>
                    <div className="flex flex-wrap gap-3">{s.bol.map((b) => <AuthImage key={b.file_id} testid={`stop-${i}-bol-image`} fileId={b.file_id} alt="Bill of lading" className="h-28 w-24 rounded-lg border" />)}</div></div>
                )}
              </div>
            );
          })}

          <div>
            <h2 className="mb-3 font-display text-lg font-semibold">Truck playback</h2>
            {pb ? <TrailPlayback pings={pb.pings} stops={pb.stops} events={pb.events} tz={tz} /> : <Skeleton className="h-80" />}
          </div>
        </div>

        <div className="space-y-6">
          <DriverEmailCard api={api} load={load} tz={tz} onChanged={refresh} />

          <div className="rounded-2xl border bg-card p-5 card-shadow">
            <h3 className="text-sm font-semibold">Rate con terms</h3>
            <div className="mt-3 space-y-2 text-sm">
              <Row k="Free time" v={`${det.free_time_hours ?? 0} h`} /><Row k="Rate" v={`${money(det.hourly_rate || 0)}/hr`} />
              <Row k="Increments" v={`${det.billing_increment_minutes || 15} min`} /><Row k="Cap" v={det.cap_amount ? `${money(det.cap_amount)} ${String(det.cap_scope || "").replace("_", " ")}` : "None"} />
              <Row k="Notice rule" v={det.notice_rule_text || "30 min before free time ends (default)"} />
            </div>
            {det.clause_text && <blockquote data-testid="load-clause-text" className="clause-mark mt-4 rounded-r-lg p-3 font-mono text-[12px] leading-relaxed">{det.clause_text}</blockquote>}
          </div>

          <div className="rounded-2xl border bg-card p-5 card-shadow">
            <h3 className="text-sm font-semibold">Invoices</h3>
            {load.invoices.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">An invoice packet is built automatically when the truck leaves a stop with billable detention.</p> : (
              <div className="mt-3 space-y-2">{load.invoices.map((inv) => (
                <div key={inv.id} data-testid={`load-invoice-${inv.id}`} className="flex items-center gap-3 rounded-lg border p-3">
                  <div className="min-w-0 flex-1"><div className="font-mono text-sm font-semibold">{inv.number}</div><div className="truncate text-xs text-muted-foreground">{inv.facility_name}</div></div>
                  <span className="num font-mono text-sm">{money(inv.amount)}</span>
                  {inv.status === "ready" ? <Button size="sm" data-testid={`load-send-invoice-${inv.id}`} disabled={busy === `i${inv.id}`} onClick={() => sendInvoice(inv)}><Send className="mr-1 h-3.5 w-3.5" />Send</Button> : <StatusChip status={inv.status} />}
                </div>))}
                <Link to="/app/invoices" className="block pt-1 text-xs text-teal-700 hover:underline">Manage invoices</Link>
              </div>
            )}
          </div>

          <div className="rounded-2xl border bg-card p-5 card-shadow">
            <h3 className="text-sm font-semibold">Timeline</h3>
            <ol data-testid="load-timeline" className="mt-3 space-y-3">
              {events.length === 0 && <li className="text-sm text-muted-foreground">Nothing yet.</li>}
              {events.map((e, i) => { const [Icon, label] = EVL[e.type] || [Clock, e.type]; return (
                <li key={i} className="flex gap-3"><Icon className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
                  <div><div className="text-sm font-medium">{label} <span className="font-normal text-muted-foreground">· {e.facility}</span></div>
                    <div className="font-mono text-[11px] text-muted-foreground">{fmtTime(e.at, tz, { seconds: true })}{e.source ? ` · ${SRC[e.source] || e.source}` : ""}{e.to ? ` · to ${e.to}` : ""}{e.note ? ` · "${e.note}"` : ""}</div></div></li>); })}
            </ol>
          </div>
        </div>
      </div>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto">
          <DialogHeader><DialogTitle>Edit load terms</DialogTitle><DialogDescription>Changes apply to live meters and unsent invoices.</DialogDescription></DialogHeader>
          {edit && <LoadForm value={edit} onChange={setEdit} />}
          <DialogFooter><Button variant="outline" onClick={() => setEdit(null)}>Cancel</Button><Button data-testid="load-edit-save-button" onClick={saveEdit} disabled={busy === "edit"}>Save changes</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!adjust} onOpenChange={(o) => !o && setAdjust(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Adjust in / out times</DialogTitle><DialogDescription>Use this when the driver's phone missed a stamp. The change and your reason are logged and shown on the evidence page.</DialogDescription></DialogHeader>
          {adjust && <div className="space-y-4">
            <div><Label>Arrived (your local time)</Label><Input data-testid="adjust-arrived-input" type="datetime-local" value={adjust.arrived} onChange={(e) => setAdjust({ ...adjust, arrived: e.target.value })} /></div>
            <div><Label>Departed</Label><Input data-testid="adjust-departed-input" type="datetime-local" value={adjust.departed} onChange={(e) => setAdjust({ ...adjust, departed: e.target.value })} /></div>
            <div><Label>Reason (required)</Label><Input data-testid="adjust-reason-input" placeholder="e.g. Times from signed BOL" value={adjust.reason} onChange={(e) => setAdjust({ ...adjust, reason: e.target.value })} /></div>
          </div>}
          <DialogFooter><Button variant="outline" onClick={() => setAdjust(null)}>Cancel</Button><Button data-testid="adjust-save-button" onClick={saveAdjust} disabled={busy === "adjust" || !adjust?.reason}>Save times</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!geo} onOpenChange={(o) => !o && setGeo(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Geofence · {geo?.name}</DialogTitle><DialogDescription>Click the map to move the pin to the dock entrance. Applies to this facility on all loads not yet arrived.</DialogDescription></DialogHeader>
          {geo && <div className="space-y-4">
            <FacilityMap testid="geofence-edit-map" editable stops={[{ ...geo, id: "g" }]} height={320} onMove={(lat, lng) => setGeo({ ...geo, lat, lng })} />
            <div><Label>Radius: <span className="font-mono">{Math.round(geo.radius_m)} m</span></Label>
              <Slider data-testid="geofence-radius-slider" className="mt-3" min={15} max={3000} step={5} value={[geo.radius_m]} onValueChange={([r]) => setGeo({ ...geo, radius_m: r })} /></div>
          </div>}
          <DialogFooter><Button variant="outline" onClick={() => setGeo(null)}>Cancel</Button><Button data-testid="geofence-save-button" onClick={saveGeo} disabled={busy === "geo"}>Save geofence</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmDel} onOpenChange={setConfirmDel}>
        <AlertDialogContent>
          <AlertDialogHeader><AlertDialogTitle>Delete load {load.load_number}?</AlertDialogTitle><AlertDialogDescription>This removes its GPS trail and unsent invoices. Loads with sent or paid invoices can't be deleted.</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction data-testid="load-delete-confirm" onClick={del}>Delete</AlertDialogAction></AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function Row({ k, v, sub, strong, testid }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-dashed pb-1.5 last:border-0">
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right"><span data-testid={testid} className={`font-mono ${strong ? "font-semibold text-emerald-700" : ""}`}>{v}</span>{sub ? <span className="block text-[11px] text-muted-foreground">{sub}</span> : null}</span>
    </div>
  );
}
