import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { MoreHorizontal, Send, ExternalLink, FileDown, PauseCircle, PlayCircle, CheckCircle2, Ban, AlertOctagon, RotateCcw, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useApi, errMsg } from "@/lib/api";
import { useFleet } from "@/lib/fleet";
import { money, fmtTime } from "@/lib/format";
import { StatusChip } from "@/components/StatusChip";
import { EvidenceSeal } from "@/components/EvidenceSeal";
import { cn } from "@/lib/utils";

const TABS = [["ready", "Ready"], ["sent", "Sent"], ["paid", "Paid"], ["closed", "Disputed / closed"], ["all", "All"]];

const Reminders = ({ inv }) => (
  <div className="flex items-center gap-1" title="Reminders on day 3, 7, 14, 30">
    {inv.reminder_plan.map((r) => (
      <span key={r.day} className={cn("grid h-5 w-7 place-items-center rounded font-mono text-[10px]",
        r.sent ? "bg-teal-600 text-white" : inv.reminders_paused || inv.status !== "sent" ? "bg-slate-100 text-slate-400" : "bg-slate-100 text-slate-600")}>d{r.day}</span>
    ))}
    {inv.reminders_paused && inv.status === "sent" && <span className="ml-1 text-[10px] text-amber-700">paused</span>}
  </div>
);

