# 07: Build schedule

## Tracks

- Engine and evaluation: pricing, deadlines, sale claims, ledger, simulation, tests
- Seller and photos: BlueBubbles, intake, image editing, review, listing copy
- Marketplaces: eBay listing, assisted Facebook flow, adapter contracts
- Demo and reliability: dashboard, scenario, smoke checks, recording, submission brief

## Build order

| Priority | Deliverable | Completion test |
|---|---|---|
| P0 | Truthful photo enhancement | Original and generated photo shown side by side. Seller approval required. |
| P0 | Seller intake | One photo and one sentence create a draft item. |
| P0 | eBay sandbox listing | Approved listing pack publishes and stores its listing id. |
| P0 | Assisted Facebook listing | Fields and photos are prepared, then publication stops for seller approval. |
| P0 | Cross-channel sale claim | A pending sale pauses duplicates. Failure resumes them. Confirmation ends them. |
| P0 | Demo dashboard | Photo review, listing state, deadline, and ledger are visible. |
| P0 | Recorded demo | Complete two-minute flow works without live buyer participation. |
| P1 | Additional channels | Craigslist and OfferUp use the same assisted contract. |
| P1 | Fulfillment | Marketplace label or optional Shippo flow, plus Calendar event. |

## Cut lines

- If marketplace credentials lag, keep the image workflow real and use eBay sandbox fixtures.
- If BlueBubbles is blocked, use direct photo upload without changing the product story.
- If assisted browser publication is unreliable, stop at the completed listing preview and show the
  seller approval boundary.
- Do not cut original retention, seller review, floor enforcement, or double-sale prevention.

## Rules

- Run `pytest -x` before every merge.
- Every generated image keeps a link to its original and the exact edit prompt.
- Never publish an enhanced image before seller approval.
- Every price or listing-state change must have a ledger row.
