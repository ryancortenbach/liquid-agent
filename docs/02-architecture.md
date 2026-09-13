# 02 · Architecture

Python 3.12, FastAPI, SQLite. One process. Deterministic core, thin adapters at the edges.

## System diagram
```
 seller iPhone ──iMessage──▶ Mac running Messages.app + BlueBubbles server (:1234)
 buyer iPhones ─┘                          │ webhook POST /webhooks/bluebubbles
                                           ▼
                        ┌──────────────────────────────────────┐
  Stripe ──webhook──▶   │  FastAPI app (uvicorn, one process)  │ ◀── dashboard (SSE)
  eBay  ◀──REST──────   │                                      │
  Shippo◀──REST──────   │  inbound/  → intent, vision          │
  GCal  ◀──REST──────   │  engine/   → decide(state, now)      │  pure, deterministic
  Claude◀──SDK───────   │  guard     → invariants              │
                        │  executor  → DB txn + outbox rows    │
                        │  outbox    → adapters with retries   │
                        │  scheduler → tick every item         │
                        │  clock     → real | demo | sim       │
                        └──────────────┬───────────────────────┘
                                       ▼
                                 SQLite (WAL)  +  ledger
```

## Principles
1. **The engine is a pure function.** `decide(state, now) -> Action`. No I/O inside. Everything the judges care about is testable by replay.
2. **Every side effect goes through the guard, then the outbox.** The guard checks invariants; the executor writes the DB and an outbox row in one transaction; a worker delivers the side effect with retries and an idempotency key. If the process dies between the two, nothing is lost and nothing is duplicated.
3. **One clock.** `clock.now()` is the only source of time. Real, demo (accelerated, pausable), and sim (stepped) clocks share the interface. Deadline math never touches `datetime.now()`.
4. **One lock per item.** Ticks and webhooks for the same item serialize on an `asyncio.Lock`, then a DB transaction. This is what makes "no double sale" a property rather than a hope.
5. **Claude never blocks the engine.** Model calls happen in intake and in message rendering, each with a timeout and a deterministic template fallback.

## Repo skeleton
```
AFE/
  pyproject.toml              # python 3.12, deps listed below
  .env.example
  README.md
  docs/
  app/
    main.py                   # app factory, routers, startup: scheduler + outbox worker
    config.py                 # pydantic-settings; MODE, DEMO_CLOCK_SPEED, every key
    clock.py                  # Clock protocol; RealClock, DemoClock(speed, pausable), SimClock(step)
    db.py                     # SQLModel engine (WAL), session helper, per-item lock registry
    models.py                 # tables below
    ids.py                    # ULIDs
    ledger.py                 # write_decision(item_id, action, inputs, reason, price_before, price_after)
    channels/
      base.py                 # ChannelAdapter: send_text(handle, text), send_image(handle, path), parse_inbound(payload)
      imessage_bluebubbles.py # P0: webhook receiver + REST sender
      imessage_chatdb.py      # fallback A: chat.db poller + osascript sender
      sms_twilio.py           # fallback B
    inbound/
      router.py               # seller or buyer? which item? dispatch to intent handlers
      intent.py               # Claude structured output → SellerIntent | BuyerIntent
      vision.py               # Claude vision → ItemIdentity
    market/
      ebay_auth.py            # client-credentials token cache (Browse); user token + refresh (Sell)
      ebay_browse.py          # item_summary/search → raw comps
      ebay_sell.py            # inventory item → offer → publish → price update (P1)
      comps.py                # Claude filter → M, sigma, n, comp list for the ledger
      fees.py                 # per-channel fee and shipping models
    engine/
      state.py                # ItemState assembled from DB rows; frozen dataclass
      demand.py               # WTP model, Gamma-Poisson arrival posterior, P(sale | p, tau)
      frontier.py             # liquidity frontier
      policy.py               # decide(state, now) → Action
      actions.py              # Action union types
      guard.py                # invariants; raises InvariantViolation
      executor.py             # apply Action: DB writes + outbox rows in one txn
      scheduler.py            # tick loop over live items
    negotiation/
      buyer_agent.py          # Claude drafts buyer replies inside engine-set bounds
      seller_voice.py         # Claude renders seller check-ins from a ledger row
      leak_check.py           # rejects drafts that reveal floor, deadline, other offers
    payments/
      stripe_client.py        # create session, expire session
      stripe_webhook.py       # verify signature, dedupe on event id, dispatch under item lock
    fulfillment/
      shippo_client.py        # shipment → rates → label
      gcal_client.py          # events.insert
      offer_page.py           # public per-item page (photos, price, make an offer, buy now)
    outbox/
      worker.py               # delivers side effects; exponential backoff; idempotency keys
    web/
      dashboard.py            # SSE ledger stream, frontier, buyers, countdown, clock controls
      templates/
  sim/
    world.py                  # seeded market: arrivals, WTP, ghosts, payment failures, latency
    policies.py               # agent, static_list, static_90, linear_markdown, oracle
    run.py                    # grid runner → results.csv
    report.py                 # table + chart → docs/eval/
  evals/
    vision_cases/             # photos + expected identity
    intent_cases.jsonl        # utterance → expected JSON
    leak_cases.jsonl          # drafts that must be rejected
    run_llm_evals.py
  tests/
    test_invariants.py        # hypothesis property tests over random event sequences
    test_policy.py            # golden decisions for the pitch scenarios
    test_webhooks.py          # duplicates, out-of-order, bad signatures
    test_chaos.py             # adapter failures, retries, restarts
  demo/
    scenario.yaml             # scripted sim buyers layered over real buyers
    run_demo.py               # boots MODE=demo with the scenario
    reset.py                  # wipe item state, expire open Stripe sessions
  scripts/
    smoke_all.py              # pings every external app, prints a table
    ebay_user_auth.py         # one-time Sell OAuth (sandbox)
    gcal_auth.py              # one-time Calendar OAuth
```

