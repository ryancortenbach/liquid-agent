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
uv run uvicorn app.main:app --reload
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

The eBay sandbox path is `POST /api/items/{item_id}/publish/ebay`. It creates a draft from approved
photos first. The offer is published only when the request explicitly includes
`"seller_approved": true`, and Liquid marks it live only after eBay returns a listing id.
