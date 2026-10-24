"""POC: rate con extraction (Gemini PDF), object storage, email, Stripe checkout."""
import asyncio, json, os, sys, uuid
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

PDF = "/tmp/test_ratecon.pdf"


def make_pdf():
    c = canvas.Canvas(PDF, pagesize=letter)
    y = 750
    lines = [
        "SUMMIT FREIGHT BROKERAGE LLC - RATE CONFIRMATION",
        "Load #: SFB-448812     Date: 03/10/2026",
        "Broker contact: Dana Ortiz  dispatch@summitfreight.example  (312) 555-0144",
        "Carrier: Ridgeline Haulers Inc  MC 778812",
        "PICKUP: Golden Valley Foods DC, 2100 S Morgan St, Chicago, IL 60608",
        "   Appointment: 03/11/2026 08:00",
        "DELIVERY: Fresh Mart Distribution, 4500 W 129th St, Alsip, IL 60803",
        "   Appointment: 03/11/2026 15:00",
        "Linehaul: $1,250.00",
        "ACCESSORIALS:",
        "Detention: Carrier is allowed 2 hours free time at each stop. After free time,",
        "detention pays $50.00 per hour, billed in 15 minute increments, max $400 per stop.",
        "Carrier must notify Summit Freight dispatch by email within 1 hour of arrival and",
        "before free time expires or detention will not be paid. Signed BOL with in/out times required.",
    ]
    for l in lines:
        c.drawString(40, y, l); y -= 20
    c.save()


async def test_extract():
    from ratecon import extract_ratecon
    data = await extract_ratecon(PDF)
    print(json.dumps(data, indent=1)[:1500])
    d = data["detention"]
    assert abs(d["hourly_rate"] - 50) < 0.01, d
    assert abs(d["free_time_hours"] - 2) < 0.01, d
    assert d.get("cap_amount") in (400, 400.0), d
    assert data["stops"] and len(data["stops"]) == 2
    print("EXTRACT OK")


def test_storage():
    from storage import put_object, get_object
    r = put_object(f"dockclock/test/{uuid.uuid4()}.pdf", open(PDF, "rb").read(), "application/pdf")
    b, ct = get_object(r["path"])
    assert len(b) > 100
    print("STORAGE OK", r["path"])


async def test_email():
    from emailer import send_email
    eid = await send_email(to="delivered@resend.dev", subject="DockClock test",
                           html="<p>DockClock integration test.</p>")
    print("EMAIL OK", eid)


def test_stripe():
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    s = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price_data": {"currency": "usd", "unit_amount": 15000,
                     "product_data": {"name": "Detention SFB-448812"}}, "quantity": 1}],
        success_url="https://example.com/s?session_id={CHECKOUT_SESSION_ID}",
        cancel_url="https://example.com/c")
    assert s.url
    print("STRIPE OK", s.id)


if __name__ == "__main__":
    make_pdf()
    test_storage()
    test_stripe()
    asyncio.run(test_email())
    asyncio.run(test_extract())
