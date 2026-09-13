# 01 · Product spec

Name: **Liquid**. As in liquidity: turning possessions into cash on a timeline.

## One line
Take a picture. Set a deadline. We'll get it sold.

## Thesis
Every marketplace asks you to set a price and wait. But people rarely have things they need to *price*. They have things they need *gone*: by the move, by the flight, by rent day. Liquid takes a photo and a deadline and runs a liquidation strategy. It discovers how much cash the item can reliably become and how fast, then reprices, negotiates, and routes between exits as the clock runs down, so you end with the most money that actually clears before your deadline.

Normal marketplaces optimize listings. Liquid optimizes liquidation.

## Interface: it lives in your texts
Like the folk.com companion, Liquid is a contact in Messages, not an app. You text a dedicated iMessage handle. It replies in blue bubbles, checks in on its own when something changes, and asks you only when it needs a decision. A web dashboard exists for the demo and debugging, never for the seller.

Voice: lowercase, warm, short. Numbers are exact. It sounds like a friend who happens to be a very good dealer. It never performs; it reports.

## Who it is for
- Anyone moving, traveling, or decluttering with a date attached
- People who hate marketplaces: the messaging, the lowballs, the no-shows
- Demo persona: Sam is moving Sunday and has a pair of Sony WH-1000XM5 headphones to get rid of

## The core loop
1. **Intake.** Photo plus "gone by sunday 6pm". Identify the item, grade condition, parse the deadline and constraints, propose a floor.
2. **Discover.** Pull comps, estimate market value and spread, compute the liquidity frontier (sell now / today / 3 days / 7 days), choose the opening price and channels.
3. **Route and sell.** List on the marketplace, open the local offer page, and on every tick: hold, reprice, broadcast, counter, accept, switch channel, or escalate, maximizing expected executable value before the deadline.
4. **Close.** The accepted buyer gets a payment link with a window. Payment is verified by webhook or the buyer is dropped and the next best exit is taken. One sale, ever.
5. **Fulfill.** Buy the label, text it, put the drop-off (or pickup) on the calendar, and send the seller one line with the counterfactual: "$39 more than the instant option."

## Features by priority
P0 is the demo. P1 only if the P0 path is green by 13:30. P2 is the pitch, not the build.

### P0, must ship
| # | Feature | Acceptance criteria |
|---|---|---|
| F1 | iMessage in and out | Photo + text from the seller's iPhone reaches the server within 5s. Replies land as blue bubbles. Buyers can text the same handle and are routed to the right item. |
| F2 | Item identification | From one photo: title, brand, model, category, condition grade (A/B/C), confidence. If confidence < 0.6, asks exactly one clarifying question. |
| F3 | Intent parsing | "gone by sunday 6pm, don't take less than 170, local only" becomes validated JSON {deadline_at, floor, constraints}. Relative dates resolve in the seller's timezone. |
| F4 | Comps and market value | eBay Browse search, Claude drops mismatches (parts, bundles, cases), median and dispersion of used fixed-price listings give M and sigma. |
| F5 | Liquidity frontier | "$153 now / ~$185 today / ~$205 within 3 days" computed from the model and texted as a card within 20s of the photo. |
| F6 | Engine tick | Every tick: recompute the optimal price, decide HOLD / REPRICE / BROADCAST / COUNTER / ACCEPT / ROUTE / ESCALATE / EXPIRE, write a ledger row with every input. |
| F7 | Local buyer channel | Per-item offer page (photos, price, "make an offer", "buy now") and buyers texting the agent. The agent answers, counters, and accepts, always at or above floor. |
| F8 | Payment | Accepted buyer gets a Stripe Checkout link with a window. `checkout.session.completed` marks SOLD. A decline or expiry drops the buyer and re-routes to the next best exit. |
| F9 | No double sale | Only one buyer can hold a live checkout. The prior session is expired through the Stripe API before a new one is issued. |
| F10 | Shipping | After SOLD: Shippo label bought, label URL and tracking texted to the seller. |
| F11 | Calendar | Drop-off (or pickup) event on the seller's Google Calendar with address, buyer, and label link. |
| F12 | Seller check-ins | Proactive texts on: listed, reprice, escalation, sold, shipped. At most one text per event class per simulated hour. |
| F13 | Demo clock | The whole run plays at 1 real second = N simulated minutes through the same code paths as real time. Pause and resume from the dashboard. |
| F14 | Eval harness | Agent vs static listing vs markdown schedule vs oracle across deadlines and seeds. One table, one chart, zero invariant violations. |

