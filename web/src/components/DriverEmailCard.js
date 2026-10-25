import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Mail, CalendarClock, Trash2, Copy, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { errMsg } from "@/lib/api";
import { fmtTime } from "@/lib/format";

const KIND = { link: "App link", recap: "Dock-time recap" };
const FREQ = { once: "One time", daily: "Daily", weekly: "Weekly", monthly: "Monthly" };
const inHour = () => { const d = new Date(Date.now() + 3600e3); d.setMinutes(0, 0, 0); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

// Email the driver the app link or a recap of their dock times — now, or on a schedule.
export function DriverEmailCard({ api, load, tz, onChanged }) {
  const [busy, setBusy] = useState("");
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState({ kind: "link", frequency: "once", at: inHour() });
  const email = load.driver?.email;

  const refresh = useCallback(async () => {
    try { setRows((await api.get(`/loads/${load.id}/email-schedules`)).data); } catch { /* list stays as is */ }
  }, [api, load.id]);
  useEffect(() => { refresh(); }, [refresh]);

  const sendNow = async (kind) => {
    setBusy(kind);
    try {
      const { data } = await api.post(`/loads/${load.id}/email-driver`, { kind });
      if (data.sent) toast.success(kind === "link" ? "App link emailed to driver" : "Recap emailed to driver");
      else toast.error(`Email failed: ${data.detail || data.reason}`);
      onChanged?.();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); }
  };
  const schedule = async () => {
    setBusy("sched");
    try {
      await api.post(`/loads/${load.id}/email-schedules`, { kind: form.kind, frequency: form.frequency, send_at: new Date(form.at).toISOString() });
      toast.success("Email scheduled");
      await refresh();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); }
  };
  const remove = async (s) => {
    try { await api.delete(`/email-schedules/${s.id}`); toast.success("Schedule removed"); await refresh(); } catch (e) { toast.error(errMsg(e)); }
  };
  const copyLink = async () => { try { await navigator.clipboard.writeText(load.driver_url); toast.success("Driver link copied"); } catch { toast.info(load.driver_url); } };
  const lastEmail = (load.email_log || []).slice(-1)[0];

  return (
    <div data-testid="driver-email-card" className="rounded-2xl border bg-card p-5 card-shadow">
      <h3 className="text-sm font-semibold">Driver app link</h3>
      <p className="mt-1 text-sm">{load.driver?.name || "No driver yet"} <span className="font-mono text-muted-foreground">{email || "no email"}</span></p>
      {!email && <p data-testid="driver-email-missing-note" className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">Add the driver's email with “Edit terms” to send the app link.</p>}
      <div className="mt-4 flex flex-col gap-2">
        <Button data-testid="load-email-driver-button" onClick={() => sendNow("link")} disabled={!email || !!busy}><Mail className="mr-2 h-4 w-4" />{busy === "link" ? "Sending…" : "Email driver the app link"}</Button>
        <Button data-testid="load-email-recap-button" variant="outline" onClick={() => sendNow("recap")} disabled={!email || !!busy}>{busy === "recap" ? "Sending…" : "Email dock-time recap"}</Button>
        <div className="flex gap-2">
          <Button data-testid="load-copy-link-button" variant="outline" className="flex-1" onClick={copyLink}><Copy className="mr-2 h-4 w-4" />Copy link</Button>
          <Button asChild variant="outline"><a data-testid="load-open-driver-link" href={`/api/open/${load.driver_token}`} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" /></a></Button>
        </div>
      </div>
      {lastEmail && <p data-testid="driver-last-email" className="mt-3 text-xs text-muted-foreground">Last email: {KIND[lastEmail.kind] || lastEmail.kind} · {fmtTime(lastEmail.at, tz)} · {lastEmail.sent ? "sent" : lastEmail.detail || lastEmail.reason}</p>}

      <div className="mt-5 border-t pt-4">
        <div className="flex items-center gap-2 text-sm font-semibold"><CalendarClock className="h-4 w-4" />Schedule an email</div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div><Label className="text-xs">What</Label>
            <Select value={form.kind} onValueChange={(kind) => setForm({ ...form, kind })}>
              <SelectTrigger data-testid="schedule-kind-select"><SelectValue /></SelectTrigger>
              <SelectContent>{Object.entries(KIND).map(([k, l]) => <SelectItem key={k} value={k} data-testid={`schedule-kind-${k}`}>{l}</SelectItem>)}</SelectContent>
            </Select></div>
          <div><Label className="text-xs">How often</Label>
            <Select value={form.frequency} onValueChange={(frequency) => setForm({ ...form, frequency })}>
              <SelectTrigger data-testid="schedule-frequency-select"><SelectValue /></SelectTrigger>
              <SelectContent>{Object.entries(FREQ).map(([k, l]) => <SelectItem key={k} value={k} data-testid={`schedule-frequency-${k}`}>{l}</SelectItem>)}</SelectContent>
            </Select></div>
        </div>
        <Label className="mt-2 block text-xs">{form.frequency === "once" ? "Send at" : "First send at"}</Label>
        <Input data-testid="schedule-time-input" type="datetime-local" value={form.at} onChange={(e) => setForm({ ...form, at: e.target.value })} />
        <Button data-testid="schedule-save-button" className="mt-2 w-full" variant="outline" onClick={schedule} disabled={!email || !form.at || busy === "sched"}>{busy === "sched" ? "Saving…" : "Schedule email"}</Button>
        <p className="mt-2 text-[11px] text-muted-foreground">Enter the time in your computer's local time; schedule times below are shown in the fleet's time zone. Emails go out within 15 minutes of the set time.</p>
        <ul className="mt-3 space-y-2">
          {rows.map((s, i) => (
            <li key={s.id} data-testid={`schedule-row-${i}`} className="flex items-start justify-between gap-2 rounded-lg border p-2 text-xs">
              <div>
                <div className="font-medium">{KIND[s.kind]} · {FREQ[s.frequency]}</div>
                <div className="text-muted-foreground">{s.active ? `Next: ${fmtTime(s.next_run_at, tz)}` : "Done"}{s.last_sent_at ? ` · last ${fmtTime(s.last_sent_at, tz)} (${s.last_result})` : ""}</div>
              </div>
              <Button data-testid={`schedule-delete-${i}`} size="sm" variant="ghost" onClick={() => remove(s)}><Trash2 className="h-3.5 w-3.5" /></Button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
