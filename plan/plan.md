# DockClock — Collect the Detention You Already Earned

DockClock turns each rate confirmation into a detention claim that is hard to dispute: AI reads the terms, the driver's phone records time at the dock, the broker gets notice on time, and the invoice packet builds itself.
It ends with a pay link and polite follow-ups until the money comes in, plus a scorecard showing which facilities and brokers cost you time.

## Who it's for
- **Owners and dispatchers at small carriers (1–25 trucks)** with no back office. They run loads, upload rate cons, and send invoices.
- **Drivers.** They only open a texted link. No app, no login.
- **Brokers.** They receive notices and invoices by email, look at the evidence page, and pay by card.

## Core features and experience

**1. Rate con reader**
- The dispatcher drops in a rate confirmation PDF. AI pulls out load number, broker name and contact email, pickup and delivery facilities and addresses, appointment times, free time, hourly rate, daily or total cap, and the notification rule (for example "notify within 1 hour of arrival" or "before free time expires").
- The exact detention clause is quoted word for word and highlighted so it can go into the invoice.
- Every extracted field can be edited. Fields the AI is unsure about are flagged for review.

**2. Driver check-in link (real SMS)**
- One tap sends the driver a text with a private link for that load.
- The link opens a simple mobile page: load info, facility on a map, and a big status button.
- When the driver's phone enters the facility geofence, arrival is stamped on its own. Departure is stamped when the phone leaves. If GPS is weak, the driver can tap "I'm at the dock" or "I'm leaving", and that tap is stamped with GPS.
- The driver photographs the signed bill of lading (BOL) with the in and out times. The photo attaches to the load.
- The phone records its location trail while the page is open. That trail powers playback.

**3. Live detention meter**
- Each active stop shows a running clock: time on site, free time left, and dollars earned once billable time starts.
- The dollar amount ticks up like a taxi meter and respects the cap from the rate con.

**4. Automatic broker notices**
- DockClock emails the broker when the rate con's notice rule requires it. If the rate con says nothing, the notice goes 30 minutes before free time runs out.
- Each notice includes arrival time, location and the quoted clause. A copy goes to the dispatcher.
- Every notice is logged with its sent time. This is the proof that notice was given on time.
- A fleet setting controls this: "send automatically" (the default) or "ask me first".

**5. Invoice packet**
- After departure, DockClock builds the packet: in and out timestamps, billable hours times the rate (capped), a map of the geofence and the truck's trail, the BOL photo, the rate con clause, and the notice log.
- Brokers get an evidence page and a downloadable PDF.
- An **evidence fingerprint** is a seal over the timestamps and photos. If anything is changed later, the page shows it.

**6. Payment and follow-ups**
- Each invoice has a Stripe card pay link. When it is paid, the invoice is marked paid automatically.
- If the invoice is unpaid, reminders go out on day 3, 7, 14 and 30. Each one is firmer in tone and re-attaches the evidence.
- The dispatcher can pause the reminders, mark the invoice paid by check or ACH, or mark it disputed or written off.

**7. Truck playback**
- A bird's-eye map replays the truck's trail on a time scrubber with play, pause and 1x/10x/60x speed.
- The geofence ring and the arrival, free-time-expired, notice-sent and departure events appear as markers on the timeline.
- Playback is shown in the app and on the broker's evidence page.

**8. Scorecard**
- Facilities and brokers are ranked by how often they detain, average dwell time, dollars billed and paid, payment rate, and days to pay.
- A simple grade from A to F tells the dispatcher whether to price up or refuse a load.

**9. Monday morning summary**
- The dashboard headline reads, for example: "Last week you were detained 14 hours across 6 loads. $520 is billable under your rate cons. 3 invoices are ready to send."
- The same summary is emailed to the owner every Monday at 7am in the fleet's time zone.

