import { Link } from "react-router-dom";
import { ArrowRight, FileSearch, MapPin, BellRing, FileCheck2, CreditCard, Trophy, Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/AppShell";

const STEPS = [
  [FileSearch, "Reads the rate con", "Drop the PDF. AI pulls free time, rate, cap and the notice rule, and quotes the clause word for word."],
  [Smartphone, "Texts the driver a link", "No app. The link geofences the dock and stamps in and out times, plus a photo of the signed BOL."],
  [BellRing, "Notifies the broker on time", "The notice goes out before free time runs out, the step most claims fail on. Every send is logged."],
  [FileCheck2, "Builds a sealed packet", "Timestamps, trail map, BOL, clause and notice log, sealed with an evidence fingerprint."],
  [CreditCard, "Collects until paid", "Brokers pay by card from the evidence page. Polite, firmer reminders on day 3, 7, 14 and 30."],
  [Trophy, "Scores who detains", "Facilities and brokers graded A to F so you can price up or refuse the loads that cost you."],
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-background">
      <header className="mx-auto flex max-w-[1200px] items-center justify-between px-6 py-5">
        <Logo />
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" data-testid="landing-sign-in-link"><Link to="/sign-in">Sign in</Link></Button>
          <Button asChild data-testid="landing-get-started-button"><Link to="/sign-up">Get started</Link></Button>
        </div>
      </header>
      <section className="hero-bg relative overflow-hidden">
        <div className="mx-auto grid max-w-[1200px] items-center gap-12 px-6 py-16 lg:grid-cols-[1.1fr_1fr] lg:py-24">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border bg-white px-3 py-1 text-xs font-medium text-teal-800">
              <span className="h-2 w-2 rounded-full bg-teal-600 pulse-dot" /> For carriers with 1–25 trucks
            </div>
            <h1 className="font-display text-4xl font-semibold leading-[1.05] tracking-tight sm:text-5xl lg:text-6xl">
              Collect the detention<br />you already earned.
            </h1>
            <p className="mt-6 max-w-xl text-base text-muted-foreground md:text-lg">
              Carriers invoice detention only 75% of the time, and brokers pay just 55% of those. DockClock reads each rate con,
              times the dock from the driver's phone, notifies the broker on time, and sends a packet they can't dispute.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg" data-testid="landing-hero-cta"><Link to="/sign-up">Start recovering detention <ArrowRight className="ml-2 h-4 w-4" /></Link></Button>
              <Button asChild size="lg" variant="outline"><Link to="/sign-in">I have an account</Link></Button>
            </div>
          </div>
          <div className="relative">
            <img src="https://images.pexels.com/photos/35501718/pexels-photo-35501718.jpeg?auto=compress&cs=tinysrgb&w=1200" alt="Aerial view of a logistics yard"
              className="h-[380px] w-full rounded-2xl object-cover card-shadow" />
            <div className="absolute -bottom-6 -left-4 w-[290px] rounded-xl border bg-white p-4 card-shadow sm:-left-8">
              <div className="flex items-center justify-between text-xs"><span className="font-semibold">Golden Valley DC</span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-800"><span className="h-1.5 w-1.5 rounded-full bg-emerald-600 pulse-dot" />Billable</span></div>
              <div className="mt-3 font-mono text-3xl font-semibold text-emerald-700">$87<span className="text-lg opacity-70">.50</span></div>
              <div className="mt-1 font-mono text-[11px] text-muted-foreground">On site 03:45:12 · $50/hr after 2h</div>
              <div className="mt-3 flex gap-[3px]">{Array.from({ length: 24 }).map((_, i) => <span key={i} className={`h-2.5 flex-1 rounded-[2px] ${i < 10 ? "bg-slate-300" : i < 18 ? "bg-emerald-400" : "bg-muted"}`} />)}</div>
            </div>
            <div className="absolute -right-2 -top-5 rounded-xl border bg-white px-4 py-3 card-shadow">
              <div className="flex items-center gap-2 text-xs font-medium text-teal-800"><MapPin className="h-3.5 w-3.5" />Arrival stamped by geofence</div>
              <div className="font-mono text-[11px] text-muted-foreground">8:02 AM · 41.8537, -87.6515</div>
            </div>
          </div>
        </div>
      </section>
      <section className="mx-auto max-w-[1200px] px-6 py-20">
        <h2 className="font-display text-2xl font-semibold tracking-tight md:text-3xl">From rate con to paid, without a back office.</h2>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map(([Icon, t, d], i) => (
            <div key={t} className="lift rounded-xl border bg-card p-6">
              <div className="flex items-center justify-between"><Icon className="h-5 w-5 text-teal-700" /><span className="font-mono text-xs text-muted-foreground">0{i + 1}</span></div>
              <h3 className="mt-4 font-semibold">{t}</h3>
              <p className="mt-2 text-sm text-muted-foreground">{d}</p>
            </div>
          ))}
        </div>
      </section>
      <section className="bg-slate-950 text-white">
        <div className="mx-auto flex max-w-[1200px] flex-col items-start justify-between gap-6 px-6 py-14 md:flex-row md:items-center">
          <div>
            <div className="font-mono text-sm text-teal-300">Monday, 7:00 AM</div>
            <p className="mt-2 max-w-2xl font-display text-xl md:text-2xl">“Last week you were detained 14 hours across 6 loads. $520 is billable under your rate cons. 3 invoices are ready to send.”</p>
          </div>
          <Button asChild size="lg" className="bg-teal-400 text-slate-950 hover:bg-teal-300"><Link to="/sign-up">Get your Monday number</Link></Button>
        </div>
      </section>
      <footer className="mx-auto max-w-[1200px] px-6 py-8 text-xs text-muted-foreground">© DockClock. Detention stats: ATRI 2023 via PrePass.</footer>
    </div>
  );
}
