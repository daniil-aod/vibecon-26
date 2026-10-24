# DockClock — Engineering Handoff / Project README

> This README is the single source of truth for a new agent/developer taking over DockClock.
> Read it top to bottom before touching code. It describes what the app is, what is built and
> tested, how everything is wired, the demo fleet, known gotchas, and what to do next.
> Companion docs: `backend/DEMO.md` (demo fleet), `memory/PRD.md` (roadmap), `design_guidelines.md` (UI).

Preview URL: **https://detention-pay.preview.emergentagent.com**

---

## 1. What DockClock is

DockClock is a **detention-claim workflow for small trucking carriers (1–25 trucks)**. Detention =
the money a broker owes a carrier when a driver is held at a dock past the free time stated in the
rate confirmation. Carriers routinely lose this money because they lack clean, timebstamped evidence
and miss notice deadlines. DockClock automates the whole chain:

1. **Read the rate con** — upload the broker's rate confirmation PDF; AI extracts the detention terms
   (free time, $/hr, increment, cap, notice rule, signed-BOL requirement, verbatim clause).
2. **Track the driver** — a no-app, no-login driver link (texted to the driver) reports GPS. A
   geofence auto-stamps arrival/departure; the driver can also tap manually and photograph the BOL.
3. **Run the meter** — a live detention meter ticks once free time is exceeded, honoring increments
   and caps.
4. **Notify the broker on time** — an email notice is sent before free time expires (auto, or
   "ask me first").
5. **Bill with evidence** — an invoice + sealed evidence packet (geofenced times, GPS trail, signed
   BOL, rate-con clause, notice log) with a tamper-evident fingerprint; broker gets a public evidence
   page and a Stripe card-payment link.
6. **Chase payment** — automated reminders at day 3/7/14/30; status tracking (paid/disputed/written-off).
7. **Learn** — broker & facility scorecards (A–F), a weekly Monday-morning owner summary email.

**Important product rule:** real customer fleets start **empty** — no pre-filled sample data. The
only seeded data is the isolated **demo fleet** (section 11).

---

## 2. Current status & provenance (read this carefully)

Phase 1 MVP is **implemented and agent/automated-tested**. It has **not been formally user-accepted**
end to end. Status of each piece:

| Area | State |
|------|-------|
| Clerk sign-in (Google/email), fleet onboarding, dispatcher invites | Built, tested |
| Rate con upload + AI extraction (Gemini via Emergent LLM) | Built, tested (core POC + UI upload) |
| Driver link: GPS pings, geofence arrive/depart, manual tap, BOL photo | Built, tested |
| Live detention meter, increments, caps (per_stop/per_day/per_load) | Built, tested |
| Broker notice (auto / ask-first), notice log, on-time flag | Built, tested |
| Invoice + sealed evidence + fingerprint + public evidence page + PDF packet | Built, tested |
| Stripe Checkout card payment + payment status sync + webhook | Built, test-card browser-tested |
| Reminders (3/7/14/30), pause/resume, mark paid/disputed/written-off | Built, tested |
| Map + trail playback, dashboard KPIs, broker/facility scorecards | Built, tested |
| Weekly Monday 7am owner summary email | Built; endpoint tested, production schedule not yet proven |
| 15-minute platform cron (`/api/cron/tick`) | Built, auth/idempotency tested |
| **Guided demo fleet** for abdowns4@gmail.com | Built, tested (section 11) |
| Driver page "location blocked" prominent prompt | Built, tested (section 12) |

### Known caveats / not-done
- **Real SMS is NOT configured.** Twilio secrets are absent, so `sms.py` returns `not_configured`
  and the UI falls back to copying the driver link. This is the #1 pending item to satisfy "real SMS".
- **Stripe is the platform sandbox/test account.** Test-card payments work. **Automatic tax is
  disabled** (Stripe rejected it — no valid head-office address on the sandbox account); checkout
  falls back to no tax (detention is usually non-taxable). Live payouts/Connect are Phase 2.
