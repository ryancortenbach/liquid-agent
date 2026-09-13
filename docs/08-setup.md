# 08: Local and account setup

## 1. Install the project

```bash
uv sync
cp .env.example .env
uv run pytest
```

## 2. OpenAI image editing

1. Create an API key at `https://platform.openai.com/api-keys`.
2. Put it in `.env` as `OPENAI_API_KEY`. Never commit the key.
3. Keep `OPENAI_IMAGE_MODEL=gpt-image-2.5-sunburst` for the highest edit precision.
4. Keep `OPENAI_VISION_MODEL=gpt-5.4-mini` to identify the product before editing it.
5. Keep `OPENAI_TRUTH_CHECK=true` so generated photos are compared with their originals before
   seller review.
6. Complete API organization verification if the OpenAI console requires it for image models.
7. Start the app and open `http://localhost:8000/docs`.
8. Create an item with `POST /api/items`.
9. Send an iPhone HEIC, JPEG, PNG, or WebP to `POST /api/items/{item_id}/photos/enhance`.
10. Compare both returned image URLs, then call the review endpoint with `{"approved": true}`.

The generated image must pass the automated truth check and then remains in `review` until the
seller approves it. The original is always kept.

## 3. BlueBubbles

1. Install BlueBubbles Server from `bluebubbles.app` on the Mac signed into the agent Apple ID.
2. Grant Full Disk Access and set a server password.
3. Run `uv run python scripts/configure_bluebubbles_local.py` on the BlueBubbles Mac to copy the
   local server password and generate a separate webhook secret without displaying either value.
4. Add `SELLER_HANDLE` to `.env`. Use the phone number or email of the person texting the server,
   not the iMessage account hosting BlueBubbles.
5. Start Liquid with `uv run python scripts/run_local.py`. This runner disables access logging so
   the webhook secret is not written into request logs.
6. Register the authenticated local inbound webhook with
   `uv run python scripts/register_bluebubbles_webhook.py`.
7. Text a photo and caption from `SELLER_HANDLE`. Liquid accepts messages only from that handle.
8. Confirm the original and enhanced photos arrive, then reply `APPROVE` or `REJECT`.

For one item with multiple angles, attach all photos in the same message. For multiple items, start
the message with `BATCH` and attach one primary photo for each item. Use `BATCH 2+3` when item 1
has two photos and item 2 has three. Confirm the numbered identity summary, approve the photo set,
and Liquid will move through the items one at a time.

If one photo contains several products, send it normally. Liquid inventories and crops each
sellable object, then asks the seller to confirm a numbered checklist. Use `REMOVE 3` to exclude an
object or `3 is ...` to correct its identity. Send a closer photo if the checklist missed anything.

Keep a specific `SELLER_HANDLE` during local testing. Set it to `*` only when intentionally opening
the bot to multiple sellers. Each sender receives a separate seller, conversation, item, and eBay
connection record.

## 4. eBay

Create Sandbox or Production application keys in the eBay Developers Program. Configure the
application's Accept URL as `PUBLIC_BASE_URL/oauth/ebay/callback` and save the RuName that eBay
assigns to it.

For Sandbox, set `EBAY_ENVIRONMENT=sandbox`, `EBAY_SB_CLIENT_ID`, `EBAY_SB_CLIENT_SECRET`, and
`EBAY_SB_RUNAME`. For Production, set `EBAY_ENVIRONMENT=production`, `EBAY_CLIENT_ID`,
`EBAY_CLIENT_SECRET`, and `EBAY_RUNAME`. Set `APP_SECRET` to at least 32 random characters. Never
commit any of these values.

The authorization request asks only for the base, Inventory, and Account scopes. The seller signs
in on eBay and grants access. Liquid exchanges the one-time code, encrypts the refresh token at
rest, and associates it with the seller record. Keep `REQUIRE_EBAY_ONBOARDING=true`. On the first
text from a new seller, Liquid sends the authorization link and blocks photos and listing work
until the callback succeeds. The seller can text `RETRY` for a fresh link if the link expires,
authorization is declined, or eBay returns an error. Onboarding cannot be skipped.

1. Create developer sandbox and production keysets at `developer.ebay.com`.
2. Create an eBay sandbox test user and redirect URL.
3. Create a sandbox inventory location and note its merchant location key.
4. Opt the sandbox seller into business policies, then create payment, return, and fulfillment
   policies.
5. Add the client id, client secret, RuName, location key, and three policy ids to `.env`. The
   per-seller refresh token is created by the onboarding callback and is not pasted into `.env`.
6. Set `PUBLIC_BASE_URL` to public HTTPS so eBay can fetch approved listing images.
7. Prepare a draft with `POST /api/items/{item_id}/publish/ebay` and
   `{"seller_approved": false, "aspects": {"Brand": ["Sony"]}}`.
8. Publish only after review by repeating the request with `seller_approved` set to `true`.

Liquid stores the eBay offer id while the listing is a draft. It marks the listing live only after
eBay returns a listing id. Production publication is not configured by this sandbox adapter.

## 5. Facebook Marketplace

1. Sign into the seller's own Facebook account in the demo browser.
2. Test opening the Marketplace create-listing flow.
3. Liquid may prepare and fill fields, but the seller performs the final review and publication.

## 6. Optional fulfillment and calendar

- Add a Shippo test key only for sales where the marketplace does not supply a label.
- Enable Google Calendar API and place the OAuth client at `secrets/gcal_client.json`.

## 7. Readiness check

```bash
uv run python scripts/smoke_all.py
```

Missing credentials are reported by name without printing their values.
