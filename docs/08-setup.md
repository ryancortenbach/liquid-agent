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
6. Keep `OPENAI_CHAT_ENABLED=true` and `OPENAI_CHAT_MODEL=gpt-5.4-mini` for conversational
   iMessage intent handling. API response storage is disabled for these calls.
7. Complete API organization verification if the OpenAI console requires it for image models.
8. Start the app and open `http://localhost:8000/docs`.
9. Create an item with `POST /api/items`.
10. Send an iPhone HEIC, JPEG, PNG, or WebP to `POST /api/items/{item_id}/photos/enhance`.
11. Compare both returned image URLs, then call the review endpoint with `{"approved": true}`.

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

Liquid uses two eBay keysets, both from developer.ebay.com > Application Keys.

- **Production keyset** (`EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`): read-only. Powers active comps
  through the Browse API and category suggestions through the Taxonomy API. No seller login.
- **Sandbox keyset** (`EBAY_SB_CLIENT_ID`, `EBAY_SB_CLIENT_SECRET`, `EBAY_SB_RUNAME`): publishes
  listings as a sandbox test user (developer.ebay.com > Sandbox test users). The RuName is the
  redirect URL name eBay assigns under User Tokens > Get a Token from eBay via Your Application.

Three commands take the sandbox from keys to a verified listing:

```bash
uv run python scripts/ebay_authorize.py
```

Sign in as the sandbox test user, approve, and paste the URL you land on. No public callback is
needed: the script exchanges the `code` from that URL and writes `EBAY_SB_REFRESH_TOKEN` to
`.env`. This shared token supports developer verification and API-only tests. It does not bypass
the required per-seller iMessage onboarding flow.

```bash
uv run python scripts/ebay_setup.py
```

Opts the seller into business policies, creates (or finds by name) the payment, return, and
fulfillment policies and a ship-from location, and writes the four ids into `.env`. Re-runnable.

```bash
uv run python scripts/ebay_verify.py --publish
```

Checks comps, category suggestion, sandbox auth, business-policy opt-in, the three policies, and
the location, then hosts a generated photo on eBay Picture Services, creates a draft offer,
publishes it, reprices it, withdraws it, and deletes it. Prints PASS/FAIL per step and exits
non-zero on any failure. Drop `--publish` for a read-only check, or use `--draft` to stop at the
draft.

Photos: at publish time Liquid uploads approved photos to eBay Picture Services, so
`PUBLIC_BASE_URL` can stay on localhost. When `PUBLIC_BASE_URL` is a public HTTPS address, eBay
fetches them from `/api/photos/{id}/file` instead.

Category: an explicit `category_id`, else a live Taxonomy suggestion for the title (production
keyset), else `EBAY_SB_DEFAULT_CATEGORY_ID`, else a leaf category for the identifier's item kind.

Per-seller connections (`CONNECT EBAY` in iMessage, `/oauth/ebay/callback`) require `APP_SECRET`,
the RuName, and a public `PUBLIC_BASE_URL`. Each seller's own connection is required before intake
and takes precedence over the `.env` token. Keep `REQUIRE_EBAY_ONBOARDING=true`.

API path: `POST /api/items/{item_id}/publish/ebay` with
`{"seller_approved": false, "aspects": {"Brand": ["Sony"]}}` prepares a draft; repeat with
`seller_approved` true to publish. Liquid stores the offer id while drafting and marks the listing
live only after eBay returns a listing id. Repricing uses `bulkUpdatePriceQuantity` on the live
offer.

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
