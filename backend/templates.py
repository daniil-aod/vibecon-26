"""Server-side email templates. All interpolation is escaped. Links point at this app only."""
from html import escape

INK = "#0f172a"
TEAL = "#0f766e"


def _wrap(title: str, inner: str, fleet_name: str) -> str:
    return (
        '<table role="presentation" width="100%" style="background:#f3f6fa;padding:24px 0"><tr><td align="center">'
        '<table role="presentation" width="600" style="max-width:600px;background:#ffffff;border:1px solid #e2e8f0;'
        'border-radius:12px;font-family:Arial,Helvetica,sans-serif;color:#0f172a">'
        f'<tr><td style="padding:20px 28px;border-bottom:1px solid #e2e8f0"><strong style="font-size:15px;color:{INK}">'
        f'DockClock</strong><span style="color:#64748b;font-size:13px"> &middot; on behalf of {escape(fleet_name)}</span></td></tr>'
        f'<tr><td style="padding:28px"><h1 style="font-size:20px;margin:0 0 16px">{escape(title)}</h1>{inner}</td></tr>'
        '<tr><td style="padding:16px 28px;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b">'
        f'Sent by DockClock for {escape(fleet_name)}. Reply to this email to reach the carrier directly. '
        'We never ask for passwords or card details by email.</td></tr></table></td></tr></table>'
    )


def _btn(url: str, label: str) -> str:
    return (f'<p style="margin:24px 0"><a href="{escape(url)}" style="background:{INK};color:#ffffff;'
            f'padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold">{escape(label)}</a></p>')


def _rows(rows) -> str:
    cells = "".join(
        f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;width:40%">{escape(k)}</td>'
        f'<td style="padding:6px 0;font-size:13px;font-family:Courier New,monospace">{escape(str(v))}</td></tr>'
        for k, v in rows)
    return f'<table role="presentation" width="100%" style="border-collapse:collapse">{cells}</table>'


def _clause(text: str) -> str:
    if not text:
        return ""
    return (f'<p style="font-size:12px;color:#64748b;margin:20px 0 6px">Rate confirmation clause</p>'
            f'<blockquote style="margin:0;padding:12px 14px;border-left:3px solid {TEAL};background:#f0fdfa;'
            f'font-size:13px;line-height:1.5">{escape(text)}</blockquote>')


def notice_email(fleet_name, load, stop, free_expires_local, arrived_local, maps_url):
    title = f"Detention notice: Load {load.get('load_number') or ''} at {stop.get('facility_name') or 'facility'}"
    inner = (
        f'<p style="font-size:14px;line-height:1.6">This is formal notice that our truck for load '
        f'<strong>{escape(load.get("load_number") or "")}</strong> is on site and free time is about to run out. '
        'Detention will accrue under the rate confirmation terms below.</p>'
        + _rows([
            ("Facility", stop.get("facility_name") or ""), ("Address", stop.get("address") or ""),
            ("Arrived", arrived_local), ("Free time ends", free_expires_local),
            ("Detention rate", f"${(load.get('detention') or {}).get('hourly_rate') or 0:,.2f}/hr"),
            ("Driver", (load.get("driver") or {}).get("name") or ""),
        ])
        + (f'<p style="font-size:13px">Location: <a href="{escape(maps_url)}">view arrival point on map</a></p>' if maps_url else "")
        + _clause((load.get("detention") or {}).get("clause_text"))
    )
    return title, _wrap(title, inner, fleet_name)


def invoice_email(fleet_name, invoice, load, stop, evidence_url, tone_idx=None):
    tones = [
        ("Friendly reminder", "Just a quick reminder that this detention invoice is still open."),
        ("Second reminder", "This detention invoice remains unpaid. The full evidence packet is linked below."),
        ("Payment overdue", "This invoice is now two weeks past due. Please arrange payment or tell us if anything is disputed."),
        ("Final notice", "This is our final notice before this invoice is escalated with our factoring partner and noted in our broker records."),
    ]
    amount = f"${invoice.get('amount', 0):,.2f}"
    if tone_idx is None:
        title = f"Detention invoice {invoice.get('number')} - {amount}"
        lead = (f'Attached by secure link is our detention invoice for load <strong>{escape(load.get("load_number") or "")}</strong>. '
                'The evidence packet includes geofenced in/out times, the truck trail, the signed BOL, your rate con clause and our notice log.')
    else:
        label, text = tones[min(tone_idx, 3)]
        title = f"{label}: invoice {invoice.get('number')} - {amount}"
        lead = escape(text)
    inner = (
        f'<p style="font-size:14px;line-height:1.6">{lead}</p>'
        + _rows([
            ("Invoice", invoice.get("number")), ("Load", load.get("load_number") or ""),
            ("Facility", stop.get("facility_name") or ""), ("Billable time", invoice.get("billable_label") or ""),
            ("Amount due", amount),
        ])
        + _btn(evidence_url, "View evidence and pay")
        + '<p style="font-size:12px;color:#64748b">The evidence page lets you download the full PDF packet and pay by card.</p>'
    )
    return title, _wrap(title, inner, fleet_name)


def weekly_email(fleet_name, headline, app_url, stats):
    title = "Your Monday detention summary"
    inner = (f'<p style="font-size:16px;line-height:1.6"><strong>{escape(headline)}</strong></p>'
             + _rows(stats) + _btn(app_url, "Open DockClock"))
    return title, _wrap(title, inner, fleet_name)


def invite_email(fleet_name, inviter, app_url):
    title = f"You're invited to {fleet_name} on DockClock"
    inner = (f'<p style="font-size:14px;line-height:1.6">{escape(inviter)} invited you to dispatch for '
             f'<strong>{escape(fleet_name)}</strong> on DockClock. Sign up with this email address to join the fleet.</p>'
             + _btn(app_url, "Join the fleet"))
    return title, _wrap(title, inner, fleet_name)
