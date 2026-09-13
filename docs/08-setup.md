# 08 · Tonight's setup checklist (Saturday 2026-09-12)

Accounts, keys, and permissions. No code. Every item is a click path a person must do. Order matters: eBay first because approval can lag.

## 1 · eBay developer (do first)
- [ ] developer.ebay.com → create an account → create an application keyset. You get a **production** keyset and a **sandbox** keyset.
- [ ] Production keyset: note `App ID (Client ID)` and `Cert ID (Client Secret)`. That is all the Browse API needs.
- [ ] Sandbox keyset (P1 listing): create a sandbox test user (Sandbox → Register a test user), add a RuName (User Tokens → Get a Token from eBay via Your Application → add an eBay Redirect URL), note client id, secret, RuName.
- [ ] Optional tonight: run one Browse search in the API Explorer to confirm the production keyset works. If the account shows "pending", write it down; comps have a Claude fallback.

## 2 · Apple ID for the agent, and Messages on the Mac
- [ ] Create a new Apple ID for the agent. An email handle is enough. Do not use anyone's personal Apple ID; the seller can't text themselves.
- [ ] On the demo Mac: Messages → Settings → iMessage → sign in with the agent's Apple ID. Enable "You can be reached at" the email. Sign out of any personal account in that Mac's Messages.
- [ ] From the seller's iPhone, text the agent's address. Reply from the Mac by hand. Blue bubbles both ways confirms iMessage.

## 3 · BlueBubbles server on the Mac
- [ ] Download the BlueBubbles server for macOS from bluebubbles.app and open it.
- [ ] System Settings → Privacy & Security → Full Disk Access → enable BlueBubbles. Accessibility is optional; skip Private API setup.
- [ ] In BlueBubbles: set a server password; note the port (1234).
- [ ] Test ping:
  ```bash
  curl "http://localhost:1234/api/v1/ping?password=PASSWORD"
  ```
- [ ] Test send (replace the number with the seller's):
  ```bash
  curl -X POST "http://localhost:1234/api/v1/message/text?password=PASSWORD" -H 'Content-Type: application/json' -d '{"chatGuid":"iMessage;-;+1SELLERNUMBER","tempGuid":"t1","message":"hello from Liquid","method":"apple-script"}'
  ```
  If the field name is rejected, try `"text"` instead of `"message"` and write down which one worked.
- [ ] Webhooks: leave for the morning once ngrok is up. Note where the setting lives.
- [ ] Disable sleep in Energy settings tonight; `caffeinate -dims` in a terminal tomorrow.

## 4 · Stripe
- [ ] dashboard.stripe.com → test mode → Developers → API keys → `sk_test_…`.
- [ ] Install the Stripe CLI (`brew install stripe/stripe-cli/stripe`), `stripe login`, then `stripe listen --print-secret` for a `whsec_…` for local dev.
- [ ] Tomorrow with ngrok: Developers → Webhooks → add endpoint `${PUBLIC_BASE_URL}/webhooks/stripe` for `checkout.session.completed`, `checkout.session.expired`, `payment_intent.payment_failed`, `checkout.session.async_payment_failed`; note that endpoint's own `whsec_`.

## 5 · Shippo
- [ ] goshippo.com → sign up → Settings → API → copy the **test** token (`shippo_test_…`).
- [ ] Decide the seller's from-address (any real US address) and put it in `.env` as `SELLER_FROM_ADDRESS_JSON`.

## 6 · Google Calendar
- [ ] console.cloud.google.com → new project "Liquid" → APIs & Services → enable **Google Calendar API**.
- [ ] OAuth consent screen: External; add the seller's Google account as a test user.
- [ ] Credentials → OAuth client ID → Desktop app → download JSON → `secrets/gcal_client.json` (git-ignored).
- [ ] Tomorrow first thing: run the one-time auth script and confirm an event appears on the seller's calendar.

## 7 · Anthropic
- [ ] `ANTHROPIC_API_KEY` with enough credit for a day of vision and parsing. Budget about $20.

## 8 · Tunnel
- [ ] `brew install ngrok` and sign in. A reserved domain avoids re-pasting webhook URLs after restarts. `brew install cloudflared` is the alternative.

## 9 · People and phones
- [ ] Seller phone: the presenter's iPhone, signed into iMessage.
- [ ] Two buyer phones (teammates), each able to iMessage the agent's address. Save it as a contact named "Liquid".
- [ ] Test cards memorized: `4242 4242 4242 4242` succeeds, `4000 0000 0000 0002` declines.

## 10 · Repo hygiene and rules
- [ ] `.gitignore`: `.env`, `secrets/`, `data/`, `*.db`.
- [ ] Register the team on the hackathon form. Read the official rules for what may be built before 9:30.

## `.env.example` (copy to `.env` tomorrow)
```
MODE=demo
DEMO_CLOCK_SPEED=3600
TICK_SECONDS=2
PUBLIC_BASE_URL=
TZ=America/Los_Angeles
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
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
SHIPPO_API_KEY=
GOOGLE_OAUTH_CLIENT_JSON=./secrets/gcal_client.json
GOOGLE_TOKEN_JSON=./secrets/gcal_token.json
SELLER_FROM_ADDRESS_JSON=
```
