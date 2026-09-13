# 13: Demo beats for what is built (two minutes)

Matches the code on `codex/liquid-core` plus PR #1. One seller, one item, one photo, one listing
pack, no buyers on camera. Record the Mac screen: iPhone mirrored on the left, `/dashboard/{item}`
on the right. Run the server in demo mode with the reprice loop on:

```
MODE=demo DEMO_CLOCK_SPEED=3600 REPRICE_LOOP=true uv run uvicorn app.main:app
```

| Time | On screen | What happens |
|---|---|---|
| 0:00 | Title, then the iPhone | Seller texts a photo with "Apple iPad Air 5th gen 64GB wifi, sell by sunday 6pm, don't go under 220". |
| 0:10 | iPhone + dashboard | "Got it. I am preparing a cleaner, truthful listing photo now." The dashboard shows the untouched original, then the enhanced version beside it. |
| 0:25 | iPhone | Original and enhanced arrive as images. Seller replies APPROVE. Caption: enhanced photos never replace the original and need approval. |
| 0:35 | iPhone | "two quick things" (condition, included, issues). Seller: "2, comes with the box and charger, small scratch on the back". |
| 0:45 | iPhone | "last three" (speed, floor, shipping and where). Seller: "3 days, not under 220, both 94110, all". |
| 0:55 | dashboard | "on it. pulling sold and active listings..." Research panel fills: sold and active counts, medians, source links. Ledger rows: research, price_plan, listing_plan. |
| 1:05 | iPhone | The card: title, condition, "list at $X, $Y with 47h left, $Z with 23h left, floor $220", platforms, "based on N sold (median) and M active (median)", three source links, guaranteed-now reference. |
| 1:15 | iPhone | Seller: "go". |
| 1:22 | dashboard + iPhone | eBay pack goes live with the sandbox listing link (or, without the sandbox, the pack shows the exact reason). Two copy-ready messages arrive for Facebook Marketplace and OfferUp, and the CSV path shows on the pack. |
| 1:35 | dashboard | Operator: `POST /api/clock/skip {"hours": 30}` (or the demo runner). Within two seconds the loop reprices; the ledger shows "reprice" with the step's reason and the before and after prices; the seller gets "24h left. dropped to $Y from $X". |
| 1:48 | dashboard | Scroll the ledger: every step with its inputs and sources. Say the word "audit". |
| 1:55 | end card | What is real: iMessage, OpenAI photo edit, Apify comps, eBay sandbox, Claude. What is not: Facebook and OfferUp are pasted by the seller. |

## Lines to say
- "Nothing publishes until the seller says go."
- "Every number on that card has a source you can click."
- "The price follows the schedule on its own; the seller only hears about it."
- "Facebook and OfferUp have no posting API, so it hands you the post. eBay it does itself."

## Fallbacks
- No OPENAI key: skip the photo beat; the flow still runs from a photo the seller sends.
- No Apify token: the card says "offline sample data"; say it out loud rather than hiding it.
- No eBay sandbox: the pack shows "eBay sandbox is not configured"; show the handoffs and the schedule instead.
- No iMessage: `uv run python demo/run_demo.py --photo ipad.jpg` drives the same path over the API with the dashboard as the only screen.
