# Liquid · morning briefing · Sunday 2026-09-13

Written 03:20 EDT by the overnight loop, revised 04:50 after a consistency review. Nothing here is applied to docs/00 to docs/09 yet, and nothing is committed or pushed. Full evolution with sources: `docs/ideation/overnight-2026-09-13.md` (thirteen iterations, v1 → v9).

## 1 · Two-minute version
- The idea survived thirteen iterations, two simulated judging panels, a numeric check of its own math, and a consistency review. Score on the hackathon rubric: **7.2 (v1) → 8.8 (v9)**. My estimate that the P0 spec is on screen by 16:00 ET: **about 75%**.
- The concept is unchanged in spirit: photo + deadline in, a liquidity frontier out, a deterministic engine sells for the most money that clears in time, never below the floor. What changed is what makes it first-place material for *this* panel: the marketplace twin is the pricing mechanism and the evidence; the engine is a finite-horizon dynamic program with a textbook lineage; the Guard catches the failure classes the host company publishes; the demo shows the agent catching an injected mistake; the numbers are pre-registered and honest.
- The simulated panel's last verdict: "a first-place build whose first place now turns on the twin's honesty rather than the engine's math." The twin now has buyers who counter, ghost, and fail payment, and the numbers below come from it.

## 2 · Decisions, with defaults so silence resolves them
1. **The name (decide before 07:40).** "Liquid" collides with Liquid AI ($2.35B foundation-model company) and Liquid / Co-Invest ($18M Series A, trades inside ChatGPT and Claude). Default if undecided: keep Liquid with the qualifier "sell by sunday" on the title card. Alternatives checked in log iteration 5B ("dueby" was the cleanest).
2. **The demo item is the iPad Air 5th gen (M1, 64GB Wi-Fi).** Confirm it is physically in hand. Switching to the XM5 invalidates the envelope, the beat sheet, and the dashboard mock; only do it if there is no iPad.
3. **Pre-window code.** Decision made: we build from 07:40 ET and disclose the commit log; the video and the crib claim nothing about when code was written. If the rules at the 12:00 ET opening forbid it, we say exactly which commits predate 12:30 and let the judges weigh it.
4. **Team size.** Three lanes below (A engine and twin, B conversation, C money, logistics, dashboard). With two people: B stays B; A takes C's items after S1, and the P0.5 twists are dropped except "where we lose".

## 3 · The idea, final
Text a photo and a deadline to an iMessage contact. Liquid confirms the item if the model is ambiguous, computes a liquidity frontier from a thousand simulated markets, lists it, reprices as time runs down and evidence arrives, negotiates offers against the continuation value, routes to the best executable exit, takes payment through Stripe, dispatches a DoorDash courier for local sales, books the pickup on Google Calendar, and texts the result with the counterfactual. Fourteen invariants in a Guard that also catches semantic failures (wrong item, model drift). Every decision is a ledger row with its inputs, badged REAL or TWIN.

**Engine**: Bellman recursion on a 15-minute grid (Gallego–van Ryzin 1994; reservation price = continuation value, Karlin 1962 / McCall 1970); arrival rates learned online (Gamma-Poisson, Aviv–Pazgal 2005); σ from the comps' robust dispersion; standing offers with expiries give recall; the instant quote is the salvage value at the deadline. Validated tonight in the spined twin: monotone price path $355 → $298 over 72h; DP and twin agree within $2; the edge over an eBay Best Offer proxy is **+$7 / +$19 / +$43 / +$59 at 12h / 1 / 3 / 7 days** (all pre-registered expectations, not results); the edge shrinks but holds at σ = 20; a 40% error in σ costs under $8.

**Apps (all real)**: iMessage (BlueBubbles on the Mac, dedicated Apple ID) · eBay Browse comps in production, plus an unpublished draft offer carrying the floor as `autoDeclinePrice` (after S1) · Stripe Checkout test mode with real declines · DoorDash Drive sandbox with simulator webhooks · Google Calendar · Claude (vision, intent, comps filter, drafts, seller voice). Pitch-only: eBay publish, Shippo, flash round by lead count, agentic checkout via Stripe Shared Payment Tokens, portfolio mode.