- **Weekly summary** real delivery at Monday 7am fleet-local time is not production-confirmed (only
  the endpoint and logic are tested).
- Test/smoke data from earlier rounds may exist under *other* test accounts (not the demo fleet).

---

## 3. Stack & architecture

- **Backend:** FastAPI (Python), Motor (async MongoDB). All routes prefixed `/api`. Binds `0.0.0.0:8001`.
- **Frontend:** React (CRA, **yarn**, not npm), react-router, Tailwind + shadcn/ui, Clerk React SDK,
  react-leaflet (OpenStreetMap), sonner toasts, lucide-react icons.
- **DB:** MongoDB via `MONGO_URL` / `DB_NAME`. **UUID string ids everywhere (never ObjectId).** All
  datetimes are timezone-aware UTC, stored as ISO strings.
- **Ingress:** `/api/*` → backend:8001, everything else → frontend:3000.
- **Services:** managed by **supervisor** (`supervisorctl restart backend|frontend`). Hot reload is on;
  only restart after dependency or `.env` changes. **Never run servers directly; never use npm.**
- **Do not modify** `frontend/.env:REACT_APP_BACKEND_URL` or `backend/.env:MONGO_URL`.

Env access: backend `os.environ.get(...)`; frontend `process.env.REACT_APP_BACKEND_URL` /
`import.meta.env.REACT_APP_BACKEND_URL`. Frontend calls backend at `${REACT_APP_BACKEND_URL}/api`.

---

## 4. Repository layout

```
/app
├── backend/
│   ├── server.py        # FastAPI app: all /api routes, dashboard, scorecard, cron, Stripe, startup
│   ├── core.py          # Pure domain logic: detention math, notice timing, evidence fingerprint, grades
│   ├── clerk_auth.py    # Clerk session verification, prod proxy relay, require_user dependency
│   ├── ratecon.py       # Gemini rate-con extraction (emergentintegrations LlmChat) -> normalized JSON
│   ├── storage.py       # Emergent managed object storage (put_object/get_object/init_storage)
│   ├── emailer.py        # Emergent managed email send (send_email / EmailError)
│   ├── sms.py           # Twilio SMS (inert until TWILIO_* secrets exist; returns not_configured)
│   ├── templates.py     # HTML email bodies: notice, invoice, invite, weekly summary
│   ├── pdfgen.py        # reportlab evidence/invoice PDF packet builder (build_packet)
│   ├── demo.py          # Guided demo fleet seeder (section 11)
│   ├── DEMO.md          # Demo fleet documentation
│   ├── requirements.txt # pip freeze (update via: pip install X && pip freeze > requirements.txt)
│   └── .env             # secrets (see section 5)
├── frontend/
│   ├── src/
│   │   ├── App.js        # Router + Clerk provider wiring (routes in section 10)
│   │   ├── lib/          # api.js (axios wrappers publicApi/api), format.js (clock/time), fleet.js
│   │   ├── components/   # AppShell, StatusChip, DetentionMeter, Maps, TrailPlayback, EvidenceSeal,
│   │   │   │             # AuthImage, auth/ClerkAuthProvider.jsx, ui/ (shadcn)
│   │   └── pages/        # Landing, Onboarding, Dashboard, Loads, NewLoad, LoadForm, LoadDetail,
│   │                     # Invoices, Scorecard, Settings, Driver, Evidence, PaymentSuccess
│   └── .env             # REACT_APP_BACKEND_URL (do not edit)
├── .emergent/crons.yml  # 15-min cron -> POST {{BASE_URL}}/api/cron/tick
├── memory/PRD.md        # roadmap / backlog
├── tests/               # test_core.py, smoke_backend.py, extra_checks.py, demo_test.py
├── test_reports/        # testing-agent iteration_*.json
└── design_guidelines.md # UI system (fonts, tokens, components)
```

---

## 5. Environment & secrets

