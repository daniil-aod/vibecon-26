"""Invoice packet PDF (reportlab): summary, timestamps, trail diagram, clause, notice log, BOL photos, QR."""
import io
import math
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.lib import colors
import qrcode

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
TEAL = colors.HexColor("#0f766e")
AMBER = colors.HexColor("#f59e0b")
LINE = colors.HexColor("#e2e8f0")


def _wrap(c, text, x, y, width, font="Helvetica", size=9, leading=12, color=INK):
    c.setFont(font, size)
    c.setFillColor(color)
    words = (text or "").split()
    line = ""
    for w in words:
        t = (line + " " + w).strip()
        if c.stringWidth(t, font, size) > width:
            c.drawString(x, y, line)
            y -= leading
            line = w
        else:
            line = t
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def _trail(c, x, y, w, h, stop, pings):
    c.setStrokeColor(LINE)
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)
    lat0, lng0 = stop.get("lat"), stop.get("lng")
    if lat0 is None or lng0 is None:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 9)
        c.drawString(x + 12, y + h / 2, "No facility coordinates")
        return
    radius = float(stop.get("radius_m") or 45)
    pts = [((p["lng"] - lng0) * 111320 * math.cos(math.radians(lat0)), (p["lat"] - lat0) * 110540) for p in pings]
    extent = max([radius * 1.6] + [max(abs(a), abs(b)) * 1.1 for a, b in pts])
    scale = (min(w, h) / 2 - 14) / extent
    cx, cy = x + w / 2, y + h / 2
    c.setStrokeColor(AMBER)
    c.setFillColor(colors.HexColor("#fef3c7"))
    c.circle(cx, cy, radius * scale, fill=1, stroke=1)
    if len(pts) > 1:
        c.setStrokeColor(TEAL)
        c.setLineWidth(2)
        path = c.beginPath()
        path.moveTo(cx + pts[0][0] * scale, cy + pts[0][1] * scale)
        for a, b in pts[1:]:
            path.lineTo(cx + a * scale, cy + b * scale)
        c.drawPath(path, stroke=1, fill=0)
        c.setLineWidth(1)
    for a, b in pts[:1] + pts[-1:]:
        c.setFillColor(TEAL)
        c.circle(cx + a * scale, cy + b * scale, 3, fill=1, stroke=0)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(x + 8, y + 8, f"Geofence {int(radius)} m around {lat0:.5f}, {lng0:.5f}  |  {len(pings)} GPS points")


