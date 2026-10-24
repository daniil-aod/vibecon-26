import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { UploadCloud, FileText, Sparkles, PencilLine, Loader2, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApi, errMsg } from "@/lib/api";
import LoadForm, { emptyLoad, fromExtracted } from "@/pages/LoadForm";
import { cn } from "@/lib/utils";

const STAGES = ["Uploading rate con", "Reading the document", "Finding detention terms", "Quoting the clause word for word"];

export default function NewLoad() {
  const api = useApi();
  const nav = useNavigate();
  const input = useRef();
  const [phase, setPhase] = useState("drop"); // drop | extracting | review
  const [stage, setStage] = useState(0);
  const [drag, setDrag] = useState(false);
  const [file, setFile] = useState(null);
  const [form, setForm] = useState(emptyLoad());
  const [meta, setMeta] = useState(null);
  const [saving, setSaving] = useState(false);

  const upload = async (f) => {
    if (!f) return;
    setFile(f);
    setPhase("extracting");
    setStage(0);
    const timer = setInterval(() => setStage((s) => Math.min(STAGES.length - 1, s + 1)), 6000);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const { data } = await api.post("/ratecons/extract", fd, { timeout: 180000 });
      setForm(fromExtracted(data.extracted));
      setMeta({ file_id: data.file_id, model: data.extracted._model, flagged: (data.extracted.low_confidence || []).length });
      setPhase("review");
      toast.success("Terms extracted. Review them before saving.");
    } catch (e) {
      toast.error(errMsg(e));
      setPhase("drop");
    } finally { clearInterval(timer); }
  };

  const save = async () => {
    if (!form.detention.hourly_rate && form.detention.hourly_rate !== 0) return toast.error("Add the detention hourly rate");
    if (form.stops.some((s) => !s.address)) return toast.error("Every stop needs an address for the geofence");
    setSaving(true);
    try {
      const { data } = await api.post("/loads", { ...form, file_id: meta?.file_id || null });
      toast.success(`Load ${data.load_number} created`);
      const missing = data.stops.filter((s) => s.lat == null).length;
      if (missing) toast.warning(`${missing} stop address could not be located on the map. Set the pin on the load page.`);
      nav(`/app/loads/${data.id}`);
    } catch (e) { toast.error(errMsg(e)); } finally { setSaving(false); }
  };

  return (
    <div className="space-y-6">
      <div><h1 className="font-display text-2xl font-semibold tracking-tight">New load</h1>
        <p className="text-sm text-muted-foreground">Upload the rate confirmation and DockClock reads the detention terms for you.</p></div>

      {phase === "drop" && (
        <>
          <div data-testid="load-new-pdf-dropzone" role="button" tabIndex={0}
            onClick={() => input.current?.click()} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files?.[0]); }}
            className={cn("grid cursor-pointer place-items-center rounded-2xl border-2 border-dashed bg-card px-6 py-16 text-center transition-colors",
              drag ? "border-teal-500 bg-teal-50" : "border-slate-300 hover:border-slate-400")}>
            <UploadCloud className="h-10 w-10 text-teal-700" />
            <div className="mt-4 font-display text-lg font-semibold">Drop the rate con PDF here</div>
            <div className="mt-1 text-sm text-muted-foreground">or click to choose a file · PDF or photo, up to 15 MB</div>
            <input ref={input} data-testid="load-new-file-input" type="file" accept="application/pdf,image/*" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
          </div>
          <div className="text-center"><Button data-testid="load-new-manual-button" variant="ghost" onClick={() => { setForm(emptyLoad()); setMeta(null); setPhase("review"); }}><PencilLine className="mr-2 h-4 w-4" />Enter terms by hand</Button></div>
        </>
      )}

      {phase === "extracting" && (
        <div data-testid="load-new-extracting" className="relative overflow-hidden rounded-2xl border bg-card p-10">
          <div className="flex items-center gap-3"><FileText className="h-6 w-6 text-slate-700" /><span className="font-mono text-sm">{file?.name}</span></div>
          <div className="mt-8 space-y-3">
            {STAGES.map((s, i) => (
              <div key={s} className={cn("flex items-center gap-3 text-sm transition-opacity", i > stage && "opacity-35")}>
                {i < stage ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : i === stage ? <Loader2 className="h-4 w-4 animate-spin text-teal-700" /> : <span className="h-4 w-4 rounded-full border" />}
                {s}
              </div>
            ))}
          </div>
          <div className="mt-8 space-y-2" aria-hidden>{[90, 72, 84, 60].map((w, i) => <div key={i} className="h-2.5 animate-pulse rounded bg-slate-100" style={{ width: `${w}%` }} />)}</div>
          <p className="mt-6 text-xs text-muted-foreground">This usually takes 20–40 seconds.</p>
        </div>
      )}

      {phase === "review" && (
        <div className="rounded-2xl border bg-card p-5 md:p-8 card-shadow">
          {meta ? (
            <div data-testid="load-new-review-banner" className="mb-6 flex flex-wrap items-center gap-3 rounded-xl bg-teal-50 p-4 text-sm text-teal-900">
              <Sparkles className="h-4 w-4" />AI read <span className="font-mono">{file?.name}</span>.
              {meta.flagged ? <span className="font-medium text-amber-800">{meta.flagged} field{meta.flagged > 1 ? "s" : ""} flagged for review.</span> : <span>Nothing flagged, but give it a look.</span>}
            </div>
          ) : <div className="mb-6 text-sm text-muted-foreground">Enter the terms from the rate con.</div>}
          <LoadForm value={form} onChange={setForm} />
          <div className="mt-8 flex flex-wrap justify-end gap-3 border-t pt-6">
            <Button variant="outline" onClick={() => setPhase("drop")}>Start over</Button>
            <Button data-testid="load-new-save-button" onClick={save} disabled={saving}>{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}Save load</Button>
          </div>
        </div>
      )}
    </div>
  );
}
