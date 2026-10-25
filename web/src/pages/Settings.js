import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Mail, Trash2, MessageSquareText, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useApi, errMsg } from "@/lib/api";
import { useFleet } from "@/lib/fleet";
import { TIMEZONES, fmtTime } from "@/lib/format";

export default function Settings() {
  const api = useApi();
  const { fleet, user, refresh } = useFleet();
  const owner = user?.role === "owner";
  const [f, setF] = useState({ name: fleet.name, timezone: fleet.timezone, reply_to_email: fleet.reply_to_email || "", notice_mode: fleet.notice_mode || "auto" });
  const [team, setTeam] = useState({ members: [], invites: [] });
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState("");
  const loadTeam = () => api.get("/fleet/team").then((r) => setTeam(r.data)).catch(() => {});
  useEffect(() => { loadTeam(); }, []); // eslint-disable-line

  const save = async () => { setBusy("save"); try { await api.patch("/fleet", f); await refresh(); toast.success("Settings saved"); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); } };
  const invite = async (e) => { e.preventDefault(); setBusy("inv"); try { const { data } = await api.post("/fleet/invites", { email }); toast.success(data.email_sent ? "Invitation emailed" : "Invite saved. They can join by signing up with that email."); setEmail(""); loadTeam(); } catch (e2) { toast.error(errMsg(e2)); } finally { setBusy(""); } };
  const revoke = async (id) => { try { await api.delete(`/fleet/invites/${id}`); loadTeam(); } catch (e) { toast.error(errMsg(e)); } };
  const summary = async () => { setBusy("sum"); try { await api.post("/summary/send-now"); toast.success("Summary emailed to the owner"); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); } };

  return (
    <div className="max-w-3xl space-y-6">
      <div><h1 className="font-display text-2xl font-semibold tracking-tight">Settings</h1><p className="text-sm text-muted-foreground">{owner ? "Fleet details, notices and team." : "Only the fleet owner can change these settings."}</p></div>

      <section className="rounded-2xl border bg-card p-6 card-shadow">
        <h2 className="font-semibold">Fleet</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div><Label>Company name</Label><Input data-testid="settings-fleet-name-input" disabled={!owner} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div><Label>Time zone</Label><Select disabled={!owner} value={f.timezone} onValueChange={(v) => setF({ ...f, timezone: v })}><SelectTrigger data-testid="settings-timezone-select"><SelectValue /></SelectTrigger>
            <SelectContent>{TIMEZONES.map((t) => <SelectItem key={t} value={t}>{t.replace("_", " ")}</SelectItem>)}</SelectContent></Select></div>
          <div className="sm:col-span-2"><Label>Reply-to email</Label><Input data-testid="settings-reply-to-input" disabled={!owner} type="email" value={f.reply_to_email} onChange={(e) => setF({ ...f, reply_to_email: e.target.value })} /></div>
        </div>
        <div className="mt-6">
          <Label>Broker notices</Label>
          <RadioGroup disabled={!owner} value={f.notice_mode} onValueChange={(v) => setF({ ...f, notice_mode: v })} className="mt-3 grid gap-3 sm:grid-cols-2">
            {[["auto", "Send automatically", "DockClock emails the broker the moment the rate con rule requires it."], ["ask", "Ask me first", "You approve each notice on the dashboard before it goes out."]].map(([v, t, d]) => (
              <label key={v} className={`flex cursor-pointer gap-3 rounded-xl border p-4 ${f.notice_mode === v ? "border-teal-600 bg-teal-50" : ""}`}>
                <RadioGroupItem data-testid={`settings-notice-mode-${v}`} value={v} className="mt-0.5" /><div><div className="text-sm font-medium">{t}</div><div className="text-xs text-muted-foreground">{d}</div></div>
              </label>))}
          </RadioGroup>
        </div>
        {owner && <div className="mt-6 flex justify-end"><Button data-testid="settings-save-button" onClick={save} disabled={busy === "save"}>Save settings</Button></div>}
      </section>

      <section className="rounded-2xl border bg-card p-6 card-shadow">
        <h2 className="font-semibold">Team</h2>
        <div className="mt-4 divide-y rounded-xl border">
          {team.members.map((m) => <div key={m.user_id} className="flex items-center justify-between p-3 text-sm"><span>{m.name} <span className="text-muted-foreground">{m.email}</span></span><span className="text-xs capitalize text-muted-foreground">{m.role}</span></div>)}
          {team.invites.map((i) => <div key={i.id} data-testid={`settings-invite-${i.id}`} className="flex items-center justify-between p-3 text-sm"><span className="flex items-center gap-2"><Mail className="h-4 w-4 text-muted-foreground" />{i.email}<span className="text-xs text-amber-700">invited</span></span>
            {owner && <Button size="icon" variant="ghost" onClick={() => revoke(i.id)}><Trash2 className="h-4 w-4" /></Button>}</div>)}
        </div>
        {owner && <form onSubmit={invite} className="mt-4 flex gap-2"><Input data-testid="settings-invite-email-input" type="email" required placeholder="dispatcher@yourfleet.com" value={email} onChange={(e) => setEmail(e.target.value)} /><Button data-testid="settings-invite-button" disabled={busy === "inv"}>Invite dispatcher</Button></form>}
      </section>

      <section className="rounded-2xl border bg-card p-6 card-shadow">
        <h2 className="font-semibold">Connections</h2>
        <div className="mt-4 space-y-3 text-sm">
          <div data-testid="settings-sms-status" className="flex items-start gap-3 rounded-xl border p-4">
            <MessageSquareText className="mt-0.5 h-4 w-4" />
            <div className="flex-1"><div className="font-medium">Driver emails</div><div className="text-xs text-muted-foreground">Driver app links and dock-time recaps are emailed from DockClock — send them now or on a schedule from each load.</div></div>
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
          </div>
          <div className="flex items-start gap-3 rounded-xl border p-4"><Mail className="mt-0.5 h-4 w-4" /><div className="flex-1"><div className="font-medium">Monday summary email</div>
            <div className="text-xs text-muted-foreground">Sent to the owner every Monday at 7am {fleet.timezone}. {fleet.weekly_sent_at ? `Last sent ${fmtTime(fleet.weekly_sent_at, fleet.timezone)}.` : ""}</div></div>
            {owner && <Button data-testid="settings-send-summary-button" size="sm" variant="outline" onClick={summary} disabled={busy === "sum"}>Send now</Button>}</div>
        </div>
      </section>
    </div>
  );
}