## User flow
1. The owner signs in with Google, creates the fleet (name, time zone, reply-to email), and invites dispatchers by email.
2. The dispatcher uploads a rate con, reviews the extracted terms, adds the driver's name and phone, and taps **Text driver**.
3. The driver opens the link at the facility. Arrival is stamped and the meter starts.
4. As free time runs out, the broker notice goes out on its own, and the dispatcher sees "Notice sent 2:41 PM" on the load.
5. The driver leaves (departure stamped) and uploads the BOL photo.
6. The invoice packet appears as **Ready to send**. The dispatcher reviews it and taps **Send**.
7. The broker opens the evidence page and pays by card. If they don't, reminders run until the invoice is paid or closed.
8. On Monday the owner reads the summary and checks the scorecard before booking more loads with problem facilities.

## UI/UX feel
- A dispatcher dashboard that feels like a calm control room: live meters, clear money figures, status chips (On site, Billable, Notice sent, Invoiced, Paid), and a map front and center.
- The driver page has big buttons, readable text, works one-handed in sunlight, and needs nothing beyond the link.
- Broker-facing pages look professional and neutral, with the evidence laid out like an exhibit.
- The detailed visual style is set by the design step.

## Implementation phases

**Phase 1 — MVP (built now)**
Everything in "Core features and experience" above: Google sign-in with a shared fleet, rate con AI reader, real SMS driver link with geofence stamps and BOL photo, live meter, automatic broker notices, invoice packet with evidence page, PDF and fingerprint, Stripe card pay links with status sync, follow-up sequence, truck playback, scorecard, and the Monday summary on the dashboard and by email.

**Phase 2 — Getting paid directly and billing for DockClock**
- Each carrier connects their own Stripe account, so broker payments go straight to them and DockClock's 10% is taken automatically.
- DockClock billing: 10% of recovered detention with a $49 monthly floor.
- Factoring companies get read-only access to a carrier's packets.
- Broker reply tracking, so a reply pauses reminders.
- A rate con risk warning before booking, based on that facility's and broker's scorecard.

**Phase 3 — Scale and network**
- Electronic logging device (ELD) connections, so dwell time comes from the truck's own log as a second source of evidence.
- A factoring partner portal.
- A suggested detention-adjusted rate when quoting loads.
- Spanish-language driver page.
- Industry-wide facility benchmarks shared across fleets (with consent).

## Assumptions
- **Sign-in and team:** sign-in uses Emergent-managed Google login. The owner and dispatchers share one fleet and see all of its loads and money. Drivers and brokers never log in; they use private, unguessable links.
- **Texts:** texts use your Twilio account. Before building I'll need three things from Twilio: Account SID, Auth Token and a Twilio phone number. Texting US numbers at scale needs Twilio's carrier registration (10DLC or toll-free verification), and trial accounts can only text numbers you have verified. Until those three are added, the dispatcher can copy the link and send it themselves.
- **Email:** emails use Emergent-managed email. The sender name is "DockClock" and replies go to the fleet's reply-to email. Email attachments aren't supported, so brokers get a secure link to the evidence page, with the PDF downloadable from there.
- **Payments:** Stripe in this version handles only card pay links on invoices. These run in a Stripe test account you can claim later. Until Phase 2, all payments land in that one Stripe account (yours), not in each carrier's own account.
- **Tax:** Stripe's "calculates only" tax setting is the starting point. Detention is a freight charge and usually has no sales tax. This can be switched later.
- **Phone tracking limits:** browsers only track location while the driver's link page is open. The page asks the driver to keep it open at the dock. Manual taps with GPS cover the gaps, and the BOL photo serves as the backup record.
- **Notice timing:** the geofence is a 300 m radius around the facility address and can be adjusted on the map per facility. If a rate con has no notice rule, the notice goes 30 minutes before free time ends.
- **Billing math:** time is billed in 15-minute increments after free time, the cap applies, and amounts are in US dollars.
- **Maps:** maps use OpenStreetMap, with no account needed.
- **AI reader:** the rate con reader uses the Emergent LLM key, with no key needed from you.
- **No sample data:** nothing is pre-filled or faked. The app starts empty and fills from real uploads and real check-ins.
