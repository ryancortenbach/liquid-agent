# 04 · Integrations

Every adapter has timeouts, tenacity retries with backoff, an idempotency key on writes, and one line in `scripts/smoke_all.py`. Nothing here is called from inside `engine/policy.py`.

## 1 · iMessage via BlueBubbles (P0)
BlueBubbles is an open-source macOS server app that watches Messages.app and exposes a REST API plus webhooks. It runs on the Mac that is signed into the agent's Apple ID.

**Mac setup** (click path in docs/08-setup.md)
- A dedicated Apple ID for the agent, signed into Messages.app on the Mac. An email handle is enough; no phone number needed. The seller and buyers text that address.
- Full Disk Access for BlueBubbles (it reads `~/Library/Messages/chat.db`). Accessibility is optional (Private API features) and we don't need it.
- The Mac must not sleep: `caffeinate -dims` in a terminal for the day.
- Default port 1234. Set a server password in the BlueBubbles settings.

**Auth**: every request takes `?password=<server password>` (aliases `guid`, `token`).

**Webhook, BlueBubbles → us**: Settings → Webhooks → add `${PUBLIC_BASE_URL}/webhooks/bluebubbles`, event "New Messages". Payload:
```json
{"type": "new-message",
 "data": {"guid": "...", "text": "sell this by sunday 6pm", "isFromMe": false,
          "dateCreated": 1772642539012,
          "handle": {"address": "+14155551234", "service": "iMessage"},
          "chats": [{"guid": "iMessage;-;+14155551234"}],
          "attachments": [{"guid": "...", "mimeType": "image/jpeg", "transferName": "IMG_0001.jpeg"}]}}
```
- Ignore `isFromMe`. `text` may be empty for a photo-only message, and a photo and its caption can arrive as two events a few seconds apart, so the router buffers a seller thread for 3 seconds before parsing.
- Attachment bytes: `GET /api/v1/attachment/{guid}/download?password=…` → save under `data/photos/{item_id}/`. HEIC arrives as HEIC; convert with `pillow-heif` before sending to Claude.

**Send text**: `POST /api/v1/message/text?password=…`
```json
{"chatGuid": "iMessage;-;+14155551234", "tempGuid": "<uuid4>", "message": "got it…", "method": "apple-script"}
```
`method: apple-script` needs no Private API. The docs' Python example uses a `text` key while the REST reference says `message`; confirm which the installed version accepts during the smoke test and pin it.
**Send image**: `POST /api/v1/message/attachment?password=…`, multipart fields `chatGuid`, `tempGuid`, `name`, `attachment` (file).
**New buyer thread**: `POST /api/v1/chat/new` with `{"addresses": ["+1…"], "message": "…"}`. Verify in the Postman collection. The fallback is to reply only to buyers who text first, which is all the demo needs.
**Chat guid**: for a DM, `iMessage;-;<address>`. Always prefer the `chats[0].guid` from the inbound event.

**Failure modes**
- BlueBubbles down → outbox retries (1s, 4s, 16s, 60s, …); the dashboard shows the channel red.
- Missed webhook → belt and braces: every 10s, `POST /api/v1/message/query` with `{"limit": 25, "sort": "DESC", "with": ["chats", "attachments", "handle"]}` and process anything newer than the last seen ROWID.
- Keep outbound to at most one message per second per thread.

**Fallback A** (about 30 minutes): `channels/imessage_chatdb.py` polls `~/Library/Messages/chat.db` for new `message` rows joined to `handle` and `attachment`. On modern macOS the text often lives in `attributedBody` (a typedstream blob) rather than `text`; parse it the way the `imessage_tools` project does. Send with `osascript -e 'tell application "Messages" to send "…" to participant "+1…" of (1st account whose service type = iMessage)'`. Needs Full Disk Access for the terminal that runs Python.
**Fallback B** (about 30 minutes): Twilio SMS/MMS. Green bubbles, verified numbers only on a trial account.

## 2 · eBay
Two keysets, two purposes.

