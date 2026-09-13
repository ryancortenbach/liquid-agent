# 06 · The two-minute demo

One item, one deadline, one failure, one recovery. A judge should be able to retell it in a sentence.

## Screen layout
Record the Mac screen with QuickTime or OBS at 1920×1080.
- Left third: the seller's iPhone through macOS iPhone Mirroring (or QuickTime over USB). This is the hero. Blue bubbles.
- Right two thirds: the dashboard at `/dashboard/{item}`: countdown in simulated time, the frontier, the live ledger stream, the buyer pipeline, and a clock pause button.
- A second phone, a teammate's, is off screen playing buyers. Its messages appear in the ledger and, when it matters, as a small inset.

## Time compression
`MODE=demo`, `DEMO_CLOCK_SPEED=3600`: one real second is one simulated hour. A 72-hour deadline plays in 72 seconds. The presenter pauses the clock at the beats below with the dashboard button. The same code paths run as in real time. Scripted sim buyers from `demo/scenario.yaml` provide views and inquiries; real teammates provide the offers, the declined card, and the final payment.

## Script (timestamps are video time)
| t | On screen | What happens |
|---|---|---|
| 0:00 | title card, 3s | "Liquid. take a picture. set a deadline. we'll get it sold." |
| 0:03 | iPhone | Seller sends a photo of the XM5s: "sell this by sunday 6pm. don't go under 170" |
| 0:10 | iPhone | "got it. sony wh-1000xm5, good condition (small scuff on the headband). checking what they're going for." |
| 0:18 | iPhone + dashboard | The frontier card arrives. Dashboard shows 48 comps, M, σ, the frontier, the opening price. Ledger row 1. |
| 0:30 | dashboard | Clock runs. Views tick up, no inquiries. At 48h: REPRICE $222 → $210, BROADCAST $204 to 7 interested. The iPhone gets the check-in. Presenter: "nobody typed a price. it's learning this market is slower than the comps suggested." |
| 0:50 | inset phone | A buyer texts "would you take 187?" The agent counters at $205. The dashboard shows EV of accepting vs continuing. The presenter reads the reason line. |
| 1:05 | dashboard | Clock to 8h. A second buyer stands at $198. The agent ACCEPTS the best executable offer and sends the pay link. Status PENDING_PAYMENT. |
| 1:15 | inset phone | The buyer pays with the declining test card. Stripe webhook `payment_intent.payment_failed`. Ledger: PAYMENT FAILED → expire session → re-evaluate → ACCEPT the next best ($187 buyer, re-asked) → new pay link. Presenter: "no double sale, no floor breach, no missed deadline." |
| 1:30 | inset phone | The buyer pays with 4242. `checkout.session.completed` → SOLD. Shippo label. Calendar event. |
| 1:38 | iPhone | "sold for $187 to priya. that's $39 more than the instant option. label's ready, ups drop-off is on your calendar tomorrow at 10." Cut to the calendar event and the label PDF, 2s each. |
| 1:48 | eval slide, 8s | The sim table: agent vs static across four deadlines, 0 invariant violations, the invariant list. |
| 1:56 | end card | Repo URL. Stack line: iMessage · eBay · Stripe · Shippo · Google Calendar · Claude. |

## Beats the judges must see
1. A photo and a sentence are the entire input.
2. The frontier card: liquidity, not a listing.
3. A reprice with a reason that cites evidence.
4. A counter with EV numbers.
5. A payment failure and an automatic re-route with no floor breach and no double sale.
6. Fulfillment and calendar done without being asked.
7. The eval table.

## Recording plan
- 14:45 take 1: unattended engine, presenter narrates live.
- 15:05 take 2.
- 15:20 cut to 2:00 in iMovie or CapCut; add the title, eval, and end cards.
- Upload by 15:45. Never depend on live conditions during judging. The video is the demo; the live system is for questions.

## Fallbacks
- BlueBubbles dies during a take: switch `CHANNEL=chatdb` (fallback A) and retake; if that also fails, `CHANNEL=twilio`.
- eBay comps fail: `comps.py` falls back to Claude's estimate with `confidence=low`; the card says "based on my estimate" and the take continues.
- Stripe webhook doesn't arrive: `payments/stripe_client.py` polls the session every 5s while a checkout is open, so the flow completes either way.
- Nothing works: play the 14:45 recording.

## Landing page (P2, only if someone is idle)
In the folk.com spirit: a sky-gradient hero, an iPhone mockup showing the frontier card, the one line "take a picture. set a deadline. we'll get it sold.", and the five promises. Static HTML, no backend.
