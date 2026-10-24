import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { UserButton } from "@clerk/react";
import { LayoutDashboard, Truck, FileText, Trophy, Settings, Plus, Clock3, Menu } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { useFleet } from "@/lib/fleet";
import { cn } from "@/lib/utils";

const NAV = [
  ["/app", "Dashboard", LayoutDashboard, "dashboard"],
  ["/app/loads", "Loads", Truck, "loads"],
  ["/app/invoices", "Invoices", FileText, "invoices"],
  ["/app/scorecard", "Scorecard", Trophy, "scorecard"],
  ["/app/settings", "Settings", Settings, "settings"],
];

export const Logo = ({ dark = false }) => (
  <div className="flex items-center gap-2.5">
    <div className={cn("grid h-8 w-8 place-items-center rounded-lg", dark ? "bg-teal-400 text-slate-950" : "bg-slate-900 text-teal-300")}>
      <Clock3 className="h-4.5 w-4.5" strokeWidth={2.5} />
    </div>
    <span className={cn("font-display text-lg font-semibold tracking-tight", dark ? "text-white" : "text-slate-900")}>DockClock</span>
  </div>
);

function NavItems({ onNav }) {
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map(([to, label, Icon, id]) => (
        <NavLink key={to} to={to} end={to === "/app"} onClick={onNav} data-testid={`nav-${id}`}
          className={({ isActive }) => cn("flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
            isActive ? "bg-[hsl(var(--shell-muted))] text-white" : "text-slate-400 hover:bg-[hsl(var(--shell-muted))] hover:text-white")}>
          <Icon className="h-4 w-4" />{label}
        </NavLink>
      ))}
    </nav>
  );
}

export default function AppShell() {
  const { fleet, user } = useFleet();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const side = (
    <div className="flex h-full flex-col gap-6 bg-[hsl(var(--shell))] p-4">
      <div className="px-2 pt-1"><Logo dark /></div>
      <Button data-testid="sidebar-new-load-button" onClick={() => { setOpen(false); nav("/app/loads/new"); }}
        className="justify-start bg-teal-500 text-slate-950 hover:bg-teal-400"><Plus className="mr-2 h-4 w-4" />Upload rate con</Button>
      <NavItems onNav={() => setOpen(false)} />
      <div className="mt-auto rounded-lg border border-[hsl(var(--shell-border))] p-3">
        <div className="text-[11px] uppercase tracking-wider text-slate-500">Fleet</div>
        <div data-testid="sidebar-fleet-name" className="truncate text-sm font-medium text-white">{fleet?.name}</div>
        <div className="text-xs capitalize text-slate-400">{user?.role}</div>
      </div>
    </div>
  );
  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] lg:block">{side}</aside>
      <div className="lg:pl-[248px]">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-white px-4 sm:px-6">
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button data-testid="mobile-menu-button" variant="ghost" size="icon" className="lg:hidden"><Menu className="h-5 w-5" /></Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-[260px] border-0 p-0">{side}</SheetContent>
          </Sheet>
          <div className="lg:hidden"><Logo /></div>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-sm text-muted-foreground sm:block">{user?.email}</span>
            <UserButton />
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8"><Outlet /></main>
      </div>
    </div>
  );
}
