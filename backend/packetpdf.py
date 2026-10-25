"""Detention Billing Packet PDF, rendered ONLY from an immutable snapshot (never from live load data)."""
import io
from xml.sax.saxutils import escape as _esc
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image,
                                KeepTogether, CondPageBreak)
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing

INK, MUTED, LINE, SOFT, ACCENT, WARN = (colors.HexColor("#0f172a"), colors.HexColor("#64748b"), colors.HexColor("#cbd5e1"),
                                        colors.HexColor("#f1f5f9"), colors.HexColor("#0f766e"), colors.HexColor("#92400e"))
S = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=INK, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=INK, spaceBefore=10, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=INK, spaceBefore=6, spaceAfter=3),
    "p": ParagraphStyle("p", fontName="Helvetica", fontSize=9, leading=12, textColor=INK),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=INK),
    "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.white),
    "mono": ParagraphStyle("mono", fontName="Courier", fontSize=7, leading=9, textColor=INK),
    "clause": ParagraphStyle("clause", fontName="Helvetica-Oblique", fontSize=8, leading=11, textColor=INK, leftIndent=6,
                             rightIndent=6, borderPadding=(5, 4, 5, 4), backColor=SOFT, spaceBefore=7, spaceAfter=4),
    "warn": ParagraphStyle("warn", fontName="Helvetica", fontSize=8.5, leading=11, textColor=WARN),
}
SRC = {"geofence": "GPS geofence", "driver_tap": "Driver tap", "dispatcher_edit": "Dispatcher adjustment",
       "dispatcher_manual_completion": "Dispatcher manual completion", None: "Not recorded"}


def P(text, style="cell"):
    return Paragraph(_esc(str(text if text not in (None, "") else "-")).replace("\n", "<br/>"), S[style])


def _money(v):
    return f"${float(v or 0):,.2f}"


def _table(rows, widths, header=True, zebra=True):
    data = [[c if not isinstance(c, (str, int, float)) and c is not None else P(c, "head" if header and i == 0 else "cell")
             for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), INK))
    if zebra:
        for i in range(1 if header else 0, len(data)):
            if i % 2 == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), SOFT))
    t.setStyle(TableStyle(st))
    return t


def _kv(rows, w=(1.7 * inch, 5.3 * inch)):
    return _table([[P(k, "cellb"), P(v)] for k, v in rows], w, header=False, zebra=False)


class _NumberedCanvas(rl_canvas.Canvas):
    """Adds 'Page X of Y' and the packet id footer on every page."""
    footer = ""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._pages)
        for st in self._pages:
            self.__dict__.update(st)
            self.setFont("Helvetica", 7)
            self.setFillColor(MUTED)
            self.drawString(0.75 * inch, 0.45 * inch, self.footer[:150])
            self.drawRightString(7.75 * inch, 0.45 * inch, f"Page {self._pageNumber} of {n}")
            super().showPage()
        super().save()


def _qr(url, size=1.0 * inch):
    w = QrCodeWidget(url)
    b = w.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
    d.add(w)
    return d


