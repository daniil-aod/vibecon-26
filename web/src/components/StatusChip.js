import { cn } from "@/lib/utils";

const P = {
  on_site: ["bg-sky-50 text-sky-800", "bg-sky-500", "On site"],
  billable: ["bg-emerald-50 text-emerald-800", "bg-emerald-600", "Billable"],
  notice_sent: ["bg-teal-50 text-teal-800", "bg-teal-600", "Notice sent"],
  invoiced: ["bg-amber-50 text-amber-800", "bg-amber-500", "Invoiced"],
  sent: ["bg-amber-50 text-amber-800", "bg-amber-500", "Sent"],
  ready: ["bg-indigo-50 text-indigo-800", "bg-indigo-500", "Ready to send"],
  paid: ["bg-emerald-50 text-emerald-800", "bg-emerald-600", "Paid"],
  disputed: ["bg-red-50 text-red-800", "bg-red-500", "Disputed"],
  written_off: ["bg-slate-100 text-slate-700", "bg-slate-400", "Written off"],
  planned: ["bg-slate-100 text-slate-700", "bg-slate-400", "Planned"],
  dispatched: ["bg-blue-50 text-blue-800", "bg-blue-500", "Driver texted"],
  in_transit: ["bg-blue-50 text-blue-800", "bg-blue-500", "In transit"],
  completed: ["bg-slate-100 text-slate-700", "bg-slate-500", "Completed"],
  awaiting_approval: ["bg-amber-50 text-amber-800", "bg-amber-500", "Approve notice"],
  pending: ["bg-slate-100 text-slate-700", "bg-slate-400", "Notice scheduled"],
  missed: ["bg-red-50 text-red-800", "bg-red-500", "Notice missed"],
  failed: ["bg-red-50 text-red-800", "bg-red-500", "Notice failed"],
  no_email: ["bg-red-50 text-red-800", "bg-red-500", "No broker email"],
  not_needed: ["bg-slate-100 text-slate-700", "bg-slate-400", "No notice needed"],
};

export const StatusChip = ({ status, label, live = false, className, testid }) => {
  const [cls, dot, text] = P[status] || P.planned;
  return (
    <span data-testid={testid || `status-chip-${status}`}
      className={cn("inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium whitespace-nowrap", cls, className)}>
      <span className={cn("h-2 w-2 rounded-full", dot, live && "pulse-dot")} />
      {label || text}
    </span>
  );
};

const G = {
  A: "bg-emerald-50 text-emerald-800 border-emerald-300",
  B: "bg-teal-50 text-teal-800 border-teal-300",
  C: "bg-sky-50 text-sky-800 border-sky-300",
  D: "bg-amber-50 text-amber-800 border-amber-300",
  F: "bg-red-50 text-red-800 border-red-300",
};

export const GradeBadge = ({ grade, size = "md", testid }) => (
  <span data-testid={testid || "grade-badge"}
    className={cn("inline-flex items-center justify-center rounded-md border font-mono font-semibold",
      size === "lg" ? "h-10 w-10 text-lg" : "h-7 w-7 text-sm", G[grade] || G.C)}>
    {grade}
  </span>
);