## 4 · The frontier card and the beat sheet (demo numbers, real sources)
Prices observed 2026-09-13: Swappa average sale $310, BankMyCell "Good" $230, Back Market about $303 → M ≈ $303. Best instant offer $221 (BankMyCell aggregator). Instant ratio 0.73, which validates the modeled 0.72 (the comps haircut is a different number, 0.92).
```
your options
$221   guaranteed now (bankmycell best offer, today)
~$305  likely by sunday · 99% in 1,000 simulated markets
       64% chance it's gone by tomorrow, at about the same price
starting at $355 and coming down as it gets closer. never below $220 without asking you.
```
| t | beat |
|---|---|
| 0:00 | Title (2s), then the seller's photo and text: "gone by sunday 6pm. not under 220" |
| 0:08 | "is this the ipad air 4th gen or 5th? they look the same and the 5th is worth about $80 more. reply 4 or 5." Seller: "5". Caption: I12, comps disagree with the model guess by 27% of the comps median |
| 0:18 | Frontier card lands; dashboard shows 48 comps, the histogram from 1,000 twin runs, the sealed-envelope hash |
| 0:30 | Operator skips the clock two days ahead. One tick: reprice $355 → $335, reason "0 inquiries in 48h, arrival estimate 2.0 → 1.1/day, V(24h) = $280" |
| 0:50 | Buyer A texts "would you do 280?" Agent counters at $320 (the smallest price whose reliability-weighted net beats V). A replies "290 is my max". Operator fires the Break Glass "instruction violation" injector on the parallel item `demo-inject`; the Guard panel shows the rejected draft "$215 works", badged INJECTED |
| 1:05 | Buyer B "i'll take it at 305", accepted, pay link. "Stripe test mode" on screen |
| 1:15 | B pays with the declining test card (narrated as injected); session expired; agent to A: "it fell through, $290 is yours"; A pays with 4242. No second checkout ever existed |
| 1:28 | Courier dispatched (3s of status), calendar event (1s), sold text: "sold for $290 to a. that's $69 more than the guaranteed offer. a dasher picks it up today at 4:10." |
| 1:40 | Same buyers, three sellers: agent / static / oracle counters on one buyer stream, labeled "means over 200 seeds" unless the per-seed race is built |
| 1:48 | Eval table vs the envelope, the failure matrix in the host's seven classes, the "where we lose" card |
| 1:56 | End card: what was real, what was twin; repo |

## 5 · 07:00 to 07:40, all hands, before the walking skeleton
1. Reserved ngrok domain up; `PUBLIC_BASE_URL` set once; pasted into BlueBubbles webhooks, the Stripe dashboard endpoint (four events), DoorDash webhooks. Never re-pasted.
2. Full iMessage round trip from every phone to the agent's Apple ID: text, photo, reply. Blue both ways. Confirm Full Disk Access, `caffeinate -dims`, and whether the send field is `message` or `text`; write it in `.env`.
3. Write and run `scripts/smoke_all.py` (15 minutes, the first code of the day): BlueBubbles ping and send, eBay Browse search, Stripe session create, DoorDash quote (JWT signed with the **base64url-decoded** secret), Calendar insert, Claude call. All green before anything else.
4. Repo hygiene commit: `.gitignore`, a pre-commit grep for `sk_test|whsec_|sk-ant`, file ownership table in the README, **and `docs/ideation/preregistration.json` with `preregistration.sha256`** (the sealed envelope; the video says it was committed before the code, so this commit is mandatory, not optional). Push it.
5. Freeze the beat sheet above; test the recording setup end to end (screen capture, mic, phone mirrored). Name decided by default if not by choice.