def build_packet(*, fleet, load, stop, invoice, billing, notices, pings, bol_images, evidence_url,
                 fingerprint, fmt_time) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter
    m = 0.6 * inch
    det = load.get("detention") or {}

    # Header
    c.setFillColor(INK)
    c.rect(0, H - 70, W, 70, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(m, H - 38, "DETENTION INVOICE & EVIDENCE PACKET")
    c.setFont("Helvetica", 9)
    c.drawString(m, H - 54, f"{fleet.get('name')}  |  Invoice {invoice.get('number')}  |  Load {load.get('load_number') or ''}")
    # QR
    qr = qrcode.make(evidence_url)
    qb = io.BytesIO()
    qr.save(qb, format="PNG")
    qb.seek(0)
    c.drawImage(ImageReader(qb), W - m - 62, H - 66, 62, 62)

    y = H - 100
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(m, y, "Bill to")
    c.drawString(W / 2, y, "Amount due")
    y -= 15
    broker = load.get("broker") or {}
    c.setFont("Helvetica", 9)
    c.drawString(m, y, broker.get("name") or "")
    c.setFont("Helvetica-Bold", 22)
    c.drawString(W / 2, y - 14, f"${invoice.get('amount', 0):,.2f}")
    y -= 12
    c.setFont("Helvetica", 9)
    c.drawString(m, y, broker.get("email") or "")
    y -= 30

    # Timeline table
    rows = [
        ("Facility", stop.get("facility_name") or ""),
        ("Address", stop.get("address") or ""),
        ("Arrived (in)", f"{fmt_time(stop.get('arrived_at'))}  [{stop.get('arrived_source') or ''}]"),
        ("Departed (out)", f"{fmt_time(stop.get('departed_at'))}  [{stop.get('departed_source') or ''}]"),
        ("Time on site", f"{billing['dwell_minutes'] / 60:.2f} h"),
        ("Free time", f"{det.get('free_time_hours') or 0:g} h"),
        ("Billed time", f"{billing['billed_minutes'] / 60:.2f} h ({int(billing.get('increment') or 15)}-min increments)"),
        ("Rate", f"${det.get('hourly_rate') or 0:,.2f}/hr" + (f", cap ${det.get('cap_amount'):,.2f}" if det.get("cap_amount") else "")),
        ("Calculation", f"{billing['billed_minutes'] / 60:.2f} h x ${det.get('hourly_rate') or 0:,.2f}"
                        + (" (capped)" if billing.get("capped") else "") + f" = ${invoice.get('amount', 0):,.2f}"),
    ]
    c.setStrokeColor(LINE)
    for k, v in rows:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 9)
        c.drawString(m, y, k)
        c.setFillColor(INK)
        c.setFont("Courier", 9)
        c.drawString(m + 110, y, str(v)[:90])
        c.line(m, y - 5, W - m, y - 5)
        y -= 17

    # Trail diagram + clause side by side
    y -= 8
    _trail(c, m, y - 190, 250, 190, stop, pings)
    cx = m + 268
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(cx, y - 12, "Rate confirmation clause")
    c.setStrokeColor(TEAL)
    c.setLineWidth(2)
    yy = _wrap(c, det.get("clause_text") or "(not stated)", cx + 8, y - 28, W - m - cx - 10, size=8.5, leading=11)
    c.line(cx, y - 20, cx, yy + 6)
    c.setLineWidth(1)
    yy -= 10
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(INK)
    c.drawString(cx, yy, "Broker notice log")
    yy -= 14
    if not notices:
        yy = _wrap(c, "No notice recorded.", cx, yy, W - m - cx, size=8.5)
    for n in notices:
        yy = _wrap(c, f"{fmt_time(n.get('sent_at'))} - emailed {n.get('to')} ({n.get('kind', 'notice')})",
                   cx, yy, W - m - cx, size=8.5)
    y -= 210

    # Fingerprint
    c.setFillColor(colors.HexColor("#f0fdfa"))
    c.setStrokeColor(TEAL)
    c.roundRect(m, y - 46, W - 2 * m, 46, 6, fill=1, stroke=1)
    c.setFillColor(TEAL)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(m + 10, y - 16, "EVIDENCE FINGERPRINT (SHA-256)")
    c.setFont("Courier", 7.5)
    c.setFillColor(INK)
    c.drawString(m + 10, y - 30, fingerprint or "sealed when sent")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(m + 10, y - 41, f"Verify online: {evidence_url}"[:140])

    # BOL photos on following pages
    for idx, (img_bytes, meta) in enumerate(bol_images):
        c.showPage()
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(m, H - m, f"Exhibit B{idx + 1}: Signed bill of lading")
        c.setFont("Helvetica", 8.5)
        c.setFillColor(MUTED)
        c.drawString(m, H - m - 14, f"Uploaded {fmt_time(meta.get('uploaded_at'))} by driver  |  SHA-256 {meta.get('sha256', '')[:32]}...")
        try:
            ir = ImageReader(io.BytesIO(img_bytes))
            iw, ih = ir.getSize()
            maxw, maxh = W - 2 * m, H - 2 * m - 40
            s = min(maxw / iw, maxh / ih)
            c.drawImage(ir, m, H - m - 30 - ih * s, iw * s, ih * s)
        except Exception:  # noqa
            c.drawString(m, H - m - 40, "(image could not be rendered)")
    c.save()
    return buf.getvalue()