### P1, if time
| # | Feature |
|---|---|
| F15 | eBay sandbox listing actually published (inventory item, offer, publish). Without it eBay is comps-only and still a real integration. |
| F16 | Escalation with one-word replies: "best real offer is $165, your floor is $170. take it / wait / extend" |
| F17 | Dashboard: live ledger stream, frontier, buyer pipeline, countdown. This is the judges' second screen. |
| F18 | Commands: "extend to tuesday", "cancel", "status", "floor 160" |
| F19 | Instant liquidation path: a modeled guaranteed quote the seller can take at any time ("take the guaranteed") |

### P2, pitch only
- Personal liquidity: scan a shelf, get "instant $1,140 / 24h $1,720 / 3d $2,380 / 7d $2,910"
- "raise $600 by tomorrow, don't sell my monitor" chooses the minimum set of items
- Routing to consignment and trade-in partners as additional exits
- Playbooks, in the spirit of folkways: "gone by", "raise $X", "declutter the closet"

## Conversation design

### Seller messages the parser must handle
- `[photo] sell this by sunday 6pm`
- `gone by friday. get me the most you can`
- `floor 170` · `don't take less than $170`
- `local only` · `no shipping` · `shipping is fine`
- `extend to tuesday` · `cancel` · `status` · `take it` · `wait`
- `raise $600 by tomorrow, don't sell the monitor` (P2: parse only, reply "one item at a time for now")

### Seller-facing messages
Templates. Claude renders the prose; the engine supplies every number. A message never contains a number the ledger does not.

- **intake ack**: "got it. sony wh-1000xm5, good condition (small scuff on the headband). checking what they're going for."
- **frontier card**:
  ```
  your options
  $153   guaranteed now
  ~$185  likely today
  ~$205  likely within 3 days

  you said sunday 6pm, so i'll start at $215 and adjust as it gets closer. i won't go below $170 without asking you.
  ```
- **listed**: "it's up. i'll text you when something changes."
- **reprice check-in**: "48h left. lots of looks, no takers. dropped to $210 and sent $200 offers to the 7 people who asked."
- **escalation** (the only time it asks): "8h left. best real offer is $165, local, can pay right now. your floor is $170. take it, wait, or extend?"
- **sold**: "sold for $192 to jordan. that's $39 more than the instant option. label's ready, ups drop-off is on your calendar tomorrow at 10."
- **recovery** (the seller sees the outcome, not the drama): "jordan's payment didn't go through. sold to priya for $198 instead, paid and confirmed."

### Buyer-facing messages
- **inquiry**: answers condition and price, attaches photos, shares the offer link
- **counter**: "can do $205. that's where it sits today." Never mentions a floor, a deadline, or other buyers' numbers.
- **accept**: "deal at $198. here's your payment link, good for 15 minutes: <url>"
- **failed**: "that payment didn't go through. if you still want it, try again within 10 minutes: <url>"
- **sold out**: "sorry, it just sold."
- **pending** (to others while one buyer holds a checkout): "someone's paying for it right now. i'll text you if it falls through."

## Promises to the seller
These are the invariants in docs/05-reliability.md, in the seller's words.
1. We never sell below your floor without asking you.
2. We never sell your item twice.
3. We never call it sold until the money has cleared.
4. We never ship before it's paid.
5. Every decision has a written reason with the numbers behind it.

## Non-goals for the hackathon
No marketplace scraping. No real eBay orders (sandbox only). No stored PII beyond phone numbers and one shipping address. No multi-item portfolios in code. No native app.
