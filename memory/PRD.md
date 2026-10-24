# DockClock — PRD / status

## Problem
Small carriers (1–25 trucks) lose detention pay because nobody reads rate-con terms, sends the broker notice on time, or assembles indisputable evidence.

## Architecture
- FastAPI (`/app/backend/server.py`) + MongoDB; modules: `core.py` (billing math, notice timing, fingerprint), `ratecon.py` (Gemini 3.1 Pro PDF extraction, fallback 2.5 Flash), `emailer.py` (Emergent managed email + guardrail gate), `templates.py`, `sms.py` (Twilio, inert until keys), `storage.py` (Emergent object storage), `pdfgen.py` (reportlab packet + QR), `clerk_auth.py` (Emergent-managed Clerk auth: email + Google).
- React (CRA) + shadcn + react-leaflet (OSM). Pages: Landing, Sign-in/up, Onboarding, Dashboard, Loads, NewLoad, LoadDetail, Invoices, Scorecard, Settings, Driver `/d/:token`, Evidence `/e/:token`, PaymentSuccess.
- Cron: `.emergent/crons.yml` → `POST /api/cron/tick` every 15 min (notices, invoices, reminders d3/7/14/30, Monday 7am local summary). Ticks also run on every driver ping, dashboard poll and load view so notices are timely.
- Stripe claimable sandbox (Flow A), Checkout per invoice from public evidence page; status polling + webhook `/api/stripe/webhook`. Tax: tries "Stripe calculates only", falls back to no tax (sandbox has no head office address yet).

## Implemented (Phase 1)
- Fleet onboarding, owner + dispatcher invites (email), notice mode auto/ask.
- Rate con AI reader with low-confidence flags + verbatim clause; manual entry; editable terms.
- Geocoded facilities with adjustable geofence (click map + radius slider).
- Driver link: GPS watch + throttled pings, auto arrive/depart by geofence (hysteresis), manual taps with GPS, BOL photo upload, wake lock.
- Live taxi meter (dashboard + load), automatic broker notice with copy to dispatcher and log.
- Invoice per detained stop, sealed SHA-256 evidence fingerprint at send, verify/changed state, PDF packet (timestamps, trail diagram, clause, notice log, BOL pages, QR).
- Evidence page (exhibits A–E, playback, BOL, pay by card, PDF download).
- Invoice lifecycle: send/resend, pause/resume reminders, mark paid (check/ACH/factoring), dispute, write-off, reopen; reminder sequence.
- Truck playback with scrubber, event markers, 1x/10x/60x/600x, follow.
- Scorecard A–F for facilities and brokers; Monday headline + email.

## Pending / needs user
- Twilio secrets (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER). Until then "Text driver" copies the link.

## Phase 2 backlog
Stripe Connect per carrier + 10%/$49 billing, factoring read-only access, broker reply tracking, pre-booking risk warning.
## Phase 3 backlog
ELD integrations, factoring portal, detention-adjusted rate suggestion, Spanish driver page, cross-fleet benchmarks.