## 6 · Sunday, Eastern time (★ = before the official 12:30 window)
| Time | A · engine and twin | B · conversation | C · money, logistics, demo |
|---|---|---|---|
| 07:40 ★ | all three: walking skeleton (config, clock, db, models, ledger, state + actions, policy stub, executor, outbox worker, main + BlueBubbles adapter) | | |
| 08:45 ★ | **S0: text in → tick → text out under the demo clock, one ledger row. Red at 09:15: everyone stays on it.** | | |
| 09:15 ★ | DP, frontier, `twin/intake.py` (the card needs it at S1) | attachments, HEIC, vision, intent | eBay comps, σ from MAD |
| 10:15 ★ | policy, actions | router | Stripe create, webhook (secret list), expire |
| 11:15 ★ | guard, executor, scheduler | buyer agent, leak check | DoorDash quote → accept → simulator webhook |
| 12:15 ★ | **S1: photo from phone → comps → frontier card → LIVE. Red: cut I11, eBay draft, the twists.** | | |
| 12:30 | official start; announce the cut list | | |
| 12:30 | I12, I13, I14 | seller voice, escalation, cancel-before-payment | paid → courier → calendar chain |
| 13:30 | twin with spined buyers, policies, `twin/run.py`, `twin/sensitivity.py` (same script) | full buyer thread: inquiry → counter → accept → pay | dashboard: ledger, Guard, header, frontier (60-minute cap) |
| 14:30 | eval grid → `docs/eval/`; envelope diff | red team personas (30 min); copy polish | calibration: 20 hand-collected sold prices, hard stop 15:15; eBay draft offer if idle |
| 15:00 | P0.5 in order: where-we-lose card (10), Break Glass injectors + strip (25), race in `twin/race.py` + panel (40) | | |
| 15:30 | **dry run 1, timed** | | |
| 15:45 | **eval-table decision: if no table, beat 10 uses golden tests + the invariant table** | | |
| 16:00 | **backup take, unedited** | | |
| 16:30 | **P0 freeze**; property tests (45 min cap), chaos, brief | | |
| 17:15 | rehearsal 2 on the freeze build | | |
| 17:45 | **code freeze; take 1** · 18:05 take 2 · 18:20 edit, brief final, tag · **18:45 submit** · 19:00 hard stop · judging with the crib open | | |
Cut rules: payments not green at 14:30 → buyer texts "paid", manual SOLD, disclosed · courier 401 at 16:00 → calendar only · nothing that is not on screen at 16:00 goes in the video.

## 7 · Exact edits to make in docs/ (none applied)
- **docs/00, 01, 05, 06**: replace Shippo with DoorDash Drive as the P0 fulfillment app everywhere (docs/00 app table, docs/01 F10, docs/05 smoke table and real-vs-modeled table, docs/06 end-card stack line); Shippo to P1.
- **docs/01**: F18 cancel-before-payment → P0; add F20 value-sanity confirmation and F21 REAL/TWIN badges; demo persona → iPad Air; add the demand numbers; state the 5% take rate.
- **docs/02, 03, 05**: `sim/` → `twin/` everywhere (`SimClock` may keep its name); add `buyer_identity` table, `engine/value_function.py`, `fulfillment/doordash_client.py`, `twin/intake.py`, `twin/race.py`, `web/dashboard.py` Guard panel and race; REAL/TWIN column on LedgerEvent; SQLite WAL + `busy_timeout` + global write lock; no HTTP inside a transaction; clock-leak test; DP clamps; Stripe secret list; DoorDash external ids with ulid.
- **docs/03**: objective → Bellman recursion; reservation price = V(τ); σ = 1.4826·MAD of comps floored at 0.08·M; **delete the 0.85 hold-price frontier rule**, the frontier is realized outcomes with probabilities from `twin/intake.py`; instant quote per category with the observed 0.73 ratio; MODEL_DRIFT check; M-update from offers (P1); citations.
- **docs/04**: DoorDash Drive section (auth, endpoints, simulator, webhooks); Shippo demoted; eBay draft offer with `bestOfferTerms`; "what Stripe test mode does not prove".
- **docs/05**: I11 to I14 with tests (I11 is implemented and unit-tested, not an eval row); failure matrix over Lemma's seven classes plus drift plus crash; **replace** `static_90` with the Best Offer proxy (list at M, accept ≥ 0.9·M); calibration and sensitivity sections; pre-registration; provenance badges; Break Glass injectors as endpoints on a parallel item.
- **docs/06**: the beat sheet in section 4; the honesty line; the word "audit" over the ledger; backup take rule; clock "skip" control.
- **docs/07**: replaced by section 6.
- **docs/08**: reserved ngrok domain; secret grep; DoorDash developer account; the 07:00 list.
- **docs/09**: headings "Failure modes and catches · Twin, not mock · Cross-system identity resolution · What is real, what is twin, what is decision-ready"; the crib as an appendix. Start from `docs/ideation/brief-draft.md`.

