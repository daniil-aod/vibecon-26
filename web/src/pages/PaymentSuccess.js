import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { publicApi } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function PaymentSuccess() {
  const [sp] = useSearchParams();
  const sid = sp.get("session_id");
  const tok = sp.get("t");
  const [state, setState] = useState("checking");
  useEffect(() => {
    let n = 0, off = false;
    const poll = async () => {
      if (off) return;
      try {
        const { data } = await publicApi.get(`/payments/status/${sid}`);
        if (data.payment_status === "paid") return setState("paid");
        if (["expired", "failed"].includes(data.payment_status)) return setState("failed");
      } catch {}
      if (++n >= 12) return setState("timeout");
      setTimeout(poll, 2000);
    };
    if (sid) poll(); else setState("failed");
    return () => { off = true; };
  }, [sid]);
  return (
    <div className="grid min-h-screen place-items-center bg-slate-100 p-6">
      <div data-testid="payment-status-card" className="w-full max-w-md rounded-2xl border bg-white p-8 text-center card-shadow">
        {state === "checking" && <><Loader2 className="mx-auto h-10 w-10 animate-spin text-slate-600" /><h1 className="mt-4 font-display text-xl font-semibold">Confirming payment…</h1></>}
        {state === "paid" && <><CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" /><h1 data-testid="payment-success-title" className="mt-4 font-display text-2xl font-semibold">Payment received</h1><p className="mt-2 text-sm text-muted-foreground">Thank you. The carrier has been notified and the invoice is marked paid.</p></>}
        {state === "failed" && <><XCircle className="mx-auto h-12 w-12 text-red-600" /><h1 className="mt-4 font-display text-xl font-semibold">Payment not completed</h1></>}
        {state === "timeout" && <><Loader2 className="mx-auto h-10 w-10 text-slate-400" /><h1 className="mt-4 font-display text-xl font-semibold">Still processing</h1><p className="mt-2 text-sm text-muted-foreground">Your card was submitted. The invoice updates as soon as the payment clears.</p></>}
        {tok && <Button asChild variant="outline" className="mt-6"><Link data-testid="payment-back-to-evidence" to={`/e/${tok}`}>Back to invoice</Link></Button>}
      </div>
    </div>
  );
}
