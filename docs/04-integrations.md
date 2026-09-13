# 04: Integrations

## Seller interface: iMessage through BlueBubbles

BlueBubbles receives the seller's photos and instructions and sends previews, approvals, and
status messages. It is not exposed to buyers. Photo and caption events are buffered for three
seconds before parsing.

Writes are delivered through the outbox with idempotency keys and retry backoff. The fallback is
a read-only Messages database poller plus AppleScript sending, after the user grants Full Disk
Access.

## Photo pipeline

Each item keeps immutable originals and separate listing assets.

1. Check blur, exposure, resolution, background clutter, duplicate angles, and coverage.
2. Ask for missing evidence such as labels, serial plate, ports, soles, corners, or known damage.
3. Use the OpenAI Image API to crop, straighten, balance exposure, and clean the background.
4. Preserve color, proportions, wear, scratches, stains, dents, and included accessories.
5. Compare every generated asset with the original and reject material changes.
6. Select a truthful hero image and channel-specific image order.

The default editor is `gpt-image-2.5-sunburst`, selected for editing precision. Each generated
asset stores its source photo, SHA-256 hash, exact prompt, model, preset, disclosure, and seller
review state. Only `approved` assets are eligible for publication, and the original remains in the
listing image set.

## eBay

### Comps

Use the production Browse API with a client-credentials token. Search used fixed-price listings,
filter mismatches, and calculate the median active ask times the disclosed realization haircut.
Widen once when fewer than five valid comps remain.

### Listing

Use the official Inventory API. The seller account needs business policies and an inventory
location. The flow is:

1. Create or replace the inventory item.
2. Create the offer with category, price, quantity, location, and policy ids.
3. Show the seller the final listing pack.
4. Publish in sandbox for the demo.
5. Publish in production only after explicit seller approval.
6. Store the listing id for repricing, pausing, and ending.

## Facebook Marketplace

Facebook Marketplace is an assisted channel for ordinary personal sellers. Liquid creates the
title, description, price, category, condition, location, and photo order. It opens and fills the
seller's listing flow, then stops for final review and publication by the seller.

Liquid does not claim a public Marketplace listing API and does not silently automate a personal
Facebook account. The listing record stores `mode=assisted`, the seller approval, and the final URL.

## Craigslist and OfferUp

These use the same assisted-publishing contract until approved integrations are available. Liquid
prepares the listing and deep link, records seller approval, and stores the resulting listing URL.

## Marketplace observations

Each adapter normalizes supported signals into views, saves, inquiries, offers, accepted offers,
orders, cancellations, and seller-confirmed local sales. Unsupported signals can be entered by the
seller with a short message such as `facebook offer 187` or `sold on marketplace for 198`.

## Seller email alerts

Each seller can reply `CONNECT EMAIL` in iMessage after eBay onboarding. Liquid uses a signed,
10-minute Google OAuth link and stores only that seller's encrypted Gmail refresh token. It polls
for new eBay and Facebook Marketplace notifications, deduplicates by Gmail message id, and parses
offer and sold events. Known sender domains plus passing Gmail authentication results are required
before an event changes marketplace state. An uncertain sender, amount, or item match produces a
review alert instead of changing the item.

Authenticated offers are added to the deterministic offer engine. An authenticated sold message
that matches a listing id or item title marks the item sold and ends its other active listings.
Every detected event is stored without retaining the full email body. Alerts go to iMessage and
the connected Gmail address. After eBay returns a live listing id, Liquid sends the exact listing
URL through both channels.

## Claude

Structured model calls provide item identity, condition notes, seller intent, comps filtering,
photo-quality assessment, listing copy, marketplace response drafts, and seller explanations.
OpenAI image editing produces the improved listing images.

The deterministic engine owns every number and action boundary. The model may not invent prices,
hide defects, add accessories, or publish without the required approval.

## Fulfillment

- Use the marketplace's label and order details when available.
- Use Shippo only when the marketplace does not provide fulfillment and the seller chooses shipping.
- Add the pickup or drop-off to Google Calendar.
- Liquid never collects buyer payment or acts as escrow.

## Smoke checks

`scripts/smoke_all.py` reports core database, BlueBubbles, eBay Browse, eBay Sell, Shippo, Calendar,
and Claude readiness. Missing credentials are reported by name without printing their values.