### Comps: Browse API, production keyset, no user login
- Token: `POST https://api.ebay.com/identity/v1/oauth2/token` with header `Authorization: Basic base64(client_id:client_secret)` and body `grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope`. Valid two hours; cache in memory with a five-minute margin.
- Search: `GET https://api.ebay.com/buy/browse/v1/item_summary/search?q=sony+wh-1000xm5&filter=conditions:{USED},buyingOptions:{FIXED_PRICE},priceCurrency:USD&limit=50` with `Authorization: Bearer <token>` and `X-EBAY-C-MARKETPLACE-ID: EBAY_US`.
- Response `itemSummaries[]`: `title`, `price.value`, `condition`, `conditionId`, `itemWebUrl`, `shippingOptions[].shippingCost.value`, `image.imageUrl`, `itemLocation.postalCode`.
- Sandbox Browse returns nonsense data. Comps always use production.
- Sold prices are not available (Marketplace Insights is gated), so `M = median(active used asks) × 0.92`. Disclosed in the brief as a modeled realization haircut.
- `comps.py`: Claude filters the 50 summaries down to the same model and condition class (drops "for parts", bundles, cases, ear pads) and returns kept ids with a one-line reason each. Then numpy median and IQR. If fewer than 5 comps survive, widen the query once (drop the color or variant), then fall back to Claude's own estimate flagged `confidence=low` with a wider σ.

