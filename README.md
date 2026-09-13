# Liquid

**Take a picture. Set a deadline. Get it listed everywhere it can sell.**

Entry for the [Multi-App AI Agent Hackathon](https://multiappagenthackathon.com), Sunday,
September 13, 2026.

Liquid is a seller-only agent for regular people who want to sell an item quickly without
looking careless or suspicious. The seller texts photos and a deadline. Liquid identifies the
item, checks and improves the listing photos without changing the item itself, writes a credible
listing, estimates the market, and publishes to supported marketplaces. It monitors demand,
reprices as the deadline approaches, compares offers, and prevents the same item from being sold
twice.

Buyers never join Liquid. They discover and purchase the item through eBay, Facebook Marketplace,
Craigslist, OfferUp, or another existing marketplace. Liquid does not run a buyer marketplace and
does not process buyer payments.

> Marketplaces provide buyers. Liquid gives ordinary sellers a professional selling operation.

## Channel model

| Channel | Publishing mode |
|---|---|
| eBay | Automated through the official Inventory API. Sandbox for the hackathon demo. |
| Facebook Marketplace | Assisted. Liquid prepares and fills the listing, then the seller approves publication. |
| Craigslist and OfferUp | Assisted until an approved API or partner integration is available. |
| Other channels | Added through adapters with explicit capability and policy checks. |

## External apps

iMessage via BlueBubbles, OpenAI for product-photo editing, eBay, assisted marketplace browser
flows, Google Calendar, Shippo when a marketplace does not provide the label, and Claude for item
analysis, listing copy, and seller messages.

## Docs

| File | What it defines |
|---|---|
| [docs/00-brief.md](docs/00-brief.md) | Hackathon brief, rubric, and scoring strategy |
| [docs/01-product.md](docs/01-product.md) | Seller-only product and feature priorities |
| [docs/02-architecture.md](docs/02-architecture.md) | Architecture, data model, and state transitions |
| [docs/03-engine.md](docs/03-engine.md) | Deadline pricing and cross-channel offer policy |
| [docs/04-integrations.md](docs/04-integrations.md) | Marketplace and seller-interface integrations |
| [docs/05-reliability.md](docs/05-reliability.md) | Invariants, tests, evaluation, and disclosure |
| [docs/06-demo.md](docs/06-demo.md) | Two-minute seller workflow demo |
| [docs/07-schedule.md](docs/07-schedule.md) | Build order and cut lines |
| [docs/08-setup.md](docs/08-setup.md) | Accounts, keys, and local setup |
| [docs/09-brief-template.md](docs/09-brief-template.md) | Submission brief template |
| [docs/10-build-status.md](docs/10-build-status.md) | Current implementation and next work |
| [docs/11-collaboration.md](docs/11-collaboration.md) | Independent branch workflow for collaborators |

## Local development

```bash
uv sync
uv run pytest
uv run python scripts/run_local.py --reload
```

Open `http://localhost:8000/docs` for the API. `POST /api/plan` previews a liquidity
frontier. `POST /api/items` creates an item, and `POST /api/items/{item_id}/tick` runs the
guarded decision path shared by real, demo, and simulation clocks.

For the photo flow, set `OPENAI_API_KEY`, upload an image to
`POST /api/items/{item_id}/photos/enhance`, compare the returned original and enhanced URLs, then
approve or reject it through `POST /api/items/{item_id}/photos/{photo_id}/review`. Enhanced photos
never enter the listing image set before approval.

For iMessage, configure BlueBubbles and the webhook values described in `docs/08-setup.md`. A
seller can then text a photo and caption, receive the original and enhanced versions, and reply
`APPROVE` or `REJECT` without using the API directly.

Attach several photos normally to use them as angles of one item. To submit several items at once,
start the caption with `BATCH` and attach one primary photo per item. If items have several angles,
use counts such as `BATCH 2+3`, where the first two attachments are item 1 and the next three are
item 2. Liquid accepts corrections such as `2 is Bose QC45`, reviews the generated set together,
and then walks through the listings one item at a time.

A single photo containing several products is also treated as an inventory scene. Liquid detects
and crops each sellable object, presents a numbered checklist, and creates one item per confirmed
object. Reply `REMOVE 3` to exclude something that is not for sale, or rename it with `3 is ...`.
The uncropped source image is retained for auditability.

The eBay sandbox path is `POST /api/items/{item_id}/publish/ebay`. It creates a draft from approved
photos first. The offer is published only when the request explicitly includes
`"seller_approved": true`, and Liquid marks it live only after eBay returns a listing id. Three
scripts take a fresh sandbox keyset to a verified listing: `scripts/ebay_authorize.py` mints the
refresh token (paste the redirect URL, no public callback needed), `scripts/ebay_setup.py` creates
the business policies and ship-from location and writes their ids to `.env`, and
`scripts/ebay_verify.py --publish` proves comps, category, auth, photo hosting, draft, publish,
reprice, and cleanup live. Photos are hosted on eBay Picture Services at publish time, so no
tunnel is required. Details in `docs/08-setup.md`.

If eBay developer approval is still pending, set `EBAY_DEMO_MODE=true`. Seller onboarding then
completes locally, the rest of the real workflow remains active, and publication returns a working
Liquid-hosted listing preview with an explicit demo disclosure. Turning the flag off restores the
normal per-seller OAuth and official eBay publishing path.

At any point in Messages, `STATUS` reports progress, `RESUME` repeats the next step, `BACK`
explains how to revise the current step, and `START OVER` cancels the active draft safely.
With `OPENAI_CHAT_ENABLED=true`, a structured intent layer uses the saved workflow state and recent
seller messages to understand conversational requests and references. The deterministic workflow
still owns onboarding, photo approval, listing approval, and publishing. Each seller's messages are
processed serially so delayed BlueBubbles deliveries cannot trigger duplicate replies.

After eBay onboarding, reply `CONNECT EMAIL` to connect the seller's Gmail account. Liquid watches
authenticated eBay and Facebook Marketplace mail for offers and sold events, deduplicates messages,
and matches them to the seller's listings. Safe matches update the offer or sale state. Ambiguous
messages ask for review. Alerts arrive through both Gmail and iMessage, and every successful eBay
publication includes the returned live listing URL in both channels. Gmail setup and public OAuth
verification requirements are in `docs/08-setup.md`.

For per-seller OAuth, configure the eBay application credentials, RuName, `APP_SECRET`, and a
public `PUBLIC_BASE_URL`. Every seller is placed into eBay onboarding on their first text, and
Liquid processes nothing until they approve access. Liquid stores only an encrypted refresh token
for that seller and resolves their connection when publishing. The link expires after 10 minutes,
and `RETRY` issues a fresh one. A shared sandbox refresh token can verify the developer setup, but
it never bypasses seller onboarding.

## Submission

- **What we built.** Liquid, a seller-only listing agent that lives in iMessage. Text a photo and a
  sentence; it identifies the item, makes a truthful listing photo, asks two short questions, pulls
  sold and active comps, prices for the deadline you chose, writes the listing, shows you a card
  with every source, publishes to eBay on "go", hands you copy-ready posts for Facebook Marketplace
  and OfferUp, and steps the price down your schedule as time passes.
- **One orchestrator.** The seller router and listing flow orchestrate every step; vision, research,
  pricing, listing copy, and publishing are tools it calls in sequence with a ledger row each.
- **External apps.** iMessage through BlueBubbles, OpenAI for item identification and the truthful photo edit, Apify's eBay
  sold and active listing actors for comps, eBay (Browse API in production for comps, Sell API in
  the sandbox for publishing and repricing), Claude optionally for listing copy polish. Sandbox
  and test environments are used where a marketplace offers them.
- **Demo video (2 minutes).** _link to be added before submission_
- **Run it.** `uv sync --all-extras`, copy `.env.example` to `.env`, then `uv run uvicorn app.main:app`.
  Open `/dashboard`. Without iMessage: `uv run python demo/run_demo.py --photo photo.jpg` drives the
  whole path over the API. `uv run python scripts/smoke_research.py "iPad Air 5th gen 64GB"` checks
  the comps sources.

## How we test reliability

- `uv run pytest`: unit, API, property (Hypothesis), clock, simulation, sale-claim, photo, iMessage,
  research, pricing, intake, listing-flow, repricing, and dashboard tests.
- **Invariants enforced in code**: no listing price below the seller's floor; nothing publishes
  without the seller's "go"; the enhanced photo never replaces the original and needs approval;
  every price and claim traces to a ledger row with its sources; publishing is idempotent.
- **Simulation**: `sim/` runs the deadline pricing engine against a seeded market and writes
  `docs/eval/results.md`; the same engine prices real items.
- **Honest labeling**: offline comps are marked "offline sample data" on the card; the eBay pack is
  marked failed with the reason when the sandbox is not configured, never silently skipped.
- **Known limitations**: Facebook Marketplace and OfferUp have no posting APIs, so those are
  copy-ready handoffs the seller pastes; eBay sold data is scraped through Apify rather than an
  official API; identification needs a clear photo of the actual item.
