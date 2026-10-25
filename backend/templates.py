"""Server-side email templates. All interpolation is escaped. Links point at this app only."""
import json
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


def driver_link_email(fleet_name, driver_name, load_number, facility, url):
    title = f"Your load {load_number} is ready"
    hi = f"Hi {escape(driver_name)}," if driver_name else "Hi,"
    inner = (f'<p style="font-size:15px;line-height:1.6">{hi} your load <strong>{escape(load_number)}</strong>'
             f'{" to " + escape(facility) if facility else ""} is ready in the DockClock Driver app.</p>'
             '<p style="font-size:15px;line-height:1.6">Open this email on your phone, tap the button, then press '
             '<strong>Start ride</strong>. Your dock arrival and departure are stamped automatically until delivery.</p>'
             + _btn(url, "Open in DockClock Driver")
             + '<p style="font-size:13px;color:#64748b">Don\'t have the app yet? The button shows you how to install it.</p>')
    return title, _wrap(title, inner, fleet_name)


def driver_recap_email(fleet_name, driver_name, period_label, rows):
    title = f"Your dock times for {period_label}"
    hi = f"Hi {escape(driver_name)}," if driver_name else "Hi,"
    if rows:
        head = "".join(f'<th style="text-align:left;padding:6px 8px;font-size:12px;color:#64748b">{h}</th>'
                       for h in ("Load", "Stop", "In", "Out", "Wait"))
        body = "".join(
            '<tr>' + "".join(f'<td style="padding:6px 8px;font-size:13px;border-top:1px solid #e2e8f0">{escape(str(v or ""))}</td>'
                             for v in (r["load"], r["facility"], r["in"], r["out"], r["wait"])) + '</tr>' for r in rows)
        table = f'<table role="presentation" width="100%" style="border-collapse:collapse"><tr>{head}</tr>{body}</table>'
    else:
        table = '<p style="font-size:14px;color:#64748b">No dock stops were recorded in this period.</p>'
    inner = (f'<p style="font-size:15px;line-height:1.6">{hi} here are your recorded dock times for '
             f'{escape(period_label)}.</p>{table}')
    return title, _wrap(title, inner, fleet_name)



def driver_open_page(valid: bool, load_number: str, driver_name: str, deep_link: str, intent_link: str,
                     ios_url: str, android_url: str) -> str:
    """Landing page for the texted driver link: opens the DockClock Driver app or shows install steps."""
    css = (
        "*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;"
        "background:#fff;color:#0f172a}main{max-width:440px;margin:0 auto;padding:20px 16px 40px}"
        ".hd{display:flex;align-items:center;gap:10px;padding-bottom:12px;border-bottom:1px solid #e2e7ed}"
        ".mk{width:32px;height:32px;border-radius:10px;background:#0f172a;color:#5eead4;display:grid;place-items:center;font-weight:700}"
        ".nm{font-weight:700;font-size:18px}.ln{margin-left:auto;font-family:ui-monospace,monospace;font-size:14px;font-weight:600}"
        "h1{font-size:26px;margin:24px 0 8px;letter-spacing:-.4px}p{font-size:16px;line-height:1.5;color:#334155;margin:0 0 12px}"
        ".btn{display:flex;align-items:center;justify-content:center;min-height:60px;border-radius:16px;font-size:19px;"
        "font-weight:600;text-decoration:none;margin-top:12px}.pri{background:#020617;color:#f8fafc}"
        ".sec{border:2px solid #0f172a;color:#0f172a;background:#fff;font-size:17px}"
        ".card{background:#020617;color:#f8fafc;border-radius:20px;padding:20px;margin-top:28px}"
        ".card h2{margin:0 0 12px;font-size:19px}.card li{margin:8px 0;color:#cbd5e1;font-size:15px}"
        ".k{font-size:12px;letter-spacing:1.2px;text-transform:uppercase;color:#5eead4;font-weight:600}"
        ".warn{background:#fffbeb;border:2px solid #fcd34d;border-radius:16px;padding:16px;margin-top:20px;color:#78350f}"
    )
    head = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>DockClock Driver</title><style>{css}</style></head><body><main>'
            f'<div class="hd"><div class="mk">&#9719;</div><div class="nm">DockClock</div>'
            f'<div class="ln" data-testid="open-load-number">{escape(load_number)}</div></div>')
    if not valid:
        return head + ('<h1 data-testid="open-invalid">This link is not valid</h1>'
                       '<p>Ask your dispatcher to text you a new link.</p></main></body></html>')
    stores = ""
    if ios_url:
        stores += f'<a class="btn sec" data-testid="open-app-store-link" href="{escape(ios_url)}">Get it on the App Store</a>'
    if android_url:
        stores += f'<a class="btn sec" data-testid="open-play-store-link" href="{escape(android_url)}">Get it on Google Play</a>'
    if not stores:
        stores = ('<div class="warn" data-testid="open-install-pending">The DockClock Driver app link isn\'t set up yet. '
                  'Ask your dispatcher to send you the install link.</div>')
    js = ("<script>var deep=" + json.dumps(deep_link) + ",intent=" + json.dumps(intent_link) + ";"
          "var a=/android/i.test(navigator.userAgent);var href=a?intent:deep;"
          "document.getElementById('open-btn').href=href;"
          "setTimeout(function(){window.location.href=href},300);</script>")
    hi = f"Hi {escape(driver_name)} — " if driver_name else ""
    return head + (
        f'<h1 data-testid="open-title">Open your load in the app</h1>'
        f'<p>{hi}tap the button to open load <b>{escape(load_number)}</b> in the DockClock Driver app, then press <b>Start ride</b>.</p>'
        f'<a id="open-btn" class="btn pri" data-testid="open-app-button" href="{escape(deep_link)}">Open DockClock Driver</a>'
        '<div class="card" data-testid="open-install-steps"><div class="k">Don\'t have the app yet?</div>'
        '<h2>Install DockClock Driver</h2><ol>'
        f'<li>Install the free DockClock Driver app{" using the button below" if (ios_url or android_url) else " (your dispatcher sends the install link)"}.</li>'
        '<li>Open it once and allow location (keep <b>Precise</b> on).</li>'
        '<li>Come back to this text and tap the link again — your load opens automatically.</li></ol></div>'
        f'{stores}</main>{js}</body></html>')