## Data model
```
Seller        id, handle (iMessage address), name, tz, from_address_json
Item          id, seller_id, title, brand, model, category, condition (A|B|C), confidence,
              photo_paths[], deadline_at (sim), floor_cents, floor_source (seller|derived),
              constraints_json {local_only, ship_ok, instant_ok}, market_value_cents, sigma_cents,
              comps_n, status, escalated_at, created_at
Listing       id, item_id, channel (ebay|local|instant), external_id, price_cents, status,
              published_at, last_reprice_at
Buyer         id, handle, channel, name, pay_reliability (0..1), failed_count
Offer         id, item_id, buyer_id, amount_cents, direction (in|out), status
              (open|countered|accepted|declined|expired|superseded), created_at, expires_at
Checkout      id, item_id, buyer_id, stripe_session_id, amount_cents, status
              (open|paid|failed|expired), opened_at, window_ends_at, paid_event_id
Shipment      id, item_id, shippo_transaction_id, label_url, tracking, carrier, rate_cents
CalendarEvent id, item_id, gcal_event_id, starts_at
LedgerEvent   id, item_id, sim_at, wall_at, kind (tick|inbound|webhook|seller|system),
              action, inputs_json, reason, price_before, price_after
Outbox        id, kind, payload_json, idempotency_key (unique), attempts, next_at, done_at, error
WebhookReceipt provider, event_id (pk), received_at
DemandObs     id, item_id, channel, kind (view|inquiry|offer), sim_at, value
```

## Item state machine
```
DRAFT → IDENTIFIED → PRICED → LIVE ⇄ PENDING_PAYMENT → SOLD → LABELED → SCHEDULED → DONE
LIVE → ESCALATED → LIVE            (waiting on the seller, engine keeps ticking but won't accept below floor)
LIVE → EXPIRED                     (deadline passed unsold; or ROUTE_INSTANT if instant_ok)
any  → CANCELLED                   (seller said cancel; open checkout expired via Stripe)
```
SOLD is terminal for sales. Nothing after SOLD can change the buyer or the amount.

## Inbound flow
```
webhook → parse_inbound → router
  from seller handle?  → intent.parse_seller → (new item: vision → comps → frontier → PRICED → LIVE)
                                              → (command: floor/extend/cancel/status/take it/wait → re-plan)
  from anyone else?    → which item? (one live item per buyer thread; else ask) → intent.parse_buyer
                         → DemandObs(inquiry) + Offer(in) → engine tick for that item now
```

## Tick flow
```
scheduler every TICK_SECONDS:
  for item in LIVE | PENDING_PAYMENT | ESCALATED:
    async with lock(item):
      state = load_state(item)                 # one read
      action = policy.decide(state, clock.now())
      guard.check(action, state)               # raises → ledger row kind=system, no side effect
      executor.apply(action, state)            # DB + outbox in one txn + ledger row
```

## Clock
```python
class Clock(Protocol):
    def now(self) -> datetime: ...          # simulated time
    def wall(self) -> datetime: ...         # real time (for logs)
RealClock: now == wall
DemoClock(speed=3600, start=...): now = start + (wall - wall_start) * speed, minus paused spans
SimClock: advance(hours) explicitly; used by sim/ and tests
```
All timestamps in the DB are simulated time; `wall_at` is stored alongside on ledger rows.

## Config (.env)
```
MODE=real|demo|sim
DEMO_CLOCK_SPEED=3600               # 1 real second = 1 simulated hour
TICK_SECONDS=2
PUBLIC_BASE_URL=https://xxxx.ngrok.app
TZ=America/Los_Angeles

ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-opus-5

BB_SERVER_URL=http://localhost:1234
BB_PASSWORD=
SELLER_HANDLE=+1415XXXXXXX           # the seller's own iMessage address for the demo

EBAY_CLIENT_ID=                      # production keyset, Browse only
EBAY_CLIENT_SECRET=
EBAY_SB_CLIENT_ID=                   # sandbox keyset, Sell (P1)
EBAY_SB_CLIENT_SECRET=
EBAY_SB_RUNAME=
EBAY_SB_REFRESH_TOKEN=

STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

SHIPPO_API_KEY=shippo_test_...

GOOGLE_OAUTH_CLIENT_JSON=./secrets/gcal_client.json
GOOGLE_TOKEN_JSON=./secrets/gcal_token.json

SELLER_FROM_ADDRESS_JSON={"name":"...","street1":"...","city":"...","state":"CA","zip":"...","country":"US","phone":"..."}
```

## Dependencies
fastapi, uvicorn, sqlmodel, pydantic-settings, anthropic, httpx, stripe, shippo, google-api-python-client, google-auth-oauthlib, tenacity, python-ulid, jinja2, sse-starlette, numpy, pyyaml · dev: pytest, pytest-asyncio, hypothesis, matplotlib, ruff

## Local dev topology
- `uvicorn app.main:app --port 8000`
- `ngrok http 8000` (or `cloudflared tunnel --url http://localhost:8000`) gives PUBLIC_BASE_URL; paste into BlueBubbles webhooks and Stripe
- `stripe listen --forward-to localhost:8000/webhooks/stripe` during dev; a real Stripe webhook endpoint on the ngrok URL for the demo so the laptop's CLI isn't a dependency
- BlueBubbles server runs on the same Mac; Messages.app signed into the agent's dedicated Apple ID