def build_billing_packet(snap: dict, images: dict, fmt) -> bytes:
    """snap: packet snapshot. images: {file_id: bytes}. fmt(iso) -> local time string."""
    buf = io.BytesIO()
    ld, car, pay, tot = snap["load"], snap["carrier"], snap["payor"], snap["totals"]
    status = snap.get("status")
    title = f"Detention Billing Packet \u2014 Load {ld.get('number') or ''}"
    footer = (f"{title} | Packet {snap['packet_id'][:8].upper()} v{snap['version']} | "
              f"{'ISSUED ' + fmt(snap.get('issued_at')) if status == 'issued' else 'DRAFT - not issued'}")
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.75 * inch, title=title, author=car.get("legal_name") or "")
    W = 7.0 * inch
    el = [P(title, "h1"),
          P("Supplemental detention billing for accessorial charges. This packet does not re-bill linehaul, "
            "and it is not a contract termination, release, settlement or waiver.", "small"), Spacer(1, 6)]
    if status != "issued":
        el.append(P("DRAFT - for review. Not yet issued or submitted.", "warn"))

    # ---- A. Cover summary
    el.append(P("A. Cover summary", "h2"))
    ids = ", ".join(x for x in [f"MC {car['mc_number']}" if car.get("mc_number") else "",
                                f"USDOT {car['usdot_number']}" if car.get("usdot_number") else ""] if x) or "Not supplied"
    el.append(_table([
        ["Carrier", "Bill to (payor)"],
        [P("\n".join(x for x in [car.get("legal_name") or "Carrier legal name not supplied", car.get("address") or "",
                                 car.get("phone") or "", car.get("billing_email") or "", ids] if x)),
         P("\n".join(x for x in [pay.get("company") or "Payor not confirmed", pay.get("address") or "Billing address not supplied",
                                 pay.get("recipient") or ""] if x))]], [W / 2, W / 2]))
    el.append(Spacer(1, 6))
    refs = ld.get("refs") or {}
    el.append(_kv([
        ("Load number", ld.get("number")), ("BOL / PRO / PO", " / ".join(refs.get(k) or "-" for k in ("bol_number", "pro_number", "po_number"))),
        ("Shipment date", ld.get("shipment_date") or "Not supplied"), ("Origin", ld.get("origin")), ("Destination", ld.get("destination")),
        ("Load completed", f"{fmt(ld.get('completed_at'))} ({SRC.get(ld.get('completion_source'), ld.get('completion_source'))})"),
        ("Packet", f"ID {snap['packet_id']} - version {snap['version']}" + (f" (revises v{snap['supersedes_version']})" if snap.get("supersedes_version") else "")),
        ("Issue date", fmt(snap.get("issued_at")) if status == "issued" else "Draft (not issued)"),
        ("Currency / timezone", f"{snap.get('currency', 'USD')} / {ld.get('timezone')}"),
        ("Evidence cutoff", fmt(snap.get("evidence_cutoff"))),
    ]))
    el.append(P("Included invoices", "h3"))
    rows = [["Invoice", "Stop", "Facility", "Status", "Invoiced", "Paid / credits", "Outstanding"]]
    for i in snap["invoices"]:
        rows.append([i["number"], i["stop_label"], i["facility"],
                     i["status_label"], _money(i["amount"]), _money(i["paid"]), _money(i["outstanding"])])
    rows.append([P("Total", "cellb"), "", "", "", P(_money(tot["invoiced"]), "cellb"), P(_money(tot["paid"]), "cellb"),
                 P(_money(tot["outstanding"]), "cellb")])
    el.append(_table(rows, [0.8 * inch, 0.8 * inch, 1.6 * inch, 1.2 * inch, 0.85 * inch, 0.9 * inch, 0.85 * inch]))
    if not snap["invoices"]:
        el.append(P("No detention was billable on this load. This is a completion summary only.", "p"))

    # ---- B. Detention invoices
    el.append(PageBreak())
    el.append(P("B. Detention invoice section (supplemental detention billing)", "h2"))
    for s in snap["stops"]:
        b = s["billing"]
        block = [P(f"Stop {s['seq'] + 1} - {s['type'].title()} - {s.get('facility') or ''}", "h3"),
                 P(s.get("address") or "", "small")]
        inv = next((i for i in snap["invoices"] if i["stop_id"] == s["id"]), None)
        block.append(_table([
            ["Item", "Value"],
            ["Invoice", f"{inv['number']} ({inv['status_label']})" if inv else "No detention invoice for this stop"],
            ["Appointment", s.get("appointment_label") or "Not recorded"],
            ["Arrival", f"{fmt(s.get('arrived_at'))} - {SRC.get(s.get('arrived_source'), s.get('arrived_source'))}"],
            ["Departure", f"{fmt(s.get('departed_at'))} - {SRC.get(s.get('departed_source'), s.get('departed_source'))}"],
            ["Billing starts", f"{fmt(b.get('billing_start_at'))} ({(b.get('billing_start_rule') or 'arrival').replace('_', ' ')})"],
            ["Elapsed on site", s.get("dwell_label")],
            ["Free time", s.get("free_label")],
            ["Billable / billed", f"{s.get('billable_label')} / {s.get('billed_label')}"],
            ["Rate", _money(b["rate"]) + "/h" if b.get("rate") is not None else "Unknown"],
            ["Cap adjustment", _money(b.get("cap_adjustment")) if b.get("capped") else "None"],
            ["Line total", _money(b.get("amount"))],
        ], [1.7 * inch, 5.3 * inch]))
        if b.get("calc"):
            block.append(P("Calculation: " + " | ".join(b["calc"]), "small"))
        if not b.get("eligible", True):
            block.append(P(f"Not eligible: {b.get('ineligible_reason')}", "warn"))
        el.append(KeepTogether(block))
        el.append(Spacer(1, 6))
    pt = snap["payment"]
    el.append(P("Payment terms and remittance", "h3"))
    el.append(_kv([("Payment terms", pt.get("terms_label")), ("Due-date basis", pt.get("due_basis")),
                   ("Remit to", car.get("remittance_address") or "Remittance address not supplied"),
                   ("Pay online / evidence", "\n".join(f"{i['number']}: {i['evidence_url']}" for i in snap["invoices"]) or "-")]))

    # ---- C. Evidence
    el.append(PageBreak())
    el.append(P("C. Evidence", "h2"))
    el.append(P("Event chronology", "h3"))
    rows = [["Time", "Stop", "Event", "Source / detail"]]
    for e in snap["chronology"]:
        rows.append([fmt(e.get("at")), e.get("stop"), e.get("event"), e.get("detail")])
    el.append(_table(rows, [1.5 * inch, 1.5 * inch, 1.4 * inch, 2.6 * inch]))
    el.append(P("Location evidence", "h3"))
    rows = [["Stop", "Geofence", "GPS points in window", "Accuracy", "Trail hash (SHA-256)"]]
    for s in snap["stops"]:
        g = s["gps"]
        rows.append([s.get("facility"), g.get("geofence"), str(g.get("count")), g.get("accuracy"), P(g.get("hash"), "mono")])
    el.append(_table(rows, [1.4 * inch, 1.3 * inch, 0.9 * inch, 1.1 * inch, 2.3 * inch]))
    el.append(P("Limitations: phone GPS has stated accuracy and can drift; a geofence exit shows the phone left the zone, "
                "not that unloading finished. Points recorded offline carry the phone's own timestamp.", "small"))
    el.append(P("Notices and authorizations", "h3"))
    rows = [["Obligation", "Stop", "Required method", "Recipient", "Status / time", "Provider ref"]]
    for o in snap["obligations"]:
        rows.append([o["label"], o.get("stop") or "Load", o.get("method") or "Not stated", o.get("to") or "-",
                     f"{o['status_label']}" + (f" - {fmt(o.get('at'))}" if o.get("at") else ""), o.get("ref") or "-"])
    el.append(_table(rows, [1.4 * inch, 1.0 * inch, 0.9 * inch, 1.3 * inch, 1.5 * inch, 0.9 * inch]))
    el.append(P("Contract clauses", "h3"))
    for c in snap["clauses"]:
        el.append(CondPageBreak(0.8 * inch))
        el.append(P(f"{c['label']} - source: {c.get('source') or 'not referenced'}", "small"))
        el.append(P(c["text"], "clause"))
        el.append(Spacer(1, 4))
    if not snap["clauses"]:
        el.append(P("No contract clause text was recorded.", "p"))

    el.append(P("Exhibit index", "h3"))
    rows = [["Exhibit", "Description", "SHA-256"]]
    for x in snap["exhibits"]:
        rows.append([x["id"], x["title"], P(x.get("sha256") or "-", "mono")])
    el.append(_table(rows, [0.7 * inch, 2.9 * inch, 3.4 * inch]))
    for x in snap["exhibits"]:
        data = images.get(x.get("file_id") or "")
        if not data:
            continue
        try:
            ir = ImageReader(io.BytesIO(data))
            iw, ih = ir.getSize()
            sc = min(6.5 * inch / iw, 6.2 * inch / ih)
            el.append(PageBreak())
            el.append(P(f"Exhibit {x['id']} - {x['title']}", "h3"))
            el.append(Image(io.BytesIO(data), width=iw * sc, height=ih * sc))
            el.append(P(f"SHA-256 {x.get('sha256')}. " + (x.get("note") or ""), "small"))
        except Exception:  # noqa  unreadable image (e.g. HEIC) stays listed in the index with its hash
            continue

    # ---- D. Exceptions
    el.append(PageBreak())
    el.append(P("D. Exceptions and open items", "h2"))
    if snap["exceptions"]:
        for x in snap["exceptions"]:
            el.append(P(f"- {x}", "p"))
    else:
        el.append(P("No exceptions recorded.", "p"))
    el.append(P("Record integrity", "h3"))
    qr = _qr(snap["verification_url"]) if snap.get("verification_url") else None
    txt = [P("Snapshot fingerprint (SHA-256):", "small"), P(snap.get("snapshot_hash") or "computed on issue", "mono"),
           P("This fingerprint is a record-integrity check: it shows whether this packet's recorded data has changed "
             "since it was issued. It is not proof that every recorded event is true, and it is not a signature, stamp, "
             "notarization or certification.", "small"),
           P(f"Verify online: {snap.get('verification_url') or '-'}", "small"),
           P("A supplemental detention invoice does not by itself replace any freight bill required for the shipment.", "small")]
    el.append(Table([[txt, qr or ""]], colWidths=[5.7 * inch, 1.3 * inch], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))

    doc.build(el, canvasmaker=type("PacketCanvas", (_NumberedCanvas,), {"footer": footer}))
    return buf.getvalue()
