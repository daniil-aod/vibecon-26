import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Show, SignIn, SignUp } from "@clerk/react";
import { Toaster } from "@/components/ui/sonner";
import ClerkAuthProvider from "@/components/auth/ClerkAuthProvider";
import { FleetProvider, useFleet } from "@/lib/fleet";
import AppShell, { Logo } from "@/components/AppShell";
import Landing from "@/pages/Landing";
import Onboarding from "@/pages/Onboarding";
import Dashboard from "@/pages/Dashboard";
import Loads from "@/pages/Loads";
import NewLoad from "@/pages/NewLoad";
import LoadDetail from "@/pages/LoadDetail";
import Invoices from "@/pages/Invoices";
import Scorecard from "@/pages/Scorecard";
import Settings from "@/pages/Settings";
import Driver from "@/pages/Driver";
import Evidence from "@/pages/Evidence";
import PaymentSuccess from "@/pages/PaymentSuccess";

function Loading() {
  return <div data-testid="app-loading" className="grid min-h-screen place-items-center text-sm text-muted-foreground">Loading DockClock…</div>;
}

function FleetGate() {
  const { loading, fleet, error } = useFleet();
  if (loading) return <Loading />;
  if (error && !fleet) return <div className="p-8 text-sm">Could not load your account. Refresh to try again.</div>;
  if (!fleet) return <Onboarding />;
  return <AppShell />;
}

function Protected() {
  return (
    <>
      <Show when="signed-in"><FleetProvider><FleetGate /></FleetProvider></Show>
      <Show when="signed-out"><Navigate to="/sign-in" replace /></Show>
    </>
  );
}

function Home() {
  return (
    <>
      <Show when="signed-in"><Navigate to="/app" replace /></Show>
      <Show when="signed-out"><Landing /></Show>
    </>
  );
}

function AuthPage({ children }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-slate-950 p-10 text-white lg:flex noise">
        <Logo dark />
        <div className="relative">
          <h2 className="font-display text-4xl font-semibold leading-tight">Every minute at the dock<br />becomes evidence.</h2>
          <p className="mt-4 max-w-md text-slate-400">Rate con terms, geofenced timestamps, on-time broker notice and a sealed invoice packet, all from a texted link.</p>
        </div>
        <div className="relative font-mono text-xs text-slate-500">Detention at 39.3% of stops · ATRI 2023</div>
      </div>
      <div className="flex items-center justify-center p-6">{children}</div>
    </div>
  );
}

export default function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <ClerkAuthProvider>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/sign-in/*" element={<AuthPage><SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" withSignUp /></AuthPage>} />
            <Route path="/sign-up/*" element={<AuthPage><SignUp routing="path" path="/sign-up" signInUrl="/sign-in" /></AuthPage>} />
            <Route path="/d/:token" element={<Driver />} />
            <Route path="/e/:token" element={<Evidence />} />
            <Route path="/payment/success" element={<PaymentSuccess />} />
            <Route path="/app" element={<Protected />}>
              <Route index element={<Dashboard />} />
              <Route path="loads" element={<Loads />} />
              <Route path="loads/new" element={<NewLoad />} />
              <Route path="loads/:id" element={<LoadDetail />} />
              <Route path="invoices" element={<Invoices />} />
              <Route path="scorecard" element={<Scorecard />} />
              <Route path="settings" element={<Settings />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ClerkAuthProvider>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </div>
  );
}
