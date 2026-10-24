import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Info } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useApi, errMsg } from "@/lib/api";
import { money } from "@/lib/format";
import { GradeBadge } from "@/components/StatusChip";

const pct = (v) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);
const ADV = { "Refuse or price up": "text-red-700 bg-red-50", "Price up": "text-amber-800 bg-amber-50", Watch: "text-sky-800 bg-sky-50", "Good to book": "text-emerald-800 bg-emerald-50" };

function Grid({ rows, kind }) {
  if (!rows.length) return <div data-testid={`scorecard-${kind}-empty`} className="rounded-xl border bg-card p-10 text-center text-sm text-muted-foreground">No completed stops yet. Grades appear after trucks check in and out.</div>;
  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <Table>
        <TableHeader><TableRow>
          <TableHead className="w-14">Grade</TableHead><TableHead>{kind === "facilities" ? "Facility" : "Broker"}</TableHead><TableHead className="text-right">Stops</TableHead>
          <TableHead className="text-right">Detained</TableHead><TableHead className="text-right">Avg dwell</TableHead><TableHead className="text-right">Billed</TableHead>
          <TableHead className="text-right">Paid</TableHead><TableHead className="text-right">Pay rate</TableHead><TableHead className="text-right">Days to pay</TableHead><TableHead>Advice</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id} data-testid={`scorecard-row-${r.id}`}>
              <TableCell><GradeBadge grade={r.grade} testid={`grade-${r.id}`} /></TableCell>
              <TableCell className="max-w-[240px] truncate font-medium">{r.name}</TableCell>
              <TableCell className="num text-right font-mono">{r.stops}</TableCell>
              <TableCell className="num text-right font-mono">{pct(r.detention_rate)}</TableCell>
              <TableCell className="num text-right font-mono">{r.avg_dwell_hours.toFixed(1)} h</TableCell>
              <TableCell className="num text-right font-mono">{money(r.billed, 0)}</TableCell>
              <TableCell className="num text-right font-mono">{money(r.paid, 0)}</TableCell>
              <TableCell className="num text-right font-mono">{pct(r.pay_rate)}</TableCell>
              <TableCell className="num text-right font-mono">{r.days_to_pay ?? "—"}</TableCell>
              <TableCell><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${ADV[r.advice]}`}>{r.advice}</span></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function Scorecard() {
  const api = useApi();
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/scorecard").then((r) => setD(r.data)).catch((e) => toast.error(errMsg(e))); }, [api]);
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div><h1 className="font-display text-2xl font-semibold tracking-tight">Scorecard</h1>
          <p className="text-sm text-muted-foreground">Who holds your trucks, and who pays for it. Worst first.</p></div>
        <TooltipProvider><Tooltip><TooltipTrigger className="flex items-center gap-1 text-xs text-muted-foreground"><Info className="h-3.5 w-3.5" />How grades work</TooltipTrigger>
          <TooltipContent className="max-w-xs text-xs">Facilities: graded on how often they detain you and how long past free time. Brokers: also on the share of detention invoices they pay and how fast. A = good to book, F = refuse or price up.</TooltipContent></Tooltip></TooltipProvider>
      </div>
      {!d ? <Skeleton className="h-64" /> : (
        <Tabs defaultValue="facilities">
          <TabsList><TabsTrigger data-testid="scorecard-tab-facilities" value="facilities">Facilities ({d.facilities.length})</TabsTrigger><TabsTrigger data-testid="scorecard-tab-brokers" value="brokers">Brokers ({d.brokers.length})</TabsTrigger></TabsList>
          <TabsContent value="facilities" className="mt-4"><Grid rows={d.facilities} kind="facilities" /></TabsContent>
          <TabsContent value="brokers" className="mt-4"><Grid rows={d.brokers} kind="brokers" /></TabsContent>
        </Tabs>
      )}
    </div>
  );
}
