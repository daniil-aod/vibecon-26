import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { BellRing, FileText, ArrowRight, AlertTriangle, Upload, Timer, Wallet, CircleDollarSign } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, errMsg } from "@/lib/api";
import { useFleet } from "@/lib/fleet";
import { money, ago } from "@/lib/format";
import { FleetMap } from "@/components/Maps";
import { DetentionMeter } from "@/components/DetentionMeter";
import { StatusChip } from "@/components/StatusChip";

const Kpi = ({ icon: Icon, label, value, testid }) => (
  <div className="rounded-xl border bg-card p-4 md:p-5 card-shadow">
    <div className="flex items-center gap-2 text-xs text-muted-foreground"><Icon className="h-4 w-4" />{label}</div>
    <div data-testid={testid} className="num mt-2 font-mono text-2xl font-semibold">{value}</div>
  </div>
);

export default function Dashboard() {
  const api = useApi();
  const nav = useNavigate();
  const { fleet } = useFleet();
  const [d, setD] = useState(null);
  const load = useCallback(async () => {
    try { setD((await api.get("/dashboard")).data); } catch (e) { toast.error(errMsg(e)); }
  }, [api]);
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); }, [load]);

  const approve = async (a) => {
    try { await api.post(`/loads/${a.load_id}/stops/${a.stop_id}/notice`); toast.success("Broker notice sent"); load(); }
    catch (e) { toast.error(errMsg(e)); }
  };
  const sendInv = async (a) => {
    try { await api.post(`/invoices/${a.invoice_id}/send`); toast.success("Invoice emailed to broker"); load(); }
    catch (e) { toast.error(errMsg(e)); }
  };

  if (!d) return <div className="space-y-4"><Skeleton className="h-32 w-full" /><Skeleton className="h-96 w-full" /></div>;
  const empty = d.kpis.loads === 0;
  return (
    <div className="space-y-6">
      <section data-testid="dashboard-monday-headline" className="relative overflow-hidden rounded-2xl bg-slate-950 p-6 text-white md:p-8 noise">
        <div className="relative flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            <div className="font-mono text-xs uppercase tracking-wider text-teal-300">Monday summary · last week</div>
            <p data-testid="dashboard-headline-text" className="mt-3 font-display text-xl leading-snug md:text-2xl">{d.headline}</p>
            <p className="mt-2 text-sm text-slate-400">{d.this_week_headline}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button data-testid="dashboard-upload-ratecon-button" onClick={() => nav("/app/loads/new")} className="bg-teal-400 text-slate-950 hover:bg-teal-300"><Upload className="mr-2 h-4 w-4" />Upload rate con</Button>
            <Button data-testid="dashboard-view-invoices-button" variant="outline" onClick={() => nav("/app/invoices")} className="border-slate-700 bg-slate-900 text-white hover:bg-slate-800 hover:text-white">Invoices</Button>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 md:gap-6">
        <Kpi icon={Timer} label="On site now" value={d.kpis.active_stops} testid="kpi-active-stops" />
        <Kpi icon={FileText} label="Invoices ready" value={d.kpis.ready_invoices} testid="kpi-ready-invoices" />
        <Kpi icon={Wallet} label="Outstanding" value={money(d.kpis.outstanding, 0)} testid="kpi-outstanding" />
        <Kpi icon={CircleDollarSign} label="Recovered" value={money(d.kpis.recovered, 0)} testid="kpi-recovered" />
      </div>

      {empty && (
        <div data-testid="dashboard-empty-state" className="rounded-2xl border border-dashed bg-card p-10 text-center">
          <h3 className="font-display text-lg font-semibold">Start with your next rate con</h3>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">Upload the PDF, check the terms the AI found, and text your driver the check-in link. Everything else here fills in from real check-ins.</p>
          <Button className="mt-5" onClick={() => nav("/app/loads/new")}>Upload rate con</Button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <div className="mb-3 flex items-center justify-between"><h2 className="font-display text-lg font-semibold">Fleet map</h2>
            <span className="text-xs text-muted-foreground">{d.trucks.length} truck{d.trucks.length !== 1 ? "s" : ""} reporting</span></div>
          <FleetMap facilities={d.facilities} trucks={d.trucks} height={440} />
        </div>
        <div className="space-y-6 lg:col-span-5">
          <div>
            <h2 className="mb-3 font-display text-lg font-semibold">Live detention meters</h2>
            {d.meters.length === 0 ? (
              <div className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">No trucks on site right now. Meters start the moment a driver's phone enters a facility geofence.</div>
            ) : (
              <div className="space-y-3">
                {d.meters.map((m) => (
                  <Link key={m.stop_id} to={`/app/loads/${m.load_id}`} className="block">
                    <DetentionMeter testid={`meter-${m.stop_id}`} compact stop={{ arrived_at: m.arrived_at, notice: m.notice }} detention={m.detention}
                      title={m.facility_name} subtitle={`Load ${m.load_number} · ${m.broker_name || ""}`} tz={fleet?.timezone} />
                  </Link>
                ))}
              </div>
            )}
          </div>
          <div>
            <h2 className="mb-3 font-display text-lg font-semibold">Needs attention</h2>
            <div data-testid="dashboard-attention-list" className="divide-y rounded-xl border bg-card">
              {d.attention.length === 0 && <div className="p-5 text-sm text-muted-foreground">All clear.</div>}
              {d.attention.map((a, i) => (
                <div key={i} className="flex items-center gap-3 p-4">
                  {a.kind === "invoice_ready" ? <FileText className="h-4 w-4 text-indigo-600" /> : a.kind === "notice_failed" ? <AlertTriangle className="h-4 w-4 text-red-600" /> : <BellRing className="h-4 w-4 text-amber-600" />}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {a.kind === "invoice_ready" ? `Invoice ready · ${money(a.amount)}` : a.kind === "notice_failed" ? "Broker notice failed" : "Approve broker notice"}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">Load {a.load_number} · {a.facility_name}{a.detail ? ` · ${a.detail}` : ""}</div>
                  </div>
                  {a.kind === "invoice_ready" && <Button data-testid={`attention-send-invoice-${a.invoice_id}`} size="sm" onClick={() => sendInv(a)}>Send</Button>}
                  {a.kind === "notice_approval" && <Button data-testid={`attention-approve-notice-${a.stop_id}`} size="sm" onClick={() => approve(a)}>Send notice</Button>}
                  {a.kind === "notice_failed" && <Button size="sm" variant="outline" onClick={() => nav(`/app/loads/${a.load_id}`)}>Fix</Button>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {d.recent_loads.length > 0 && (
        <div>
          <div className="mb-3 flex items-center justify-between"><h2 className="font-display text-lg font-semibold">Recent loads</h2>
            <Link to="/app/loads" className="flex items-center text-sm text-teal-700 hover:underline">All loads <ArrowRight className="ml-1 h-3.5 w-3.5" /></Link></div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {d.recent_loads.map((l) => (
              <Link key={l.id} to={`/app/loads/${l.id}`} data-testid={`recent-load-${l.id}`} className="lift rounded-xl border bg-card p-4">
                <div className="flex items-center justify-between gap-2"><span className="truncate font-mono text-sm font-semibold">{l.load_number}</span><StatusChip status={l.status} live={l.status === "on_site"} /></div>
                <div className="mt-2 truncate text-xs text-muted-foreground">{l.broker?.name}</div>
                <div className="mt-3 flex items-end justify-between"><span className="num font-mono text-lg">{money(l.detention_total)}</span><span className="text-[11px] text-muted-foreground">{ago(l.created_at)}</span></div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
