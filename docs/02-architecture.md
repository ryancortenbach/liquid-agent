# 02: Architecture

Python 3.12, FastAPI, SQLite, one process. Deterministic policy core with marketplace adapters at
the edges.

## System

```text
seller iPhone -> iMessage -> BlueBubbles -> FastAPI intake
                                             |
photos -> quality and identity -> listing pack
                                             |
                   +-------------------------+-------------------------+
                   |                         |                         |
              eBay API            Facebook assisted          other assisted
                   |                         |                         |
                   +---------- marketplace observations --------------+
                                             |
                           deterministic deadline engine
                                             |
                     sale claim and cross-channel delisting
                                             |
                                SQLite ledger and outbox
```

Buyers never connect to Liquid. Buyer identities and offers in the database are marketplace
observations, not Liquid accounts.

## Principles

1. `decide(state, now)` is pure and deterministic.
2. Every publish, reprice, reply, pause, and delist operation passes through the guard and outbox.
3. Real, demo, and simulation time share one clock interface.
4. One lock per item serializes ticks and marketplace events.
5. One active sale claim per item is enforced in SQLite.
6. Automated publishing uses approved APIs. Assisted publishing requires the seller's final action.
7. Photo enhancement may improve presentation but cannot change evidence about the item.
8. Model calls have deterministic fallbacks and never own prices or state transitions.

## Repository structure

```text
app/
  main.py
  config.py
  clock.py
  db.py
  models.py
  ledger.py
  channels/
    imessage_bluebubbles.py
  inbound/
    seller_router.py
    intent.py
    vision.py
  photos/
    quality.py
    studio.py
    truth_check.py
  market/
    ebay_auth.py
    ebay_browse.py
    ebay_sell.py
    comps.py
    fees.py
  publishing/
    base.py
    listing_pack.py
    ebay.py
    assisted_facebook.py
    assisted_craigslist.py
    assisted_offerup.py
  engine/
    state.py
    demand.py
    frontier.py
    actions.py
    policy.py
    guard.py
    executor.py
    scheduler.py
  fulfillment/
    shippo_client.py
    gcal_client.py
  outbox/
    worker.py
  web/
    dashboard.py
sim/
tests/
demo/
scripts/
```

## Core data

```text
Seller        handle, timezone, fulfillment address
Item          identity, condition, originals, enhanced assets, deadline, floor, market estimate,
              status, constraints
ListingPack   item, title, description, category, attributes, selected assets, truth-check result
Listing       item, channel, mode automated or assisted, external id, price, status, last reprice
Buyer         marketplace-scoped handle, channel, close reliability
Offer         item, buyer, channel, amount, direction, status, timestamps
SaleClaim     item, offer, channel, amount, ACTIVE or CONFIRMED or RELEASED, source
Shipment      marketplace or Shippo label and tracking
CalendarEvent pickup or drop-off event
LedgerEvent   simulated time, wall time, inputs, action, reason, prices
Outbox        side effect, idempotency key, retries, next attempt, result
WebhookReceipt provider and event id
DemandObs     views, saves, inquiries, offers, and order signals by channel
```

SQLite has a partial unique index allowing only one ACTIVE `SaleClaim` per item.

## State machine

```text
DRAFT -> IDENTIFIED -> ASSETS_READY -> PRICED -> READY_TO_PUBLISH -> LIVE
LIVE <-> ESCALATED
LIVE -> SALE_PENDING -> SOLD -> FULFILLMENT_READY -> DONE
SALE_PENDING -> LIVE              failed close releases the claim
LIVE -> EXPIRED                   deadline passed without an approved exit
any -> CANCELLED                  seller cancellation pauses or ends all listings
```

SOLD is terminal. A sale claim is created before an offer is accepted or a seller commits to a
local buyer. Creating it pauses all competing listings. Confirmation ends all listings. Release
resumes eligible listings.

## Seller intake flow

```text
BlueBubbles webhook
  -> ignore outbound messages and deduplicate
  -> buffer photo and caption events for three seconds
  -> parse seller intent
  -> inspect identity, condition, and photo quality
  -> request missing evidence or build truthful listing assets
  -> collect comps and create a channel plan
  -> send preview to seller
  -> publish approved channels
```

## Marketplace event flow

```text
poll or webhook -> normalize observation -> item lock -> load state -> decide -> guard -> executor
```

Automated adapters apply changes directly. Assisted adapters create an approval task with the
prepared fields and deep link. They never silently publish through a personal account.

## Configuration

```text
MODE=real|demo|sim
DEMO_CLOCK_SPEED=3600
TICK_SECONDS=2
PUBLIC_BASE_URL=
TZ=America/Los_Angeles
DATABASE_URL=sqlite:///data/liquid.db

ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-opus-5

BB_SERVER_URL=http://localhost:1234
BB_PASSWORD=
SELLER_HANDLE=

EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_SB_CLIENT_ID=
EBAY_SB_CLIENT_SECRET=
EBAY_SB_RUNAME=
EBAY_SB_REFRESH_TOKEN=

SHIPPO_API_KEY=
GOOGLE_OAUTH_CLIENT_JSON=./secrets/gcal_client.json
GOOGLE_TOKEN_JSON=./secrets/gcal_token.json
SELLER_FROM_ADDRESS_JSON=
```

## Local topology

- `uvicorn app.main:app --port 8000`
- `cloudflared tunnel --url http://localhost:8000` provides the public webhook URL
- BlueBubbles runs on the seller-side Mac
- eBay Browse uses production credentials for comps
- eBay Sell uses sandbox credentials for the demo
- Assisted marketplace flows run in the seller's existing browser session and stop at approval