export default function Invoices() {
  const api = useApi();
  const { fleet } = useFleet();
  const tz = fleet?.timezone;
  const [invs, setInvs] = useState(null);
  const [tab, setTab] = useState("ready");
  const [paid, setPaid] = useState(null);
  const [detail, setDetail] = useState(null);
  const load = useCallback(() => api.get("/invoices").then((r) => setInvs(r.data)).catch((e) => toast.error(errMsg(e))), [api]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (invs && tab === "ready" && !invs.some((i) => i.status === "ready") && invs.length) setTab("all"); }, [invs]); // eslint-disable-line

  const rows = useMemo(() => (invs || []).filter((i) => tab === "all" || (tab === "closed" ? ["disputed", "written_off"].includes(i.status) : i.status === tab)), [invs, tab]);
  const totals = useMemo(() => ({ ready: (invs || []).filter((i) => i.status === "ready").reduce((a, i) => a + i.amount, 0), sent: (invs || []).filter((i) => i.status === "sent").reduce((a, i) => a + i.amount, 0), paid: (invs || []).filter((i) => i.status === "paid").reduce((a, i) => a + (i.paid_amount || i.amount), 0) }), [invs]);

  const run = async (fn, ok) => { try { const r = await fn(); if (ok) toast.success(ok); await load(); if (detail) setDetail(r?.data || null); } catch (e) { toast.error(errMsg(e)); } };
  const status = (inv, action, ok, extra = {}) => run(() => api.post(`/invoices/${inv.id}/status`, { action, ...extra }), ok);
  const send = (inv) => run(() => api.post(`/invoices/${inv.id}/send`), inv.status === "ready" ? "Invoice sealed and emailed to broker" : "Invoice re-sent");
  const pdf = async (inv) => { try { const r = await api.get(`/invoices/${inv.id}/pdf`, { responseType: "blob" }); window.open(URL.createObjectURL(r.data), "_blank"); } catch (e) { toast.error(errMsg(e)); } };
  const openDetail = async (inv) => { try { setDetail((await api.get(`/invoices/${inv.id}`)).data); } catch (e) { toast.error(errMsg(e)); } };

  return (
    <div className="space-y-6">
      <div><h1 className="font-display text-2xl font-semibold tracking-tight">Invoices</h1><p className="text-sm text-muted-foreground">Detention packets, follow-ups and payments.</p></div>
      <div className="grid grid-cols-3 gap-4">
        {[["Ready to send", totals.ready, "invoices-total-ready"], ["Waiting on brokers", totals.sent, "invoices-total-sent"], ["Collected", totals.paid, "invoices-total-paid"]].map(([l, v, t]) => (
          <div key={l} className="rounded-xl border bg-card p-4 card-shadow"><div className="text-xs text-muted-foreground">{l}</div><div data-testid={t} className="num mt-1 font-mono text-xl font-semibold">{money(v)}</div></div>
        ))}
      </div>
      <Tabs value={tab} onValueChange={setTab}><TabsList>{TABS.map(([k, l]) => <TabsTrigger key={k} value={k} data-testid={`invoices-tab-${k}`}>{l}</TabsTrigger>)}</TabsList></Tabs>
      <div className="rounded-xl border bg-card">
        {!invs ? <div className="p-4"><Skeleton className="h-32" /></div> : rows.length === 0 ? (
          <div data-testid="invoices-empty" className="p-10 text-center text-sm text-muted-foreground">No invoices here. Invoices appear automatically when a truck leaves a stop with billable detention.</div>
        ) : (
          <div className="divide-y">
            {rows.map((inv) => (
              <div key={inv.id} data-testid={`invoice-row-${inv.id}`} className="grid grid-cols-[1fr_auto] items-center gap-4 p-4 md:grid-cols-[150px_1.4fr_120px_150px_170px_auto]">
                <button onClick={() => openDetail(inv)} className="text-left"><div className="font-mono text-sm font-semibold hover:underline">{inv.number}</div><Link to={`/app/loads/${inv.load_id}`} className="text-xs text-muted-foreground hover:underline">Load {inv.load_number}</Link></button>
                <div className="hidden min-w-0 md:block"><div className="truncate text-sm">{inv.broker_name}</div><div className="truncate text-xs text-muted-foreground">{inv.facility_name}</div></div>
                <div className="num hidden text-right font-mono text-sm font-semibold md:block">{money(inv.amount)}</div>
                <div className="hidden md:block"><StatusChip status={inv.status} />{inv.viewed_at && <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground"><Eye className="h-3 w-3" />viewed {fmtTime(inv.viewed_at, tz)}</div>}</div>
                <div className="hidden md:block"><Reminders inv={inv} /></div>
                <div className="flex items-center justify-end gap-2">
                  <span className="num font-mono text-sm md:hidden">{money(inv.amount)}</span>
                  {inv.status === "ready" && <Button data-testid={`invoice-send-${inv.id}`} size="sm" onClick={() => send(inv)}><Send className="mr-1.5 h-3.5 w-3.5" />Send</Button>}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild><Button data-testid={`invoice-actions-${inv.id}`} size="icon" variant="ghost"><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-52">
                      {inv.status === "sent" && <DropdownMenuItem data-testid="invoice-action-resend" onClick={() => send(inv)}><Send className="mr-2 h-4 w-4" />Re-send to broker</DropdownMenuItem>}
                      {inv.status !== "ready" && <DropdownMenuItem asChild><a href={inv.evidence_url} target="_blank" rel="noreferrer" data-testid="invoice-action-evidence"><ExternalLink className="mr-2 h-4 w-4" />Open evidence page</a></DropdownMenuItem>}
                      <DropdownMenuItem data-testid="invoice-action-pdf" onClick={() => pdf(inv)}><FileDown className="mr-2 h-4 w-4" />Preview PDF packet</DropdownMenuItem>
                      <DropdownMenuSeparator />
                      {inv.status === "sent" && (inv.reminders_paused
                        ? <DropdownMenuItem data-testid="invoice-action-resume" onClick={() => status(inv, "resume", "Reminders resumed")}><PlayCircle className="mr-2 h-4 w-4" />Resume reminders</DropdownMenuItem>
                        : <DropdownMenuItem data-testid="invoice-action-pause" onClick={() => status(inv, "pause", "Reminders paused")}><PauseCircle className="mr-2 h-4 w-4" />Pause reminders</DropdownMenuItem>)}
                      {["sent", "disputed", "ready"].includes(inv.status) && <DropdownMenuItem data-testid="invoice-action-mark-paid" onClick={() => setPaid({ inv, method: "check" })}><CheckCircle2 className="mr-2 h-4 w-4" />Mark paid…</DropdownMenuItem>}
                      {inv.status === "sent" && <DropdownMenuItem data-testid="invoice-action-dispute" onClick={() => status(inv, "dispute", "Marked disputed")}><AlertOctagon className="mr-2 h-4 w-4" />Mark disputed</DropdownMenuItem>}
                      {["sent", "disputed", "ready"].includes(inv.status) && <DropdownMenuItem data-testid="invoice-action-write-off" onClick={() => status(inv, "write_off", "Written off")}><Ban className="mr-2 h-4 w-4" />Write off</DropdownMenuItem>}
                      {["disputed", "written_off", "paid"].includes(inv.status) && <DropdownMenuItem data-testid="invoice-action-reopen" onClick={() => status(inv, "reopen", "Reopened")}><RotateCcw className="mr-2 h-4 w-4" />Reopen</DropdownMenuItem>}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={!!paid} onOpenChange={(o) => !o && setPaid(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Mark {paid?.inv.number} paid</DialogTitle><DialogDescription>Use this when the broker paid outside DockClock. Reminders stop.</DialogDescription></DialogHeader>
          <Select value={paid?.method} onValueChange={(m) => setPaid({ ...paid, method: m })}>
            <SelectTrigger data-testid="mark-paid-method-select"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="check">Check</SelectItem><SelectItem value="ach">ACH</SelectItem><SelectItem value="factoring">Through factoring company</SelectItem><SelectItem value="other">Other</SelectItem></SelectContent>
          </Select>
          <DialogFooter><Button variant="outline" onClick={() => setPaid(null)}>Cancel</Button>
            <Button data-testid="mark-paid-confirm" onClick={() => { status(paid.inv, "mark_paid", "Marked paid", { method: paid.method }); setPaid(null); }}>Mark paid</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          {detail && <>
            <SheetHeader><SheetTitle className="font-mono">{detail.number}</SheetTitle></SheetHeader>
            <div data-testid="invoice-detail-sheet" className="mt-4 space-y-5 text-sm">
              <div className="flex items-center justify-between"><StatusChip status={detail.status} /><span className="num font-mono text-2xl font-semibold">{money(detail.amount)}</span></div>
              <EvidenceSeal verification={detail.verification} tz={tz} />
              <div className="space-y-1.5">
                <div className="flex justify-between"><span className="text-muted-foreground">Broker</span><span>{detail.broker_email || detail.load?.broker?.email}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Sent</span><span className="font-mono">{fmtTime(detail.sent_at, tz)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Paid</span><span className="font-mono">{detail.paid_at ? `${fmtTime(detail.paid_at, tz)} · ${detail.paid_method}` : "—"}</span></div>
              </div>
              <div><div className="mb-2 font-medium">Follow-up sequence</div>
                <div className="space-y-1.5">{detail.reminder_plan.map((r) => (
                  <div key={r.day} className="flex justify-between rounded-lg border px-3 py-2"><span>Day {r.day}</span><span className="font-mono text-xs">{r.sent ? `sent ${fmtTime(r.sent_at, tz)}` : r.due_at ? `due ${fmtTime(r.due_at, tz)}` : "starts when sent"}</span></div>))}</div></div>
              <div><div className="mb-2 font-medium">History</div>
                <ol className="space-y-1 font-mono text-xs text-muted-foreground">{(detail.history || []).map((h, i) => <li key={i}>{fmtTime(h.at, tz)} · {h.action.replace(/_/g, " ")}{h.to ? ` → ${h.to}` : ""}</li>)}
                  {!(detail.history || []).length && <li>Not sent yet.</li>}</ol></div>
            </div>
          </>}
        </SheetContent>
      </Sheet>
    </div>
  );
}