### Listing: Sell Inventory API, sandbox keyset, user login (P1, time-boxed to 60 minutes)
- OAuth authorization-code flow with a RuName redirect, scopes `https://api.ebay.com/oauth/api_scope/sell.inventory` and `…/sell.account`. `scripts/ebay_user_auth.py` runs it once and stores the refresh token.
- One-time seller setup in sandbox, each step of which has bitten people: `POST /sell/account/v1/program/opt_in` with `{"programType": "SELLING_POLICY_MANAGEMENT"}` (the sandbox website's opt-in page redirects to production; use the API), then create one fulfillment, one payment, and one return policy through the Account API, then `POST /sell/inventory/v1/location/{merchantLocationKey}`.
- Per item: `PUT /sell/inventory/v1/inventory_item/{sku}` (condition enum, product title, description, imageUrls, availability 1) → `POST /sell/inventory/v1/offer` (sku, marketplaceId EBAY_US, format FIXED_PRICE, categoryId, listingPolicies with all three policy ids, merchantLocationKey, pricingSummary.price) → `POST /sell/inventory/v1/offer/{offerId}/publish` → listingId.
- Reprice: `PUT /sell/inventory/v1/offer/{offerId}` with the new price.
- Known errors: publish fails without merchantLocationKey; errorId 25009 means the return policy is missing a return option.
- If not green by 12:00, eBay stays comps-only and the listing channel in the demo is the local offer page. That is still a real eBay integration.

## 3 · Stripe (test mode)
- Create: `stripe.checkout.Session.create(mode="payment", line_items=[{"price_data": {"currency": "usd", "unit_amount": 19800, "product_data": {"name": "Sony WH-1000XM5 (good)", "images": [...]}}, "quantity": 1}], success_url=f"{BASE}/o/{item}/paid?s={{CHECKOUT_SESSION_ID}}", cancel_url=f"{BASE}/o/{item}", client_reference_id=checkout_id, metadata={"item_id": ..., "buyer_id": ..., "checkout_id": ...}, shipping_address_collection={"allowed_countries": ["US"]}, expires_at=now + 30 min)`. Stripe's minimum `expires_at` is 30 minutes after creation; the engine's own payment window is shorter and enforced by us.
- Webhooks at `POST /webhooks/stripe`, verified with `stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)`:
  - `checkout.session.completed` → under the item lock: the checkout must be `open` and `amount_total ≥ agreed` → SOLD. Idempotent on `event.id` (WebhookReceipt) and on `session.id`.
  - `payment_intent.payment_failed` (a card decline on the hosted page; `last_payment_error.code == "card_declined"`) → buyer dropped, re-route. This is the demo's failure beat.
  - `checkout.session.expired` → buyer dropped if the checkout is still `open`.
  - `checkout.session.async_payment_failed` handled the same way for completeness.
- Expire: `stripe.checkout.Session.expire(session_id)`. The guard calls it before issuing any new checkout for the same item (invariant I2).
- Local dev: `stripe listen --forward-to localhost:8000/webhooks/stripe`. Demo: a real webhook endpoint on the ngrok URL so the CLI isn't a dependency.
- Test cards: `4242 4242 4242 4242` succeeds · `4000 0000 0000 0002` declines (the failure beat) · `4000 0000 0000 9995` insufficient funds.
- Payment Links are a drop-in alternative if Checkout Sessions misbehave; same webhooks.

## 4 · Shippo (test mode)
- `pip install shippo`; `sdk = shippo.Shippo(api_key_header=SHIPPO_API_KEY)` with a `shippo_test_…` key.
- `shipment = sdk.shipments.create(address_from=SELLER_FROM_ADDRESS, address_to=buyer_address, parcels=[{"length": "10", "width": "8", "height": "4", "distance_unit": "in", "weight": "2", "mass_unit": "lb"}], async_=False)`. Parcel dimensions come from a small category table.
- Pick the cheapest ground rate from `shipment.rates` (USPS Ground Advantage or UPS Ground), then `tx = sdk.transactions.create(rate=rate.object_id, label_file_type="PDF", async_=False)` → `tx.label_url`, `tx.tracking_number`, `tx.tracking_url_provider`. Test labels are watermarked but real PDFs.
- The buyer address comes from `shipping_details` on the completed Stripe session, or from the buyer's text for local pickup (then no label; the calendar event is a pickup instead).

## 5 · Google Calendar
- `google-api-python-client` + `google-auth-oauthlib`; scope `https://www.googleapis.com/auth/calendar.events`; `scripts/gcal_auth.py` runs `InstalledAppFlow` once and stores the token.
- `service.events().insert(calendarId="primary", body={"summary": "drop off: sony xm5 (ups)", "location": "<carrier drop-off or pickup address>", "description": "buyer: jordan · $198 · label: <url> · tracking: <n>", "start": {"dateTime": ..., "timeZone": TZ}, "end": {...}, "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60}]}}).execute()`.
- Time: shipped → next day 10:00 local; pickup → the time agreed in the buyer thread.

## 6 · Claude
- Model `claude-opus-5`, adaptive thinking on, `output_config.effort` low for parse and filter calls and medium for drafts. Server-side refusal fallback on by default (`betas=["server-side-fallback-2026-07-01"], fallbacks="default"`) so a refusal never stalls the pipeline.
- Structured outputs via `client.messages.parse(output_format=PydanticModel)`; the Pydantic schema is the contract with the engine.
- Vision: base64 `image` content block followed by a text block; convert HEIC to JPEG first and downscale to at most 1568px on the long edge.
- Calls:
  1. `vision.identify_item(photos) → ItemIdentity{title, brand, model, category, condition: A|B|C, confidence, notes, clarifying_question | None}`
  2. `intent.parse_seller(text, now, tz) → SellerIntent{kind: new_item|set_floor|extend|cancel|status|take_it|wait, deadline_at?, floor?, constraints?}`
  3. `intent.parse_buyer(text) → BuyerIntent{kind: inquiry|offer|accept|decline|question, amount?, question?}`
  4. `comps.filter(query, summaries) → kept ids + reasons`
  5. `buyer_agent.draft(context, bounds) → text`, where bounds = {allowed_price, allowed_actions}; then `leak_check` (floor, deadline, other offers, the words "minimum", "floor", "deadline") plus a numeric check that any dollar figure in the draft equals `allowed_price`
  6. `seller_voice.render(ledger_row) → text`; numeric check that every figure in the text appears in the ledger row
- Every call: 20s timeout, one retry, then a deterministic template. Stable system prompts carry `cache_control` so repeated calls hit the prompt cache.
