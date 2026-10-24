# DockClock Guided Demo Fleet

An end-to-end smoke test that **demonstrates every part of the app** as a ready-to-explore
fleet. It is defined in `backend/demo.py`.

## Who can see it
- Owner access is granted to **abdowns4@gmail.com**.
- On sign-in, that email is attached to the demo fleet as **owner** (via an owner-role invite,
  or by re-pointing an existing account). They see a fully populated fleet immediately.

## What it demonstrates (fleet: "Summit Ridge Carriers (Demo)")
6 loads across 3 brokers and 5 facilities cover the whole lifecycle:

| Load | Broker | State | Shows |
|------|--------|-------|-------|
| EVG-77421 | Evergreen | PAID by card | rate con + AI terms, 2-stop trail, notice on time, BOL, sealed **verified** evidence, card payment, recovered KPI |
| RL-55018 | Redline | ACTIVE on site | **live detention meter**, truck on the map, auto notice sent |
| APX-30277 | Apex | invoice READY | attention list "invoice ready", low-confidence AI field flagged |
| APX-30188 | Apex | SENT / overdue | outstanding KPI, day-3 & day-7 reminders fired |
| EVG-77510 | Evergreen | completed, no detention | quick turn under free time (good-facility signal) |
| RL-55102 | Redline | DISPUTED | **cap hit $400**, dispute handling |

Also produces: weekly dashboard headline, broker scorecards (A for Evergreen → F for Apex/Redline),
facility scorecards (A for Midwest DC → F for others).

Sample files are generated in-process: a one-page **rate confirmation PDF** per load and a
signed **bill-of-lading photo** (PNG) for each detained delivery. No real email/SMS/charges —
driver texts are marked `simulated` (Twilio not connected), statuses are written directly.

## Keeping it up to date with future changes
`demo.py` has `DEMO_VERSION`. On every backend startup, `ensure_demo()`:
- seeds the fleet if it is missing, or
- **rebuilds it when `DEMO_VERSION` changed** (otherwise leaves it as-is so exploration isn't reset).

**Workflow:** whenever a new feature is added that the demo should showcase, extend the
seeder in `demo.py` and bump `DEMO_VERSION`. The next deploy/restart rebuilds the demo.

Force a rebuild without a code change:
```
curl -X POST "$BACKEND_URL/api/demo/reseed" -H "Authorization: Bearer $WEBHOOK_CRON_SECRET"
```

## Notes
- The seeder only ever touches data scoped to `fleet_id == demo-dockclock-fleet`. Real customer
  fleets still start empty.
- A returning reviewer keeps ownership across rebuilds (existing `owner_user_id` is preserved).
