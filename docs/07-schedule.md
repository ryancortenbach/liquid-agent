# 07 · Build schedule, Sunday 2026-09-13 (Pacific)

The official build window is 9:30 to 16:00. We will be at keyboards earlier for environment checks. Whether code is written before 9:30 is a rules question the team answers; this doc only says what to do in what order.

## Tracks
Four tracks. With fewer people, merge A with D and B with C.
- **A · Engine**: clock, models, demand, policy, guard, executor, scheduler, sim, tests
- **B · Conversation**: BlueBubbles adapter, router, vision, intent, buyer agent, seller voice, leak check
- **C · Money and logistics**: eBay Browse and comps, Stripe, Shippo, Calendar, offer page, outbox worker
- **D · Demo and brief**: dashboard, demo scenario and clock controls, smoke script, the brief, the video

## Timeline
| Time | A · Engine | B · Conversation | C · Money and logistics | D · Demo and brief |
|---|---|---|---|---|
| 07:00 | `scripts/smoke_all.py` skeleton; everyone runs it | BlueBubbles round trip from the seller's phone: text, photo, reply | Keys in `.env`; Stripe CLI listening; Shippo and Calendar smoke | ngrok up, webhook URLs pasted; recording setup tested |
| 08:00 | Repo skeleton, pyproject, config, clock, db, models, ledger | Adapter: inbound parse, attachment download, send text and image | eBay token and Browse search returning 50 XM5 comps | Dashboard shell with the SSE ledger stream |
| 09:30 | **Official start.** `demand.py` and `frontier.py` with unit tests against the worked example | `vision.py` and `intent.py` with Pydantic schemas; 10 intent cases passing | `comps.py` (Claude filter, M and σ); `fees.py` | `scenario.yaml` format; DemoClock pause and resume wired to the dashboard |
| 10:30 | `policy.py` decide() and actions; golden test for the 72h scenario | `router.py`: seller vs buyer, item resolution, 3s photo-and-caption buffer | Stripe: create session, webhook handler, expire; local test with the CLI and the declining card | Offer page: photos, price, buy now → Checkout |
| 11:30 | `guard.py`, `executor.py`, outbox rows; scheduler tick loop | `buyer_agent.py` and `leak_check.py`; `seller_voice.py` | Shippo label and Calendar insert behind the SOLD transition | Smoke table on the dashboard; brief skeleton filled with the architecture |
| 12:30 | **Integration checkpoint.** One photo from the seller's phone → frontier card → LIVE, in demo mode. Lunch at desks. | | | |
| 13:00 | `sim/world.py`, policies, `run.py`; first results table | End-to-end buyer thread: inquiry → counter → accept → pay link | P1 decision: eBay sandbox listing only if C is idle, else skip | Demo dry run with sim buyers only |
| 13:30 | **P0 feature freeze.** Hypothesis property tests; fix what they find | Escalation flow (P1) | Stripe polling fallback; outbox retries verified by killing the process mid-run | Full rehearsal with real teammate buyers |
| 14:15 | Chaos tests; eval report to `docs/eval/` | Copy polish on every template | Reset script; expire stray sessions | Rehearsal 2, timed |
| 14:45 | **Freeze. Nobody touches main.** | | | **Take 1** |
| 15:05 | LLM evals run; numbers into the brief | | | **Take 2** |
| 15:20 | Brief final: real vs modeled table, eval table, limitations | README pass | | Edit the video to 2:00 |
| 15:45 | Tag `v0.1-hackathon`; submit repo, video, brief | | | Upload |
| 16:00 | **Hard stop.** Judging. Keep the live system up for questions. | | | |

## Cut lines
- 12:30 checkpoint fails → drop dashboard polish and the eBay listing; D helps B.
- 13:30 and payments aren't green → the demo closes with a buyer texting "paid" and a manual SOLD command, disclosed on screen. Everything else stays.
- 14:15 and the sim isn't producing a table → present the golden tests and the invariants instead of the grid, and say so in the brief.

## Rules of the day
- Every merge to main runs `pytest -x` first. A red main is a stop-the-line event.
- No new dependencies after 13:30.
- Every number in a demo text must exist in a ledger row.
- If a track is blocked for 20 minutes, say so in chat and swap to the next item in its column.
