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

## Guided demo fleet (see backend/DEMO.md)
End-to-end demo seeded by backend/demo.py, owned by abdowns4@gmail.com. 6 loads covering rate-con AI extraction, live meter, broker notices, sealed/verified evidence, card payment, reminders, cap-hit dispute, scorecards. Version-gated by DEMO_VERSION (bump + restart rebuilds it; POST /api/demo/reseed forces it). Must be kept in sync as new features ship.



## 2026-06 — DockClock Driver mobile app (Expo, /app/frontend)
- Original ask: replace the driver web page with a mobile app with the same UI. The owner texts a link that opens the app, the driver presses Start, and nothing else is needed until delivery. Real precise GPS (iOS Precise Location / Android fine), background tracking, pings same as web (20s / 25 m), send to the existing backend, install page if the app is missing.
- Web app moved to /app/web; web /d/:token now forwards to backend /api/open/:token (landing page that opens the app or shows install steps).
- Built: home (resume trip / paste link), /d/[token] driver screen (Start trip, geofence auto-stamps, manual taps, BOL camera/gallery, OSM map WebView), background location task with Android foreground service, precise-location prompts, permission cards with Open Settings.
- Tested: iteration_4 — 13/13 backend, all frontend web flows pass.
- Backlog: P0 publish + native build to verify background/precise on real phones; set DRIVER_APP_IOS_URL / DRIVER_APP_ANDROID_URL; add the production web domain to EXPO_PUBLIC_EXTRA_API_HOSTS. P1 Twilio real SMS (pending); Spanish driver UI. P2 offline ping queue.

## 2026-06 — Round 2
- Offline ping backup: points queued on the phone with GPS time, sent oldest-first (on next fix, every 15s, and on app foreground). Backend honors ping ts (≤24h old, not future); departure only after arrival; last_ping only moves forward.
- Spanish driver screens: EN/ES toggle on home + driver screen, English by default, choice saved.
- Twilio: manual "Text driver" only (user choice); waiting on TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER.
- Store links skipped (proof of concept on the owner's own phone).
- Tested: iteration_5 — 24/24 backend, frontend EN/ES + offline queue pass; duplicate-point & dropped-fix issues fixed after.

## 2026-06 — Round 3
- Email instead of SMS: driver.email on loads; web LoadDetail "Driver app link" card (DriverEmailCard.js) to email the app link or a dock-time recap now, or on a schedule (one time / daily / weekly / monthly). Texting UI removed.
- Backend: POST /api/loads/{id}/email-driver, GET/POST /api/loads/{id}/email-schedules, DELETE /api/email-schedules/{sid}; run_schedules() in the 15-min cron. Occurrences are counted from the original send time in the fleet's timezone (no drift). Each run is claimed atomically; temporary failures retry every 15 min, up to 4 times.
- Expo: trip summary after delivery (in/out/wait per stop + total), EN/ES.
- Tested: iteration_6 (20/20 new + 24/24 regression); retry and no-drift fixes applied afterwards.
- Note: the web dashboard changes in /app/web go live only when the web app is republished.


## 2026-06 — Round 4
- TEST-0001 test load in the abdowns4 demo fleet (Evergreen contract), anchored at the first accurate fix; reset endpoint plus an in-app Reset test trip button. Demo driver tokens are stable (DEMO_VERSION 3).
- App Store readiness: bundle id/package com.dockclock.driver, 1024 icon, adaptive icon, splash, ITSAppUsesNonExemptEncryption false, removed unused "fetch" background mode; .env no longer git-ignored (deployment blocker).
- Tested: iteration_8 (backend 10/10, frontend pass); accuracy gate and card order fixed afterwards.
- Backlog: localize server-provided test-load strings; delete BOL files on test reset.


