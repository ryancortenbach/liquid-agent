# 12: Listing pipeline (after the photo step)

Owner: `spectrrt/listing-pipeline`. Everything from the seller's photo approval to live listings.

## Conversation
1. Photo review ends (APPROVE or REJECT) → the flow asks question set one: condition (1 to 4), what is
   included, anything a buyer should know.
2. Question set two: speed (1 day, 3 days, week, month, hold), floor (a number or "you decide"),
   ship / local / both with a zip, and where to list (all, or pick).
3. Research runs, the price schedule is solved, the draft is written, and the seller gets the card:
   title, condition, list price and markdown steps, floor, platforms, comps counts and medians,
   source links, the guaranteed-now reference.
4. `go` publishes to the eBay sandbox and sends copy-ready handoffs for Facebook Marketplace and
   OfferUp (plus a CSV for form-filler extensions). Any other reply is a change ("floor 250",
   "1 day", "ebay only") and the card is rebuilt. `cancel` stops.

Free text fills several fields at once; only missing fields are asked; blanks take defaults.

## Modules
- `app/intake/details.py`: parsers, defaults, question sets
- `app/intake/flow.py`: `ListingFlow` (state machine over `SellerConversation.status`)
- `app/intake/router.py`: `PipelineRouter` wraps the photo router
- `app/research/`: Apify eBay sold and active actors, eBay Browse, fixture source, aggregation
- `app/pricing/schedule.py`: horizon → list price, markdown steps, floor suggestion
- `app/listing/draft.py`: grounded template, optional Claude polish that must keep every issue
- `app/listing/pack.py`, `app/listing/handoff.py`: per-channel packs, Facebook/OfferUp handoff
- `app/market/publish_service.py`: eBay sandbox publish shared by the endpoint and the flow

## Endpoints (for the dashboard and for running without iMessage)
`POST /api/items/{id}/details` `{text}` · `POST /api/items/{id}/plan-listing` `{research}` ·
`POST /api/items/{id}/go` · `GET /api/items/{id}/packs`

## Configuration
`APIFY_TOKEN` (sold and active comps), `EBAY_CLIENT_ID/SECRET` (Browse comps), `RESEARCH_MODE`
(`auto` uses real sources when keys exist, `fixture` uses the labeled offline sample, `off`),
`HANDOFF_DIR`, `ANTHROPIC_API_KEY` (copy polish), plus the `EBAY_SB_*` sandbox values.

## Honesty rules
- Fixture comps are labeled in every source row and the card says "offline sample data".
- The description only contains what the seller said, what vision found, and what comps carry.
- No publish without `go`; the eBay pack is marked failed with the reason when the sandbox is not
  configured, never silently skipped.
