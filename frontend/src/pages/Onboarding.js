import { useState } from "react";
import { toast } from "sonner";
import { useUser } from "@clerk/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Logo } from "@/components/AppShell";
import { useApi, errMsg } from "@/lib/api";
import { useFleet } from "@/lib/fleet";
import { TIMEZONES } from "@/lib/format";

export default function Onboarding() {
  const api = useApi();
  const { refresh, user } = useFleet();
  const { user: cu } = useUser();
  const guessTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [f, setF] = useState({ name: "", timezone: TIMEZONES.includes(guessTz) ? guessTz : "America/Chicago",
    reply_to_email: user?.email || cu?.primaryEmailAddress?.emailAddress || "", notice_mode: "auto" });
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/fleet", { ...f, origin: window.location.origin });
      toast.success("Fleet created");
      await refresh();
    } catch (e2) { toast.error(errMsg(e2)); } finally { setBusy(false); }
  };
  return (
    <div className="hero-bg grid min-h-screen place-items-center p-6">
      <form onSubmit={submit} className="w-full max-w-lg rounded-2xl border bg-white p-8 card-shadow" data-testid="onboarding-form">
        <Logo />
        <h1 className="mt-6 font-display text-2xl font-semibold">Set up your fleet</h1>
        <p className="mt-1 text-sm text-muted-foreground">You'll be the owner. You can invite dispatchers after this.</p>
        <div className="mt-6 space-y-4">
          <div><Label>Company name</Label><Input data-testid="onboarding-fleet-name-input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Ridgeline Haulers Inc" /></div>
          <div><Label>Time zone</Label>
            <Select value={f.timezone} onValueChange={(v) => setF({ ...f, timezone: v })}>
              <SelectTrigger data-testid="onboarding-timezone-select"><SelectValue /></SelectTrigger>
              <SelectContent>{TIMEZONES.map((t) => <SelectItem key={t} value={t}>{t.replace("_", " ")}</SelectItem>)}</SelectContent>
            </Select></div>
          <div><Label>Reply-to email</Label><Input data-testid="onboarding-reply-to-input" type="email" required value={f.reply_to_email} onChange={(e) => setF({ ...f, reply_to_email: e.target.value })} />
            <p className="mt-1 text-xs text-muted-foreground">Brokers' replies to notices and invoices land here. You also get a copy of each notice.</p></div>
        </div>
        <Button data-testid="onboarding-submit-button" className="mt-8 w-full" disabled={busy}>{busy ? "Creating…" : "Create fleet"}</Button>
      </form>
    </div>
  );
}
