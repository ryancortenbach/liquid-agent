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
4. Complete API organization verification if the OpenAI console requires it for image models.
5. Start the app and open `http://localhost:8000/docs`.
6. Create an item with `POST /api/items`.
7. Send an iPhone HEIC, JPEG, PNG, or WebP to `POST /api/items/{item_id}/photos/enhance`.
8. Compare both returned image URLs, then call the review endpoint with `{"approved": true}`.

The generated image remains in `review` until the seller approves it. The original is always kept.

## 3. BlueBubbles

1. Install BlueBubbles Server from `bluebubbles.app` on the Mac signed into the agent Apple ID.
2. Grant Full Disk Access and set a server password.
3. Add `BB_SERVER_URL`, `BB_PASSWORD`, and `SELLER_HANDLE` to `.env`.
4. Confirm a seller can send a text and photo to the agent account.

## 4. eBay

1. Create developer sandbox and production keysets at `developer.ebay.com`.
2. Create an eBay sandbox test user and redirect URL.
3. Add the client ids, secrets, RuName, and sandbox refresh token to `.env`.
4. Use sandbox for hackathon publication. Production publication requires explicit seller approval.

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
