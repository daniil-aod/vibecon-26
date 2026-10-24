import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi, errMsg } from "@/lib/api";
import { money, fmtTime } from "@/lib/format";
import { useFleet } from "@/lib/fleet";
import { StatusChip } from "@/components/StatusChip";
import { toast } from "sonner";

export default function Loads() {
  const api = useApi();
  const nav = useNavigate();
  const { fleet } = useFleet();
  const [loads, setLoads] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => { api.get("/loads").then((r) => setLoads(r.data)).catch((e) => toast.error(errMsg(e))); }, [api]);
  const rows = useMemo(() => (loads || []).filter((l) => !q || `${l.load_number} ${l.broker?.name} ${l.stops.map((s) => s.facility_name).join(" ")} ${l.driver?.name}`.toLowerCase().includes(q.toLowerCase())), [loads, q]);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="font-display text-2xl font-semibold tracking-tight">Loads</h1><p className="text-sm text-muted-foreground">Every rate con you've uploaded, with live detention.</p></div>
        <Button data-testid="loads-new-button" onClick={() => nav("/app/loads/new")}><Plus className="mr-2 h-4 w-4" />Upload rate con</Button>
      </div>
      <div className="relative max-w-sm"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input data-testid="loads-search-input" className="pl-9" placeholder="Search load, broker, facility, driver" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <div className="overflow-hidden rounded-xl border bg-card">
        {!loads ? <div className="p-4"><Skeleton className="h-40" /></div> : rows.length === 0 ? (
          <div data-testid="loads-empty" className="p-10 text-center text-sm text-muted-foreground">No loads yet. Upload a rate confirmation to create one.</div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Load</TableHead><TableHead>Broker</TableHead><TableHead>Stops</TableHead><TableHead>Driver</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Detention</TableHead><TableHead>Created</TableHead></TableRow></TableHeader>
              <TableBody>
                {rows.map((l) => (
                  <TableRow key={l.id} data-testid={`load-row-${l.id}`} className="cursor-pointer" onClick={() => nav(`/app/loads/${l.id}`)}>
                    <TableCell className="font-mono font-semibold"><Link to={`/app/loads/${l.id}`}>{l.load_number}</Link></TableCell>
                    <TableCell className="max-w-[200px] truncate">{l.broker?.name || "—"}</TableCell>
                    <TableCell className="max-w-[260px] truncate text-xs text-muted-foreground">{l.stops.map((s) => s.facility_name).join(" → ")}</TableCell>
                    <TableCell>{l.driver?.name || "—"}</TableCell>
                    <TableCell><StatusChip status={l.status} live={l.status === "on_site"} /></TableCell>
                    <TableCell className="num text-right font-mono">{money(l.detention_total)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtTime(l.created_at, fleet?.timezone)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