## 8 · The Q&A crib (twelve questions, one line each)
1. eBay Best Offer already does this? One channel, static thresholds, no clock; we re-solve a finite-horizon program each tick and arbitrate across exits on net; the Best Offer proxy nets $263 at 72h in our twin, the agent $306.
2. Listx? A commitment surface the seller chooses on; we route between exits and prove the counterfactual per sale; to copy the frontier you need the twin.
3. Is a simulated sale honest? Messaging, comps, money rail, courier, calendar are real; buyers are the twin unless a teammate is texting; every event is badged REAL or TWIN, including at the sale.
4. Vision says XM5, it's an XM4? I12: eight-plus comps and agreement within 15% of the comps median with an independent price prior, else the seller confirms the model before listing.
5. A floor check is a bounds check; what catches "every step succeeded, answer wrong"? I12 and I13 (posterior predictive check on inquiries → MODEL_DRIFT), both on the Guard panel at runtime.
6. Where did the priors come from? Invented because sold data is gated, then learned; here is the sensitivity sweep, including σ; the floor is never engine-moved.
7. Why is this an agent? The model never touches money by design; agency is multi-step state over a horizon with tool side effects and revision under evidence; thirty Claude buyer personas red-team it.
8. Two webhooks 40ms apart? A unique partial index on open checkouts plus SOLD-terminal in one transaction; the second write fails at the database; event ids are receipts.
9. Buyer never shows, seller cancels at minute 14? No hold without a checkout, reliability halves, pool re-evaluates; seller cancel before payment expires the session; after payment it is a refund and we say so.
10. Same person on two channels? Resolved at the router across handle, email, and Stripe customer before it counts, or arrivals inflate and two checkouts can reach one human; implemented and unit-tested, not demonstrated with two phones.
11. 1,000 items? Cache the value function per (category, M, σ) bucket; then the single Mac behind iMessage is the ceiling, and a product would use business messaging.
12. Built in six and a half hours? Here is the commit log and the cut line; credentials before the window, code from 07:40 ET disclosed, nothing in the video claims otherwise.

## 9 · Numbers for the brief
- Pre-registered expectations: `docs/ideation/preregistration.json`, sha256 in `preregistration.sha256` (`874acade…bb80c`). One world model for every number in it.
- Demand: 38 to 40 million Americans moved in 2024 (Census ACS); about 400,000 military families PCS a year; $559.8B of unused resellable items in US homes, about $4,267 per household (Mercari 2023); 54% sold something secondhand last year, 60% use the proceeds for bills (OfferUp 2024); people are as likely to trash (36%) or give away (35%) an item as sell it; eBay monthly sell-through about 31 to 33%; fire-sale discounts 8 to 25%. Do not cite the "70% no-show" figure.
- Certainty premiums: iBuyers 8.8 to 13.9% below resale; instant car offers 10 to 15% below private party; our observed iPad instant ratio 0.73 (a 27% discount).
- Theory: Gallego and van Ryzin 1994; Karlin 1962; McCall 1970; Aviv and Pazgal 2005; Besbes and Zeevi 2009; Almgren and Chriss 2000; Bulow and Klemperer 1996.

## 10 · What is in the ideation folder
- `overnight-2026-09-13.md`: the full log, v1 → v9, thirteen iterations, every source
- `MORNING.md`: this file
- `preregistration.json` + `preregistration.sha256`: the sealed envelope, commit at 07:00
- `video-script.md`: eleven beats, narration, both phones' texts, operator cues
- `brief-draft.md`: the system and reliability brief, two pages, numbers marked for replacement
- `dashboard-spec.md`: seven panels in build order under a 60-minute cap
- `twin-spec.md`: world model, policies, common random numbers, grid, personas, calibration
- Scratchpad (session-local, not in the repo): `engine_check.py` through `engine_check5.py`, about 250 lines of plain Python that can seed `engine/value_function.py` and `twin/world.py`
