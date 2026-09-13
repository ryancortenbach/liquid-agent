# Build status

Updated 2026-09-13.

## Green now

- Python project, locked dependencies, environment template
- Real, accelerated demo, and stepped simulation clocks
- SQLite data model with WAL, foreign keys, and a unique open-checkout constraint
- Per-item lock registry
- Pure demand model, expected-value price search, and liquidity frontier
- HOLD, REPRICE, COUNTER, ACCEPT, ESCALATE, EXPIRE, instant route, and payment timeout policy
- Guard checks for floor, deadline, terminal state, checkout, and monotonic price invariants
- Transactional executor, ledger writes, and idempotent outbox rows
- FastAPI health, plan, item creation, tick, and ledger endpoints
- Seeded market simulation across five policies, four deadlines, and three item archetypes
- Generated evaluation table and chart from 12,000 policy runs
- Unit, API, property, clock, demand, policy, and guard tests

## Ordered P0 queue

1. BlueBubbles webhook intake. Add the three-second photo and caption buffer.
2. Claude schemas for vision and seller or buyer intent, with deterministic fallbacks.
3. eBay Browse token cache, comps search, filtering, and market statistics.
4. Offer page and buyer offer ingestion.
5. Stripe checkout lifecycle and signature-verified webhook transitions.
6. Outbox delivery worker with retries and restart tests.
7. Shippo label and Google Calendar adapters behind the paid transition.
8. Dashboard with ledger stream, frontier, pipeline, countdown, and demo clock controls.
9. Scripted demo scenario, reset command, live smoke checks, and final eval artifacts.
10. Extend simulation with response latency and delayed settlement.

P1 eBay sandbox listing work remains behind the 13:30 feature gate from the original plan.

## Local setup blockers

- BlueBubbles is not installed.
- `.env` has not been created, so external service credentials are not configured.
- Stripe CLI and ngrok are not installed. Cloudflared is available for the public tunnel.
- Google Calendar OAuth client JSON is not present.

These do not block core, simulation, adapter, dashboard, or test development. They block live
end-to-end smoke tests for their respective services.