Secrets live in `backend/.env` and are managed via the platform secrets tool (never ask for or paste
keys in chat; use the secure secrets card). Current state (from `secrets_list`):

**Configured & working**
- `EMERGENT_LLM_KEY` — Emergent universal key (Gemini extraction; also used to init object storage).
- `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` — Emergent-managed Clerk (owner/dispatcher sign-in).
- `EMERGENT_EMAIL_KEY`, `EMAIL_FROM_NAME=DockClock` — Emergent-managed email (notices, invoices, reminders, weekly).
- `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_ACCOUNT_ID`, `STRIPE_MODE=test` — Stripe sandbox.
- `WEBHOOK_CRON_SECRET` — bearer secret for `/api/cron/tick` and `/api/demo/reseed`.
- `INTEGRATION_PROXY_URL` — base for Emergent integrations (object storage); defaults if unset.
- System (do not touch): `MONGO_URL`, `DB_NAME`, `CORS_ORIGINS`, `REACT_APP_BACKEND_URL`, `WDS_SOCKET_PORT`.

**Not configured (pending)**
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` — required for **real driver SMS**.
  Until present, `sms.sms_configured()` is False and `/me` returns `sms_configured:false`; UI copies
  the driver link instead of texting. Collect via the secrets card, then no code change is needed.

---

## 6. Data model (MongoDB collections)

All ids are UUID strings; all timestamps ISO-8601 UTC. Everything tenant-scoped by `fleet_id`.

- **users**: `{user_id (Clerk sub), email, name, fleet_id, role ('owner'|'dispatcher'), created_at}`.
  Created lazily on first authenticated request (`current_member`).
- **fleets**: `{id, name, timezone, reply_to_email, notice_mode ('auto'|'ask'), owner_user_id,
  app_url, invoice_seq, weekly_sent_key, created_at}`. Demo fleet also has `is_demo, demo_version`.
- **invites**: `{id, fleet_id, email, role, status ('pending'|'accepted'), ...}`. Claimed on sign-in
  by `current_member` (see section 8). Owner-role invites hand over `owner_user_id`.
- **loads**: `{id, fleet_id, load_number, carrier_name, linehaul_amount, broker{name,contact_name,
  email,phone}, broker_id, detention{...}, stops[...], driver{name,phone}, driver_token, ratecon_file_id,
  low_confidence[], sms_log[], last_ping{lat,lng,ts}, status, created_at, updated_at}`.
  - **stop**: `{id, seq, type ('pickup'|'delivery'), facility_id, facility_name, address, appointment,
    lat, lng, radius_m, arrived_at, departed_at, arrived_source, departed_source, arrived_coords,
    departed_coords, events[...], bol[{file_id,sha256,uploaded_at,content_type}],
    notice{status, due_at, sent_at, to, email_id, manual_by, error}}`.
    notice.status ∈ pending|awaiting_approval|sent|missed|not_needed|no_email|failed.
  - **detention terms** (`detention`): `free_time_hours, hourly_rate, billing_increment_minutes,
    cap_amount, cap_scope ('per_stop'|'per_day'|'per_load'), notice_after_arrival_minutes,
    notice_before_expiry_minutes, notice_rule_text, requires_signed_bol, clause_text`.
- **pings**: `{id, load_id, fleet_id, stop_id, lat, lng, accuracy, ts}`. The GPS trail.
- **facilities**: `{id, fleet_id, key, name, address, lat, lng, radius_m, created_at}`. De-duped by key.
- **brokers**: `{id, fleet_id, key, name, email, created_at}`.
- **invoices**: `{id, fleet_id, load_id, stop_id, number ('DC-1001'), load_number, broker_*,
  facility_*, amount, billable_label, status ('ready'|'sent'|'paid'|'disputed'|'written_off'),
  public_token, fingerprint, sealed_evidence, sealed_at, reminders[], reminders_paused, sent_at,
  paid_at, paid_method, paid_amount, last_emailed_at, viewed_at, history[]}`.
- **notices**: audit docs `{id, fleet_id, load_id, stop_id, kind, to, sent_at, email_id, on_time, created_at}`.
- **files**: `{id, fleet_id, storage_path, content_type, size, sha256, kind ('ratecon'|'bol'),
  is_deleted, extracted (for ratecons), created_at, ...}`.
- **payment_transactions**: `{session_id, invoice_id, fleet_id, amount, currency, status,
  payment_status, tax_mode, stripe_payment_intent_id, created_at, updated_at}`.
- **cron_runs**: `{_id: run_id, at}` — idempotency guard for cron deliveries.

Startup indexes (server.startup): loads.id unique, loads.driver_token unique, loads.fleet_id,
invoices.public_token unique, invoices.fleet_id, pings(load_id,ts), users.user_id unique.

---

## 7. Core domain logic (`core.py`) — do not duplicate elsewhere

- `stop_billing(stop, det, now, other_billed)` → dwell/billable/billed minutes, amount, capped flag,
  free_expires_at, live flag. Billing = `floor(billable/inc)*inc` minutes × rate; cap applied per scope.
- `notice_due_at(arrived, det)` → when the broker notice must go out (before free expiry, or a
  fraction of notice-after-arrival; default 30 min before expiry).
- `evidence_record(invoice, load, stop, billing, notices, pings)` → the canonical dict that is hashed.
- `canonical_hash(obj)` = sha256 of sorted-keys JSON. `trail_hash(pings)` hashes rounded lat/lng/ts.
- **Evidence seal/verify:** on invoice send (`ready`→`sent`), `sealed_evidence` + `fingerprint` are
  stored. `verify()` recomputes from current state; returns `verified` (match), `changed` (lists
  changed fields), or `unsealed`. The fingerprint depends on times, terms, BOL **sha256** (not upload
  time), notice sent times, and the GPS **trail** — so editing a stop after sealing is detectable.
- `REMINDER_DAYS = [3,7,14,30]`; `grade_from_score` → A/B/C/D/F.

**Gotcha (fingerprint + pings):** `playback_data(load, stop_id)` filters pings to
`[arrived-45m, departed+45m]`. Anything that seals evidence must hash **that same windowed set** or
verify will report `changed`. `demo.py._window()` mirrors this.

---

## 8. Auth & roles (Clerk)

- `clerk_auth.require_user` validates the Clerk session (Bearer token or `__session` cookie) → `user_id`.
- `server.current_member` upserts the `users` row (fetching email/name from Clerk) and, if the user
  has no fleet but a **pending invite** matches their email, attaches them with the invite's `role`
  (`dispatcher` default; `owner` for the demo). Owner invites also set `fleet.owner_user_id`.
- `fleet_member` requires a fleet (409 if none). `require_owner` enforces owner-only actions (fleet
  settings, invites, force weekly summary) → 403 for dispatchers.
- Frontend: `GET /api/clerk/config` tells the SPA the publishable key / proxy. `GET /api/me` returns
  `{user, fleet, sms_configured}` and syncs `fleet.app_url` to the current origin.
- **Testing note:** Clerk sign-in uses one-time tickets that are hard for browser automation; prefer
  testing authenticated flows at the API layer, and public pages (`/d/...`, `/e/...`) in the browser.

---

## 9. API surface (all under `/api`)

- **Auth/fleet:** `GET /me`, `POST /fleet`, `PATCH /fleet`, `GET /fleet/team`, `POST /fleet/invites`,
  `DELETE /fleet/invites/{id}`, `GET /clerk/config`, `* /__clerk/{path}` (prod relay).
- **Files/geo:** `GET /files/{id}`, `GET /geocode?q=`, `POST /ratecons/extract` (upload → AI terms).
- **Loads:** `POST /loads`, `GET /loads`, `GET /loads/{id}`, `PATCH /loads/{id}`, `DELETE /loads/{id}`,
  `POST /loads/{id}/sms` (text driver), stop time/geofence adjust, `POST /loads/{id}/stops/{sid}/notice`.
- **Driver (public, by token):** `GET /driver/{tok}`, `POST /driver/{tok}/ping`,
  `POST /driver/{tok}/stops/{sid}/tap/{arrive|depart}`, `POST /driver/{tok}/stops/{sid}/bol`.
  (Route order: the literal `/bol` route is declared **before** the parameterized `/tap/{action}` —
  keep it that way; see section 13.)
- **Invoices:** `GET /invoices`, `GET /invoices/{id}`, `POST /invoices/{id}/send`,
  `POST /invoices/{id}/status` (pause/resume/mark_paid/dispute/write_off/reopen), `GET /invoices/{id}/pdf`.
- **Public evidence/payment:** `GET /public/evidence/{tok}`, `.../pdf`, `.../files/{fid}`,
  `POST /public/evidence/{tok}/checkout` (Stripe), `GET /payments/status/{session_id}`, `POST /stripe/webhook`.
- **Dashboard/analytics:** `GET /dashboard`, `GET /scorecard`, `POST /summary/send-now` (owner).
- **Ops:** `POST /cron/tick` (bearer `WEBHOOK_CRON_SECRET`), `POST /demo/reseed` (same bearer).

---

## 10. Frontend routes (`App.js`)

Public: `/` (Landing or redirect), `/sign-in/*`, `/sign-up/*`, `/d/:token` (Driver),
`/e/:token` (Evidence), `/payment/success`.
Protected (`/app`, requires Clerk + fleet): index `Dashboard`, `loads`, `loads/new`, `loads/:id`,
`invoices`, `scorecard`, `settings`. First-time users (no fleet) are routed to Onboarding.

UI must follow `design_guidelines.md` ("control-room" calm dispatcher theme; Space Grotesk / IBM Plex
Sans / IBM Plex Mono). Every interactive/key element needs a `data-testid`.

---

## 11. The guided demo fleet (`backend/demo.py`) — "end-to-end smoke test"

A fully-worked fleet so a reviewer can explore every feature. Owned by **abdowns4@gmail.com**.

- **Access:** on sign-in, that email is attached as **owner** via an owner-role invite (or an
  existing account is re-pointed). Fleet id `demo-dockclock-fleet`, name "Summit Ridge Carriers (Demo)".
- **Contents:** 6 loads / 3 brokers / 5 facilities covering the whole lifecycle:
  - `EVG-77421` Evergreen — **paid by card**, 2 stops, trail, on-time notice, BOL, sealed **verified**
    evidence, seeded `payment_transactions` row → feeds "recovered" KPI.
  - `RL-55018` Redline — **active on site now**: live meter running, truck on the map, auto notice sent.
  - `APX-30277` Apex — invoice **ready to send** (attention list), one AI low-confidence field flagged.
  - `APX-30188` Apex — invoice **sent, overdue**, day-3 & day-7 reminders fired → "outstanding" KPI.
  - `EVG-77510` Evergreen — quick turn, **no detention** (good-facility signal).
  - `RL-55102` Redline — **cap hit $400**, invoice **disputed**.
  - Produces dashboard headline, broker scorecards (Evergreen A → Apex/Redline F), facility scorecards.
- **Sample files are generated in-process:** a one-page **rate confirmation PDF** per load
  (`make_ratecon_pdf`, reportlab) and a signed **BOL photo PNG** per detained delivery (`make_bol_png`,
  Pillow). BOL timestamps + the date drawn on the image are set to **each load's own departure time**
  (not seed time) — this was a deliberate fix; keep new BOLs contemporaneous with their stop.
- **GPS trails** (`make_trail`) = approach → dwell inside the 300 m geofence → depart, as `pings`.
  Sealing uses `_window()` to match `playback_data`'s ping window so fingerprints verify.
- **MOCKED in the demo:** driver texts (`sms_log` entries marked `simulated`), broker notice/invoice
  emails (written as `sent` statuses, not actually emailed), and the Stripe payment (seeded txn, not a
  live charge).

### Keep-updated workflow (the user explicitly asked for this)
`DEMO_VERSION` gates rebuilds. On every backend startup `ensure_demo(db)`:
- seeds if the demo fleet is missing, **or rebuilds when `DEMO_VERSION` changed** (otherwise leaves it
  so a reviewer's exploration isn't reset).
- `seed_demo` only ever deletes/writes data scoped to `fleet_id == demo-dockclock-fleet`; real fleets
  are untouched. A returning owner keeps ownership across rebuilds.

**When you add or change a feature that the demo should showcase: extend `demo.py` and bump
`DEMO_VERSION`.** It rebuilds on the next restart. Force a rebuild anytime:
```
curl -X POST "$BACKEND_URL/api/demo/reseed" -H "Authorization: Bearer $WEBHOOK_CRON_SECRET"
```
Note: a rebuild regenerates `public_token`s, so `/e/...` and `/d/...` links change. List current links:
`python -c "..."` querying loads.driver_token and invoices.public_token for the demo fleet.
Current `DEMO_VERSION = 2`.

---

## 12. Driver page location-permission behavior (`pages/Driver.js`)

The public driver page watches GPS and throttles pings (every 20s or 25m moved). Recent fix: when the
phone **blocks** location, it shows a **prominent amber card** (`data-testid="driver-location-blocked"`)
with phone-specific steps (iOS vs Android), a **"I've turned it on — try again"** button
(`data-testid="driver-enable-location-button"`) that re-requests location, and it auto-detects via the
Permissions API when the user grants it. The status chip (`data-testid="driver-gps-status"`) reads
"Location is off" when blocked. A manual-tap fallback ("I'm at the dock") remains so a blocked phone
never fully blocks the driver. Rationale: once a browser is set to "Block", it won't re-prompt on its
own — the user must change site settings, hence the instructions rather than a silent re-ask.

---

## 13. Integrations — state & how to extend

| Integration | Module | State | To extend / finish |
|---|---|---|---|
| Emergent LLM (Gemini `gemini-3.1-pro-preview`, fallback `gemini-2.5-flash`) | `ratecon.py` | Working | Monitor extraction quality on real rate cons; low-confidence fields are human-editable in the UI. |
| Object storage (Emergent managed) | `storage.py` | Working | `init_storage` runs at startup; `put_object/get_object`. Validate upload size/persistence. |
| Email (Emergent managed) | `emailer.py`, `templates.py` | Working | Verify deliverability + reply-to with a real fleet address. Broker reply tracking is Phase 2. |
| Twilio SMS | `sms.py` | **Inert (no creds)** | Add `TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE_NUMBER` via secrets card. Then `/loads/{id}/sms` sends real texts. Check 10DLC/toll-free verification for scale. No code change needed. |
| Stripe (sandbox) | `server.py` checkout/webhook | Test-card works; auto-tax disabled | For production: claim/configure Stripe account + valid business address (to enable tax), wire live webhook. Phase 2 = Connect for carrier payouts + platform fee. |
| Maps (OpenStreetMap/Leaflet, Nominatim geocode) | `Maps.js`, `/geocode` | Working, no key | Validate tiles/geocode for real facility addresses. |
| Platform cron | `.emergent/crons.yml` → `/api/cron/tick` | Endpoint tested | Confirm scheduled execution + Monday-7am summary after deploy/publish. |

**For any new third-party integration:** use the integration-playbook expert first, collect keys via
the secrets card (never chat), and for OpenAI/Anthropic/Google LLMs use the Emergent universal key
(`EMERGENT_LLM_KEY`) — do not install those SDKs directly.

---

## 14. Scheduled jobs

`/api/cron/tick` (POST, bearer `WEBHOOK_CRON_SECRET`, idempotent via `x-webhook-id`) runs `run_tick()`:
for each active load `process_load` (free-time events, send due notices, build invoices), then per
fleet `run_reminders` (3/7/14/30 day escalation) and `run_weekly` (Monday ≥07:00 fleet-local, once per
ISO week, emails the owner). Schedule is every 15 min (`*/15 * * * *`). `process_load` is idempotent,
so it's also run on-demand when loading the dashboard/load detail.

---

## 15. Testing

- Prefer the **testing agent**; reports land in `test_reports/iteration_*.json`. Latest:
  `iteration_3.json` — demo fleet + driver location fix, 6/6 backend + 11/11 frontend passed.
- Handy scripts in `tests/`: `test_core.py` (storage/Stripe/email/LLM POC), `smoke_backend.py`
  (API walkthrough), `extra_checks.py` (notice/cap/invoice/reminder/roles/scorecard), `demo_test.py`
  (demo + driver location, written by the testing agent).
- Quick backend checks: `curl $REACT_APP_BACKEND_URL/api/` → `{"app":"DockClock","ok":true}`.
  Public evidence: `curl $BE/api/public/evidence/<token>`. Frontend compile sanity:
  `cd frontend && npx esbuild src/pages/X.js --loader:.js=jsx --bundle --outfile=/dev/null`
  (Leaflet `.png`/`.css` errors there are harmless; add `--loader:.png=dataurl --loader:.css=css`).

---

## 16. Dead-ends / do-not-retry ledger

1. **Route order in `server.py`:** the literal `/driver/{tok}/stops/{sid}/bol` route MUST stay above
   the parameterized `/tap/{action}` route, or the BOL route gets shadowed.
2. **MongoDB array `$ne` for weekly filtering** omitted valid detention — use `$elemMatch`
   (see `period_summary`, `dashboard`). Keep it.
3. **Stripe automatic tax** fails on the sandbox (no valid head-office address). Checkout is card-only
   with no tax by design; don't re-enable tax until a real business address is configured.
4. **Stripe Checkout accordion** broke browser automation — Checkout was constrained to `card` only.
5. **`/tmp` is not persistent** — put durable test artifacts in `/app/tests`, not `/tmp`.
6. **Clerk one-time tickets** make browser auth flaky — test authed flows via API, public pages via browser.
7. **Demo fingerprints:** always seal using the `_window()`-filtered pings (mirrors `playback_data`),
   else evidence verifies as `changed`.

---

## 17. Roadmap (see `memory/PRD.md`)

- **Phase 2:** Stripe Connect per carrier (carrier-direct payout + 10% / $49/mo floor billing),
  broker reply tracking (pause reminders on reply), factoring read-only share link, pre-booking risk
  warning (warn on D/F broker/facility, suggest higher rate).
- **Phase 3:** ELD integrations, factoring partner portal, detention-adjusted rate suggestions,
  Spanish driver UI, consented cross-fleet benchmarks.

---

## 18. Immediate next steps for the new agent

1. **Enable real SMS** — collect Twilio creds via the secrets card, send a real test text, verify the
   driver link flow; surface clear errors without dropping the copy-link fallback.
2. **User acceptance** — have the user sign in and run sign-in → rate-con upload → driver session →
   BOL → notice → payment in preview. Don't call Phase 1 "done" until confirmed.
3. **Confirm cron + email in deployment** — real Monday 7am summary + broker emails from the managed
   sender with the right reply-to.
4. Keep the **demo fleet in sync** with any new feature (extend `demo.py`, bump `DEMO_VERSION`).

---

## 19. Common commands

```
sudo supervisorctl status
sudo supervisorctl restart backend        # after .env or requirements change
sudo supervisorctl restart frontend
tail -n 80 /var/log/supervisor/backend.*.log
tail -n 80 /var/log/supervisor/frontend.*.log
cd /app/backend && pip install <pkg> && pip freeze > requirements.txt
cd /app/frontend && yarn add <pkg>        # never npm
```
