# Liquid · overnight ideation log · 2026-09-13

Loop started 00:02 EDT. Planned stop about 06:15 EDT. Nothing in this file is committed or pushed. The planning docs in `docs/00` to `docs/09` are untouched; this log proposes changes to them, it does not apply them.

Note for the morning: the hackathon runs on Pacific time. Opening 9:00 PT is 12:00 EDT; the build window 9:30 to 16:00 PT is 12:30 to 19:00 EDT. `docs/07-schedule.md` is written in Pacific.

## Read me first (added 05:00)
Start with `MORNING.md` in this folder; it is the consolidated latest version. This log is the trail.
| Version | When | What changed | Rubric score |
|---|---|---|---|
| v1 | 00:02 | Baseline: Liquid as documented in docs/00 to docs/09 | 7.2 |
| v2 | 00:15 | The judges' vocabulary: marketplace twin, a semantic-failure catch on screen, buyer identity resolution, red-team personas | 7.7 |
| v3 | 00:45 | Pricing by simulation, DoorDash courier pickup, the Guard on screen, a real item | 8.25 |
| v4 | 01:08 | Bellman recursion replaces the hold-price objective; mechanism routing (P1); evidence-based video rules | 8.5 |
| v5 | 01:36 | The panel's hardest questions: value sanity I12, drift I13, external calibration, scope freeze, REAL/TWIN badges | 8.55 (v4 re-scored to 8.3) |
| v6 | 02:02 | Failure matrix over the host's seven classes; I14 constraints | 8.6 |
| v7 | 02:24 | Execution plan from the pre-mortem; real prices; ship probability 55% → 75% | 8.6 |
| v8 | 02:45 | The math run for real; honest frontier and Best Offer baseline; pre-registration | 8.7 |
| v9 | 03:08 | Twin buyers with a spine; σ inferred from comps; eBay draft offer; four originality twists | 8.8 |
Iterations 9 to 14 produced the morning briefing, the video script, the brief draft, the dashboard and twin specs, a consistency review with 44 fixes, and the sealed envelope (`preregistration.json`, sha256 `874acade…bb80c`, one world model for every number).

## How to read this
- Each iteration: research → critique → one concrete change to the idea → re-score.
- Scores are my judgment, 1 to 10 per criterion, weighted by the hackathon rubric. Deltas matter more than absolutes. A change that doesn't move the weighted score is recorded and rejected.
- Earlier versions stay in place so the evolution is visible; the consolidated latest version is `MORNING.md`.

## Scoring rubric v0 (refined after the winners research in iteration 2)
| Criterion | Weight | What a 10 looks like |
|---|---|---|
| Technical execution | 30% | A core only a strong team could build in 6.5h, working live, integrations that actually act, no smoke and mirrors |
| Reliability & evaluation | 25% | Invariants enforced in code, quantitative evals against baselines, failure injection shown, honest about what is modeled |
| Usefulness | 20% | A pain people already pay for or lose money on, the agent removes the whole chore, obvious who wants it tomorrow |
| Originality | 15% | Judges have not seen the framing; it changes what the product fundamentally does, not just the interface |
| Demo clarity | 10% | A judge can retell it in one sentence; a wow inside 15 seconds; one failure and one recovery |

## v1 · baseline · 00:02 · Liquid as documented in docs/00 to docs/09
**Idea.** Text a photo and a deadline to an iMessage contact. Liquid identifies the item, computes a liquidity frontier (sell now / today / 3 days / 7 days), lists it, reprices and negotiates as the clock runs down, routes to the best executable exit, takes payment, buys the label, books the drop-off. Deterministic engine, ten invariants, sim harness. Apps: iMessage (BlueBubbles), eBay, Stripe, Shippo, Google Calendar, Claude.

**Scorecard v1**
| Criterion | Score | Why |
|---|---|---|
| Technical execution (30) | 7 | Real engine, five integrations, real iMessage bridge. But the "AI" sits at the edges (vision, parsing, prose) and a judge could read the core as a rules engine with LLM decoration. eBay listing is sandbox. |
| Reliability & evaluation (25) | 8 | Invariants, property tests, sim grid vs baselines, ledger. Stronger than almost any hackathon project on this line. |
| Usefulness (20) | 7 | Real pain, whole chore removed. But "one item, one deadline" is a narrow wedge; people sell a few times a year. |
| Originality (15) | 6 | The frontier and "set a deadline, not a price" are fresh. The surface pattern-matches to "AI helps you sell stuff", which is crowded. |
| Demo clarity (10) | 8 | One item, one failure, one recovery. Risk: time compression confuses viewers if not narrated. |
| **Weighted** | **7.2** | |

**Weaknesses to attack, in priority order**
1. Where is the agent? The money-moving core must stay deterministic, but judges need to see multi-step agentic reasoning somewhere central, not only in prose rendering.
2. The market is half staged: eBay sandbox has no buyers; local buyers are teammates. The demo needs a buyer side that feels real.
3. Originality is carried by one framing (the frontier). Needs a second distinctive mechanism.
4. Usefulness is capped by the single-item scope; "raise $600 by tomorrow" is the more compelling ask.
5. Demo risk stack: iMessage bridge, time compression, live Stripe declines.

**Candidate directions to test in later iterations** (not yet adopted)
- Deadline-triggered flash auction among warm leads (mechanism design inside iMessage)
- Courier pickup via DoorDash Drive or Uber Direct instead of, or in addition to, a shipping label: the seller never leaves home
- Ghost counterfactual: run the static-listing policy in parallel and show both timelines live during the demo
- Portfolio mode: "raise $600 by tomorrow, don't sell my monitor"
- Explainable receipts: seller asks "why did you drop the price?" and gets the ledger-backed answer
- Red-team eval: adversarial buyer agents try to extract the floor; zero leaks shown as a number
- Multi-photo condition grading with damage detection driving the price

---

## Iteration 1 · 00:02 to 00:15 · Who is judging, and what they reward

**Research** (subagent, 32 web lookups; sources inline)
- **Arga Labs** (Phillip Li CEO, ex-Amazon; Akira Tong CTO, ex-Stripe, brothers). YC-backed, $10M seed led by General Catalyst (TechCrunch, 2026-08-26). Builds high-fidelity **digital twins of enterprise software** (Salesforce, Stripe, Slack, GitHub, Gmail, Workday; 17 twins) with permissions and webhooks intact, so multi-app agents can be trained and tested against realistic scenarios instead of stateless mocks, with automated evals per commit. Li's stated hard problem: **cross-system ambiguity**, e.g. is this Salesforce lead the same company as a colleague's HubSpot outreach. https://techcrunch.com/2026/08/26/arga-is-building-a-better-way-to-train-enterprise-ai-agents · https://www.argalabs.com
- **Lemma AI** (Jerry Zhang, Cole Gawin; YC F25; $2.3M pre-seed from Matrix, YC, Comma Capital). Production observability for agents, built around **semantic failures**: the agent executes every step "successfully" and still produces the wrong result, misreads intent, or calls the wrong tool. Traces 1M+ runs/day, root-causes, proposes fixes. Blog: "A Taxonomy of Agent Failures", "How to Choose an Agent Harness in 2026" ("match your tool to your problem, ship something"). Gawin: a lemma is a small proven proposition used to build a larger proof; "reliable steps create trustworthy systems". https://www.uselemma.ai/blog · https://www.unite.ai/lemma-raises-2-3m-pre-seed-to-tackle-silent-ai-agent-failures-in-production
- **Userlens** (Ankur Dahama, Hai Ta; YC S26). "AI CSM" for B2B SaaS: stitches PostHog/Amplitude, HubSpot/Salesforce, Stripe, Intercom into churn flags and auto-generated QBR decks. Their product is the brief: 3+ apps in, **one decision-ready output** out. https://www.ycombinator.com/companies/userlens
- **Fifth judge** not on our list: Shlok Mundhra, founding engineer at Clera (hardware-AI). The second host "CC" is very likely **Comma Capital** (a Lemma investor); not visually confirmed. /rules and /faq pages 404.

**What this panel rewards** (grounded in the above)
1. Evidence of testing over polish. A demo with no evals reads as exactly the silently-wrong agent Lemma exists to catch.
2. Real, permissioned integrations. Stubbed APIs are the thing Arga's founders critique for a living.
3. Resolving ambiguity across systems, not just relaying data.
4. Multi-app signals synthesized into one decision-ready output.
5. Architecture justified by the task; an elaborate multi-agent graph for a simple job reads as poor judgment.
6. A caught or handled failure on screen.
7. A tilt toward operational use cases; both sponsors build enterprise agent infrastructure. Our consumer framing is a mild headwind, not a wall: the rubric line is "usefulness", not "enterprise".

**Critique of v1 against this panel**
- Our reliability plan is already what Lemma's founders would design. But we describe it in our words. Naming it in theirs costs nothing and lands harder.
- Our simulator exists because eBay's sandbox has no buyers. That is precisely Arga's thesis (mocks vs faithful replicas). We should call it what it is: a **marketplace twin**, and run the agent against it per commit.
- We have one failure beat (payment declined) and it is an infrastructure failure. The panel's signature failure class is semantic: every step succeeded, the outcome is wrong. We have none on screen.
- Cross-system ambiguity is in our domain and unexploited: the buyer who texted and the buyer who clicked "buy now" on the offer page may be the same person; two XM5 listings and one XM4 in the comps; one item live on two channels that must sell once.
- The agentic core is invisible. The twin gives us a place to show agent-vs-agent negotiation without putting an LLM in charge of money.

**Change → v2** (framing and four additions; the engine, apps, and demo spine are unchanged)
1. **Marketplace twin.** Rename `sim/` to `twin/` in the plan. It is a faithful replica of a two-sided market: Poisson arrivals, willingness to pay, ghosts, flaky payers, latency, fees. `pytest` runs the agent against the twin on every commit. The brief says why it exists in Arga's terms: the eBay sandbox is a stateless mock with no buyers.
2. **Semantic-failure catch on screen.** Add a second failure beat to the demo: the negotiation model drafts "sure, $165 works" for a buyer; the guard rejects the draft because $165 is below the floor; the template reply goes out at $187; the ledger shows the rejected draft next to the sent message. Every step "succeeded"; the outcome would have been wrong; the guard caught it. Also add a failure taxonomy to the brief (infrastructure / semantic / adversarial / timing), with one test per class.
3. **Buyer identity resolution across channels.** New invariant I11: one buyer identity per person across iMessage handle, offer-page email, and Stripe customer, resolved before any demand count or checkout. Prevents double-counting interest and issuing two checkouts to one person under two names. This is Li's cross-system ambiguity problem in our domain, and it is real, not decorative.
4. **LLM buyer personas inside the twin, for the red-team eval only.** Thirty scripted personas (lowballer, "what's your floor", ghoster, flaky payer, polite haggler) each run by Claude with a hidden willingness to pay. The numeric grid stays numeric and cheap. The personas test negotiation text: zero floor leaks, counters stay within bounds, realized price vs oracle. This is where "where is the agent" gets answered: agent-vs-agent, measured.
5. **One-line ops path in the brief**, not in the build: the same engine liquidates an office move (40 monitors by the 30th) or aging dealer inventory. Consumer is the wedge because the demo is cleaner.

**Scorecard v2**
| Criterion | v1 | v2 | Why |
|---|---|---|---|
| Technical execution (30) | 7 | 7.5 | Identity resolution across three systems, the twin as CI, agent-vs-agent evals |
| Reliability & evaluation (25) | 8 | 9 | Failure taxonomy with a test per class, a semantic failure caught on screen, the twin framed as what it is |
| Usefulness (20) | 7 | 7 | Unchanged; the ops path is narrative only |
| Originality (15) | 6 | 6.5 | "Liquidity router tested in a marketplace twin" is a more distinctive combination than "AI seller" |
| Demo clarity (10) | 8 | 8.5 | Two failure classes, both caught, both explained by the ledger |
| **Weighted** | **7.2** | **7.7** | |

**Cost of the change on Sunday**: about 45 minutes. Renames are free. The rejected-draft beat is a ledger row plus a dashboard line. I11 is one table (`buyer_identity`) and a resolver in the router. Personas are a prompt file plus a 30-run script; only run once.

**Next iteration**: first-place winners at TreeHacks, HackMIT, HackHarvard, Cal Hacks, PennApps, and AI-agent hackathons 2024 to 2026. Derive what separates first from third. Refine the rubric. Then test the candidate directions (flash auction, courier pickup, ghost counterfactual, portfolio mode) against those patterns rather than against my taste.

> 00:17 · cadence changed by the user from about 50 minutes to every 15 minutes. From here, research passes and synthesis passes alternate to keep usage in check.
> 00:20 · user: depth over thrift. Every pass from here is a full research pass; usage is not a constraint.

---

## Iteration 2 · 00:20 to 00:45 · What first-place projects have in common, and what is actually open

**Research** (two subagents, five sub-reports, roughly 300 web lookups; sources inline, uncertain items flagged)

### A. First-place patterns, 2023 to 2026
Events covered: TreeHacks 2025/2026, HackHarvard 2024/2025, Cal Hacks 10/11/12, PennApps XXVI, Hack the North 2025 (finalist tier only), Anthropic Opus 4.6/4.7/4.8 hackathons, OpenAI GPT-5 and Codex hackathons and Build Week 2026, YC Agents and Browser Use hackathons, Supabase x YC, MCP birthday hackathon, Descope MCP, lablab Arc and Milan, Great Agent Hack (Holistic AI x UCL), Microsoft AI Agents 2025.

1. **Domain reality beats novelty, and judges say so out loud.** CrossBeam (a lawyer automating permit corrections, Anthropic 4.6 grand prize; judge: "expertise trumps coding"), Medkit (a physician's clinical simulator with three faculty pilots, 4.7 grand prize; pilot interest was the stated selection reason), veTriage (a vet piloting in her own clinic, OpenAI Build Week), Deals Machine (sales agent, Milan; 30 pilot teams within weeks). https://claude.com/blog/meet-the-winners-of-our-built-with-opus-4-6-claude-code-hackathon · https://claude.com/blog/meet-the-winners-of-built-with-opus-4-7-claude-code-hackathon · https://developers.openai.com/blog/build-week-winners
2. **"AI does the interpretive layer; deterministic code does whatever must be correct."** Stated explicitly by four OpenAI Build Week winners (Echo Canvas: "AI is most reliable as a constrained authoring layer"; Sentinel: "constraining a model is harder than prompting one"; Mechanica's docent declines to answer without evidence; Dấu defers when unclear). Our engine design is this pattern exactly. It is now evidence, not taste.
3. **Reliability wins when it is the product's visible mechanism, not a slide.** Cite-Before-Act MCP (human approval gate before any state-mutating call) took the grand prize at the MCP birthday hackathon. Rippletide won the OpenAI Codex hackathon with a "decision and evaluation layer" ("outputs vs outcomes"). Browser Brawl won YC's Browser Use hackathon with an agent-vs-agent arena that generates eval traces, after judges warned it was "a research rabbit hole". Jailbreak Lab swept all three tracks at the Great Agent Hack. Hack the North's computer-use track was judged by benchmark score with reruns. https://gradio.app/mcp-birthday-winners · https://www.rippletide.com/resources/blog/winning-the-openai-codex-hackathon-moving-from-outputs-to-outcomes-the-decision-layer · https://stack.convex.dev/the-real-reason-y-combinator-is-using-convex · https://cua.ai/blog/hack-the-north
4. **Simulate before you act is a winning mechanic in commerce.** Waddle (OpenAI GPT-5 hackathon, first of 93 teams) builds synthetic shoppers from real conversation data and simulates how a price or promotion will perform before it ships. It is the one winner found that touches both commerce and evals. https://blog.gentooai.com/waddle-wins-first-place-at-the-openai-gpt-5-hackathon/
5. **Guarded money movement is respected.** OmniAgentPay (lablab Arc champion) wraps wallets in a "Safety Kernel" of atomic spending guards: budget caps, rate limits, whitelists. Judges chose it over the crowd favorite. https://lablab.ai/ai-hackathons/agentic-commerce-on-arc/live
6. **Physical-world stakes separate winners at collegiate hackathons.** Shepherd (motorized cane, TreeHacks 2026, <50ms latency cited), Post Surgery Pillow (HackHarvard 2025; team noted competitors were "software only"), Duet (EEG music, Cal Hacks 11), FaceTimeOS (remote Mac control, Cal Hacks 12). https://devpost.com/software/raising-cane · https://devpost.com/software/post-surgery-pillow-psp
7. **Winners front-load spec and evals.** Maieutic spent two days on design before code; MaestrIA built a ground-truth eval set before features; Sustain-ify spent the first 10 of 36 hours choosing the idea.
8. **Retellable in a sentence.** Cal Hacks 10 winner on why they won: "you have to be able to explain it to someone who's never seen your product before."

**Anti-patterns with evidence**
- Hiding unreliability in the demo. FaceTimeOS removed clicking and forced keyboard-only control because the agent could not click reliably (team retrospective, https://blog.dylanlu.com/cal-hacks-12/). It won at Cal Hacks; in front of Lemma's founders it would be the thing they catch.
- Crowd favorite is not the judged winner. In two of three lablab events the champion had fewer community votes than second and third.
- Pure chatbot interfaces and full autonomy with no approval gate read weaker in commerce contexts (MACH Alliance commerce hackathon recap: "orchestration over chat", human-in-the-loop). https://machalliance.org/insights-hub/from-who-showed-up-to-what-they-built
- Big teams and slide-heavy pitches. A repeat winner's own formula: "useful + unexpected", one coder one generalist one support, live demos over slides. https://maven.com/p/41380d/how-i-won-first-places-in-the-yc-and-open-ai-hackathons
- Demo mechanics (length, live vs recorded) are almost never documented publicly. Our two-minute video is a constraint of this event, not a pattern to copy.

### B. Landscape and technical levers (as of September 2026)
- **Whitespace confirmed, closing fast.** No product combines deadline-conditioned pricing, multi-channel best-execution routing, and chained auto-fulfillment. "Sell it for me" concierges are launching monthly: Listx (lists, negotiates, ships, 5% fee), ClearList (live; the only deadline-like feature found, an optional 24h pickup window), Resell Agent, reWearwolf, Commonplace. Cross-listers (Vendoo, List Perfectly, Crosslist) post but do not negotiate or fulfill. Worthy runs a 48-hour multi-buyer auction for jewelry, the closest production analog to best execution. Our differentiation must be the engine, not the concierge.
- **Courier pickup is achievable same-day.** DoorDash Drive has self-serve signup, an immediate sandbox, and a delivery simulator that advances statuses without a real Dasher. Uber Direct is business-gated and region-limited; Roadie and Curri need sales contact. https://developer.doordash.com/en-US/docs/drive
- **Agentic payments are real in test mode.** Stripe Shared Payment Tokens have a no-approval test path (`/v1/test_helpers/shared_payment/granted_tokens`, then a normal PaymentIntent). Google AP2 is fully open but proves consent, not settlement. OpenAI/Stripe ACP, Visa, Mastercard, PayPal's agent program are partner-gated. https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens · https://github.com/google-agentic-commerce/AP2
- **Instant buyback has no public API anywhere** (Gazelle, Decluttr, Amazon, Apple, Best Buy), and their terms ban scraping. The instant quote stays modeled or human-pasted. Back Market's API is gated to vetted refurbishers.
- **eBay specifics.** Marketplace Insights (sold data) is restricted and rarely granted. The Negotiation API (`sendOfferToInterestedBuyers`) exists but only for Trading-API listings and its sandbox is mocked. The Inventory API supports Best Offer thresholds: `listingPolicies.bestOfferTerms.autoAcceptPrice` and `autoDeclinePrice`. The Analytics API `getTrafficReport` exposes `LISTING_VIEWS_TOTAL` in production. https://developer.ebay.com/api-docs/sell/negotiation/overview.html

**Critique of v2 against the evidence**
- Pattern 2 and pattern 3 are already our architecture, but the eval harness is still framed as a test tool that lives next to the product. Waddle and Browser Brawl won by making simulation *the product's mechanism*. We can do the same: the frontier should be the output of simulation, on screen.
- Pattern 6: our physical-world touch is a shipping label PDF. A courier arriving at the door is a much stronger "the agent acted in the world" beat, and the sandbox makes it demoable.
- Pattern 1: our demo item should be a real thing a teammate actually wants gone, with real photos and real comps, and the video should say so.
- Pattern 5: our guard is the equivalent of a Safety Kernel. It needs a name and a visible place on screen where rejected actions appear.
- The concierge landscape means "lists and negotiates for you" is table stakes by 2026. "Sets a deadline and prices by simulation" is not.

**Change → v3**
1. **Liquid prices by simulation, visibly.** On intake, the marketplace twin runs 1,000 seeded markets for *this item* (its comps, spread, category priors, the seller's deadline). The frontier card is the read-out: "I ran your headphones through 1,000 three-day markets. 87% sold above $205; the median clearing price was $211." The dashboard shows the histogram. The closed-form model in docs/03 stays as the per-tick policy; the Monte Carlo is the same twin with the item's parameters and it also validates the closed form (they must agree within a few dollars, and that agreement is itself a test). The eval harness and the pricing engine become one thing, which is the single most on-brand move available for this panel.
2. **Courier pickup for local sales via DoorDash Drive (P0), Shippo moves to P1.** Demo beat: "sold to priya for $187. a dasher picks it up at 4:10 today; you don't need to be home." The sandbox simulator walks the delivery through created → picked up → delivered on the dashboard. Google Calendar stays: the pickup window goes on the seller's calendar.
3. **The Guard gets a name and a screen.** Every action passes through "the Guard" (docs/05's guard layer). The dashboard has a permanent Guard panel listing accepted and rejected actions with the invariant that fired. The semantic-failure beat from v2 plays there.
4. **eBay listing carries the floor.** When the sandbox listing works (P1), `autoDeclinePrice` is set to the floor and `autoAcceptPrice` to p*, so the marketplace itself enforces the same invariant the Guard does. One sentence in the brief; ten minutes of code.
5. **A real item.** The demo sells something a teammate genuinely wants gone. Real photos, real comps, the seller's real deadline. Say it in the first five seconds.
6. Parked for iteration 3, not adopted: a buyer-agent exit path via Google AP2 mandates settled with Stripe Shared Payment Tokens (timely, technically deep, risks confusing a two-minute story); a deadline-triggered flash auction among warm leads (Worthy precedent; mechanism-design depth).

**Scorecard v3**
| Criterion | v2 | v3 | Why |
|---|---|---|---|
| Technical execution (30) | 7.5 | 8 | Per-item Monte Carlo pricing, courier dispatch with webhooks, floor mirrored into eBay's own thresholds, Guard on screen |
| Reliability & evaluation (25) | 9 | 9.5 | The pricing engine is the eval harness; agreement between closed form and simulation is a test; two failure classes caught on screen; identity resolution |
| Usefulness (20) | 7 | 7.5 | Courier pickup removes the seller's last chore; the seller does nothing after the first text |
| Originality (15) | 6.5 | 7.5 | Landscape confirms whitespace; pricing by simulation plus a deadline is not in any concierge; the frontier is a genuinely new object |
| Demo clarity (10) | 8.5 | 8.5 | The courier beat is vivid. Risk: too many beats; the calendar shot shrinks to one second |
| **Weighted** | **7.7** | **8.25** | |

**Cost of the change on Sunday**: DoorDash Drive sandbox about 60 minutes (JWT auth, create quote, accept, simulator webhooks). Monte Carlo per item reuses the twin: seconds of compute, 30 minutes of wiring, 30 minutes for the histogram. Guard panel 20 minutes. Net: about two hours moved from Shippo, dashboard polish, and the P1 eBay listing.

**Next iteration**: (1) de-risk DoorDash Drive: exact sandbox auth, endpoints, simulator behaviour; (2) decide the parked items with evidence: study Worthy's 48-hour auction and revenue-management literature on deadline pricing (Gallego and van Ryzin, perishable inventory) to ground the frontier academically for the brief; (3) look at how the strongest recent winners structured their demo videos, since this event judges from a video.

---

## Iteration 3 · 00:53 to 01:08 · De-risking the courier, grounding the math, structuring the video

**Research** (three subagents, about 130 lookups)

### A. DoorDash Drive is feasible on Sunday (primary sources: developer.doordash.com)
- Self-serve developer account, sandbox keys issued immediately (developer_id, key_id, signing_secret). Production is gated; sandbox is all the demo needs. https://developer.doordash.com/en-US/docs/drive/tutorials/get_started/
- Auth: JWT HS256 with header `{"alg":"HS256","typ":"JWT","dd-ver":"DD-JWT-V1"}`, claims aud "doordash", iss = developer_id, kid = key_id, iat, exp (max 30 min), signed with the **base64url-decoded** signing secret. The docs ship a PyJWT example. https://developer.doordash.com/en-US/docs/drive/how_to/JWTs/
- Endpoints: `POST /drive/v2/quotes` → `POST /drive/v2/quotes/{external_delivery_id}/accept` (returns `tracking_url`, `fee`, ETAs) or `POST /drive/v2/deliveries` directly; `GET /drive/v2/deliveries/{id}`. Required: external_delivery_id, pickup_address, pickup_phone_number (E.164), dropoff_address, dropoff_phone_number, order_value in cents; either pickup_time or dropoff_time, never both. Reused external ids return 409.
- Sandbox: the portal's Delivery Simulator advances a test delivery through created → confirmed → arrived_at_pickup → picked_up → arrived_at_dropoff → delivered, and **webhooks fire on every transition** (register an HTTPS URL per environment, Basic Auth). Events: DASHER_CONFIRMED, DASHER_PICKED_UP, DASHER_DROPPED_OFF, DELIVERY_CANCELLED. Test deliveries auto-cancel after one hour, so reset before each take. https://developer.doordash.com/en-US/docs/drive/how_to/use_delivery_simulator/ · https://developer.doordash.com/en-US/docs/drive/how_to/webhooks/
- Unverified: whether an `auth-version: v2` header is needed (secondary sources say yes, the primary page shows only Bearer; try without). Whether non-US addresses work in sandbox.
- Fallback: Uber Direct test mode has a "Robo Courier" that auto-advances statuses on a timer (`test_specifications.mode: "auto"`), which is better for an unattended run, but signup is business-oriented and region-limited. https://developer.uber.com/docs/deliveries/guides/robocourier

### B. The math has a name, and one part of ours is wrong
- **Gallego and van Ryzin (1994)**, single perishable unit, price-dependent Poisson demand, hard deadline: the optimal price is monotone decreasing in remaining time, and for one unit active repricing strictly beats any fixed price. Our ticks are their state variables. https://dl.acm.org/doi/10.5555/2827835.2827840
- **Karlin (1962), McCall (1970)**, the asset-selling problem: the optimal policy is a single reservation price equal to the **continuation value**; accept any offer at or above it. With recall (a rejected offer stays available) the state becomes "best offer so far", and recall never hurts.
- **Aviv and Pazgal (2005)**: Gamma prior on the unknown Poisson arrival rate, updated from observed inquiries, is the standard closed form. Exactly our demand update. **Besbes and Zeevi (2009)**: greedy exploitation on thin data can be badly suboptimal; allow brief exploration early.
- **Almgren and Chriss (2000)**: selling over a horizon trades cost against variance; the efficient frontier between "sell now" and "sell slowly" is our liquidity frontier, relabeled.
- **Bulow and Klemperer (1996)**: an auction with one extra bidder and no reserve beats the best optimized negotiation with one fewer bidder. eBay Best Offer studies find sequential bargaining raises sale probability (about 3%) but not price; simultaneous competition is what raises price. Worthy runs a 48 to 72 hour multi-buyer auction in production. Harvard's "negotiauction" guidance: choose the mechanism by expected bidder count.
- Certainty premiums in the wild: Opendoor offers average 8.8% below eventual resale, Offerpad 13.9% (2023 to 2025 sample; secondary citation); instant car offers run 10 to 15% below private-party value; StockX frames "Sell Now" vs "Ask" as speed vs price.

**The correction.** docs/03 scores a price by `P(τ, p)·net(p) + (1 − P)·S`, which silently assumes we hold price p for the whole remaining horizon and then take salvage S. The literature's answer is a finite-horizon dynamic program: the value of having the item with τ left is
```
V(τ) = max over p of [ λ(p)·Δ · n̄(p) + (1 − λ(p)·Δ) · V(τ − Δ) ],    V(0) = S
```
solved backward over a time grid (a few hundred steps times a price grid, milliseconds in numpy). The price path p*(τ) falls out of the recursion; the reservation price for any offer is V(τ) itself; and the frontier is read off V and a forward pass for P(sale by h). Same inputs, same monotone behaviour, but now every accept/counter decision is "offer versus continuation value", which is the result a finance-literate judge will recognize. Standing offers with expiries give us the recall variant for free: the state carries the best valid standing offer, which can be taken later if V(τ) drops below it.

### C. Demo video rules with evidence
- Devpost: say what it does in the first few seconds; narrated screencast, not a marketing reel; cut mundane flows; never claim a feature you don't show. https://info.devpost.com/blog/6-tips-for-making-a-hackathon-demo-video
- Judges decide whether they care in the first 30 seconds; "if the judge cannot repeat your problem back in one sentence, the rest is noise"; "show something working within about 90 seconds"; "be very direct about what works and what doesn't". https://info.devpost.com/blog/hackathon-judging-tips
- Showing reliability: avoid unexplained jumps from empty screen to perfect result; narrate the failure in plain words before the recovery so the outcome feels earned; never present a recorded fallback as live.
- The critique of last year's Anthropic hackathon winners by Dexter Hadley: demos are "theoretical proof" that never show whether outputs can be audited. https://gigazine.net/gsc_news/en/20260425-anthropic-hackathon/ Our ledger is the direct answer; the video should say the word "audit" once.
- Not obtainable: the actual winner videos (YouTube pages return no transcript to the fetcher). Treat structure advice as guidance, not as copied winners.

**Change → v4**
1. **Replace the objective with the Bellman recursion.** `engine/demand.py` gains `solve_value_function(state) → (V[τ], p_star[τ])`. Reservation price = V(τ). Counter price = the smallest grid price whose reliability-weighted net beats V(τ). Frontier and the Monte Carlo twin both derive from the same λ(p), and "DP price path agrees with the twin's realized clearing prices within tolerance" becomes a test. The brief cites Gallego–van Ryzin, Karlin/McCall, Aviv–Pazgal, Almgren–Chriss in one paragraph. Cost: about 40 lines of numpy, replacing the grid-search objective, not adding to it.
2. **Mechanism routing by lead count (P1).** When at least three warm leads are live and τ is inside the endgame window, the agent opens a timed best-offer round instead of countering one at a time: "3 people want these. i'm running a 30-minute best-offer round; highest verified offer above $X takes them." Winner = highest offer at or above V(τ_end), earliest on ties, then straight to checkout. One or two leads: negotiate as today. Justified by Bulow–Klemperer and the eBay evidence that bargaining converts but competition raises price. Nobody in the concierge landscape chooses the mechanism. Cost about 75 minutes; only if P0 is green by 13:30.
3. **Courier confirmed as P0** with the exact auth and endpoints above. `demo/reset.py` cancels any open sandbox delivery before a take. Uber Direct Robo Courier is the named fallback.
4. **Video restructured on the evidence.** Seconds 0 to 8: the seller's real item and the one sentence ("Liquid sells your stuff by your deadline and never goes below your price"). Something working by 0:20 (the frontier card). Plain-language line for the twin ("we tested it against a thousand simulated buyers before it talked to one real one"). The failure narrated before the reroute. One line on what is real and what is simulated, on screen. The word "audit" once, over the ledger. Repo card at the end. docs/06 to be rewritten in the morning.
5. **Instant quote per category, cited.** 9 to 14% haircut for houses, 10 to 15% for cars, larger for electronics buyback; our 0.72·M for electronics is defensible but should be labeled as a modeled quote with these reference points in the brief.
6. **Exploration note for the brief**: with thin early data the engine reprices no faster than its hysteresis allows; a known limitation, cited to Besbes–Zeevi.

**Scorecard v4**
| Criterion | v3 | v4 | Why |
|---|---|---|---|
| Technical execution (30) | 8 | 8.5 | A real dynamic program each tick with the literature behind it; mechanism routing; courier dispatch with webhooks |
| Reliability & evaluation (25) | 9.5 | 9.5 | Unchanged in kind; the DP-vs-twin agreement test is a better test than closed-form-vs-twin |
| Usefulness (20) | 7.5 | 7.5 | Unchanged |
| Originality (15) | 7.5 | 8 | Choosing the selling mechanism by lead count is not in any product found; the frontier now has a textbook lineage, which reads as depth rather than novelty for its own sake |
| Demo clarity (10) | 8.5 | 9 | Evidence-based opening and failure narration; the "audit" line answers a known critique of past winners |
| **Weighted** | **8.25** | **8.5** | |

**Flag for the morning**: the name Liquid collides with Liquid AI (foundation-model company) and several fintechs. Judges in AI will hear "Liquid AI" first. Not a blocker; worth a two-second look at alternatives like "Liquidate", "Gone", "Sellby" before the title card is made.

**Next iteration**: an adversarial pass. A subagent plays the four judges and asks the ten hardest questions ("why not eBay Best Offer?", "how is this not Listx?", "what if vision is wrong?", "what is actually real?"); we write the answers into the log and change the idea where an answer is weak. Also: what people actually sell under deadlines (moves, campus move-outs, resale communities) to pick the demo item and sharpen usefulness.

---

## Iteration 4 · 01:21 to 01:36 · The panel asks its hardest questions; the demand side gets numbers

**Research** (an Opus subagent playing the five judges plus the host, after reading docs/01, 03, 05 and this log; a Sonnet subagent on demand-side evidence, 42 lookups)

### A. Verdict from the simulated panel
"Top three near-certain and a live shot at first, unless a judge asks what happens when the item is misidentified, because the honest answer today is 'nothing', in front of the one company that sells the detector for it."

### B. The three weakest points, ranked, and the fixes
1. **Nothing detects a wrong market value.** Vision says XM5, it is an XM4, confidence 0.82 so nobody asks; comps are wrong, M is off by $60, every invariant passes, the item sells $60 under. Fix: a value-sanity invariant (I12 below) that cross-checks comps against an independent price prior and asks the seller to confirm the item when they disagree. About 25 minutes, and it buys a third beat where the agent catches itself.
2. **The evidence is self-confirming.** The twin generates the buyers, prices the item, and grades the policy with the same distributional assumptions the engine uses. Fix: 20 hand-collected real sold prices across three archetypes (manual browsing, no scraping) → "our value estimate is off by a median of X%" in the brief; plus a sensitivity sweep of the haircut and priors, showing the seller-set floor protects the seller regardless.
3. **Scope exceeds the window and the fragile parts come last.** Fix: demote mechanism routing and eBay Sell to pitch-only now, freeze P0, record a labeled backup take by 15:00.

### C. The twelve questions, with the answer that satisfies (crib for Sunday's Q&A)
| # | Judge | Question | The answer that lands |
|---|---|---|---|
| 1 | Li | eBay Best Offer already auto-accepts and auto-declines. What does your engine add? | Best Offer is one channel with static thresholds and no clock. We re-solve a finite-horizon program each tick so the reservation price falls with time, and we arbitrate across exits on net proceeds. Show the eval row where the Best Offer proxy nets $98 at 12h and the agent nets $171. |
| 2 | Dahama | Listx lists, negotiates, ships for 5%. What do you give that they won't ship next month? | A commitment surface: $153 now or $205 in three days, chosen by the seller. Concierges optimize one listing; we route between exits and prove the counterfactual per sale. To copy the frontier they have to build the twin. |
| 3 | Li | Your honesty table says the buyers are simulated. Is calling that a sale honest? | Say it first: messaging, comps, money rail, courier, calendar are real; buyers are the twin unless a teammate is texting. Every ledger event carries a REAL or TWIN badge, visible at the moment of sale. |
| 4 | Tong | Vision calls it an XM5, it's an XM4, confidence 0.82. Where does that error die? | Today it doesn't. I12: at least 8 cleaned comps and agreement within 25% between the comps median and an independent price prior, else the agent asks the seller to confirm the model before listing. |
| 5 | Gawin (host) | A floor check is a numeric bounds check. What catches the failure where every step succeeds and the answer is still wrong? | Two runtime detectors: the I12 disagreement check, and a posterior predictive check each tick: if observed inquiries fall outside the 90% interval the model predicted, a red MODEL_DRIFT row appears in the Guard and the prior widens. |
| 6 | Ta | Where did Gamma(2, 24h), 0.92, 0.05, 0.72·M come from, and how wrong can they be? | Invented, because sold data is gated; then updated from evidence. Show the sensitivity sweep. The seller's floor is never engine-moved, so the downside is bounded by the seller, not the priors. |
| 7 | Mundhra | The core is numpy and a rules table. Why is this an agent and not a cron job with a chatbot? | Deliberately: the model never touches money. Agency is multi-step state over a horizon with tool side effects and revision under evidence. The agentic showpiece is thirty Claude buyer personas negotiating against the policy, scored on leaks and realized price. |
| 8 | Tong | Two webhooks land 40ms apart on two workers. An in-process lock doesn't stop a double sale. | The lock is a convenience. The guarantee is a unique partial index on open checkouts per item plus SOLD-terminal in the same transaction; the second write fails at the database. Webhook receipts are keyed by event id. Say the index first. |
| 9 | Dahama | Buyer says "hold it, cash tonight" and never shows. Seller texts "don't sell" at minute 14 of a 15-minute checkout. | No hold exists without a checkout; a failed buyer's reliability halves and the pool re-evaluates immediately. Seller cancel before payment expires the Stripe session; after payment it is a refund, and we say so. (Cancel-before-payment moves to P0.) |
| 10 | Li | Same person texts from a phone, buys on the offer page with another email, third name on the card. Two leads or one? | One, resolved at the router across handle, email, and Stripe customer before it is counted, or the arrival rate inflates and two checkouts can go to one human. I11 lands in the invariant table with a test. |
| 11 | Mundhra | 1,000 items live. What falls over first? | Per-tick solves; cache the value function per (category, M, σ) bucket and recompute on evidence. Then the single Mac and Apple ID behind iMessage, which is a real ceiling and we name it. |
| 12 | Tong | Fourteen P0 features, a DP, a twin, courier auth, identity resolution, four test suites, in six and a half hours. Convince me. | Here is the cut line and what was provisioned before the window (credentials only, no product code). The DP replaces the grid search, it does not add to it. Mechanism routing and eBay Sell are pitch-only. |

### D. Demand side, the numbers worth citing (and the ones not to)
- 11.8% of Americans moved in 2024, roughly 38 to 40 million people (Census ACS via The Hill / Axios). About 400,000 military families PCS each year (militaryfamily.org). Campus move-out: Tufts over 230 tons a year, UNH's waste jumps from 25 to 105 tons in May (resource-recycling.com).
- Mercari's 2023 Reuse Report: US households hold 21.1 billion unused resellable items worth $559.8B, about $4,267 per household.
- OfferUp 2024 Recommerce Report (n=1,500): 54% sold something secondhand in the past year; 60% use the proceeds for bills.
- Why things don't get sold: 77% cite emotional attachment; people are as likely to trash (36%) or give away (35%) an item as to sell it (BehaviourWorks Australia). Self-storage is a $45B industry used by one in three Americans.
- Time pressure costs money: motivated sellers accept measurably lower prices (real estate literature); fire-sale discounts of 8 to 9%, up to 25% in liquidations; garage-sale convention prices at 10 to 30% of retail and cuts a further 25 to 50% near the deadline.
- eBay monthly sell-through is about 31 to 33%; electronics about 31%; earbuds and smartwatches about 41%.
- Depreciation: mainstream headphones lose 40 to 50% a year; iPads about 30% in year one; laptops 25 to 30% in year one.
- Do not cite: the "70% of Facebook Marketplace buyers no-show" figure (vendor marketing); OfferUp's 27 minutes a day (not per listing).
- White space confirmed: no research on deadline-labeled peer-to-peer selling exists. The closest analogues are real-estate guaranteed-sale programs and iBuyers.
- **Demo item: an iPad (Air, about $300 used)** beats the XM5: squarely in the $150 to $400 band, the richest comps, courier-friendly, and a natural deadline story (leaving for a semester abroad, trade-in credit expiring). It also has natural model ambiguity (Air 4th vs 5th generation), which makes the I12 confirmation beat organic rather than staged. XM5 stays as the backup.

**Change → v5**
1. **I12, value sanity (P0).** Before listing: at least 8 cleaned comps, and the comps median must agree within 25% with an independent Claude price estimate made without seeing the comps. On disagreement, or on model ambiguity flagged by vision, the agent texts the seller a one-tap confirmation ("is this the iPad Air 5th gen with the M1? reply 4 or 5"). Third failure class on screen: the agent catching its own misidentification. This is the single change most likely to move a judge from "top three" to "first".
2. **I13, MODEL_DRIFT (P0, small).** Posterior predictive check each tick on inquiries; outside the 90% interval → red Guard row, prior widened, re-solve. Semantic failure detection at runtime, in the host's vocabulary.
3. **Calibration and sensitivity (P0, one person, 45 minutes).** Twenty hand-collected sold prices across three archetypes → median M error in the brief. Twin re-run with the haircut in [0.82, 1.0] and priors ±50% → one table showing realized proceeds and floor breaches (always zero).
4. **Scope freeze.** P0 = F1 to F14 with DoorDash Drive in place of Shippo, plus I11, I12, I13, and seller cancel before payment. Mechanism routing, eBay Sell, Shippo, refunds after payment: pitch-only or P1 after 13:30. Backup take recorded by 15:00 and labeled as a backup if used.
5. **REAL / TWIN badge** on every ledger event and on the dashboard at the moment of sale; one line in the video.
6. **Baseline relabeled.** `static_90` becomes "eBay Best Offer proxy": list at M, auto-accept at 0.9·M, auto-decline below the floor. The comparison then answers Q1 directly.
7. **Demo item: iPad Air**, owned by a teammate, real deadline story, with the model-generation confirmation as the first beat after the photo.
8. **Brief additions**: the demand numbers above; the scale answer (bucketed value-function cache; the single-Mac ceiling); the honest provenance of priors.

**Scorecard v5** (v4 re-scored: the panel showed its 9.5 on reliability was overstated while wrong-value detection and external calibration were missing; 8.5 is the honest v4 number)
| Criterion | v4 (re-scored) | v5 | Why |
|---|---|---|---|
| Technical execution (30) | 8.5 | 8.5 | I12 and I13 add real mechanism; mechanism routing leaves the build; net flat |
| Reliability & evaluation (25) | 8.5 | 9.5 | Wrong-value detection, drift detection, external calibration, sensitivity sweep, REAL/TWIN provenance |
| Usefulness (20) | 7.5 | 8 | The brief can now say who and how many; seller cancel path exists; the item and story are real |
| Originality (15) | 8 | 7.5 | Mechanism routing is pitch-only now; a self-catching pricing agent with a frontier is still not on the market |
| Demo clarity (10) | 9 | 9 | Three catches are one too many for the video; two in the video, the third in the brief |
| **Weighted** | **8.3** | **8.55** | |

**Next iteration**: write the failure section of the brief in the host's own vocabulary (map our tests to Lemma's published taxonomy of agent failures) and check how Arga describes agent evals so the twin is described in terms they use; check the "Liquid" name collision quickly; start a morning briefing draft that consolidates v1 to v5 into one current spec and the exact edits to make to docs/01 to docs/07.

---

## Iteration 5 · 01:47 to 02:02 · Speaking the host's language; the name; the consolidated spec

**Research** (two Sonnet subagents, about 40 lookups; primary sources)

### A. Lemma's actual taxonomy, and where we stand against it
Source: Kostesku, "A Taxonomy of Agent Failures", uselemma.ai/blog/a-taxonomy-of-agent-failures (2026-07-13); Zhang, "Introducing Lemma". Their definition of a semantic failure: the agent "appears to succeed, but the intended work never happened, or happened incorrectly", as opposed to "traditional crashes". Their rule: "none can be detected by inspecting an action in isolation". Seven named classes:

| Lemma class | Their meaning | Our coverage in v5 | v6 adds |
|---|---|---|---|
| Instruction Violation | broke an explicit rule it was given | Floor-breach draft caught by the Guard; leak_check under adversarial buyers | — |
| Hallucination | asserts something with no basis in fact | I12: vision's confident item id disagrees with an independent price prior | — |
| Integration Failure | an external step failed and nothing visible handled it | Payment decline → reroute on the ledger; comps timeout → labeled fallback | — |
| Skipped Work | claimed done, never happened | none | Every "it's up" or "sold" text requires a done outbox row with an external id; test: kill the worker, assert no such text goes out |
| Out of Scope Work | did something not asked | none | I14: seller constraints are Guard-enforced (local_only → no courier or label; ship_ok=false → no Shippo); test with hypothesis |
| Retry Loop | retried forever, or retried with side effects | outbox retries exist but unbounded | Backoff capped at 6 attempts, then a DELIVERY_STALLED Guard row and a dead-letter; on recovery nothing duplicates (idempotency keys) |
| Communication Failure | told the human the wrong thing | seller_voice numeric check | Buyer told "sold" only after SOLD; test that every number in any outbound text exists in the ledger row that produced it |
| (unnamed) | plan executed faithfully, world model behind it was wrong | I13 MODEL_DRIFT posterior predictive check | Present it as the class their taxonomy does not name yet, in one sentence, without presuming |
| (outside their frame) | crashes and restarts | outbox + webhook receipts survive a restart | keep in the brief under "the crash half" |

Arga's own vocabulary (argalabs.com, YC launch, TechCrunch 2026-08-26): "stateful service twins", "realistic replicas", the unit is a "scenario", twins carry "permissions" and "support webhook events", and evals "define judging criteria and grade performance for every commit or PR". Li's quote on record: "Can the agent correctly identify that these two are the same company?" The phrases "grader", "per-commit evals", and "stateless mock" are press paraphrase, not their copy; use "twin", "scenario", "every commit". Userlens: "Decision-Ready Insights", "QBR decks", "talking points", "churn risk", apps stitched "into one view".

**Brief section headings, in their vocabulary**: "Failure modes and catches" · "Twin, not mock: what the simulator reproduces" · "Cross-system identity resolution" · "What is real, what is twin, what is decision-ready". Sample paragraph to adapt: "The Guard checks against named failure classes, not one price rule: instruction violations (a drafted counter that would break the seller's floor), hallucination (a confident item id that disagrees with an independent price prior), and integration failures we recover from on the ledger instead of silently, including a decline that reroutes to the next buyer. The market the engine trades against is a stateful twin, not a stateless mock of eBay and Stripe: it replays duplicate and out-of-order webhooks, ghosts, and flaky payers, so the eval grid means something before a real buyer sees the item. Because one person can text the agent, click buy now on the offer page, and pay under a third identifier, we resolve identity across channels before counting a lead. What the seller gets back is decision-ready: one ledger row with the inputs, the reason, and the price before and after."

### B. The name
- Liquid AI (liquid.ai): MIT spinout, LFM foundation models, about $2.35B valuation, $297M raised. The first thing an AI-infra judge hears.
- Liquid / Co-Invest (liquid.trade): $18M Series A in April 2026; trades 500+ markets **inside ChatGPT and Claude** via a connector. Closest possible collision for this audience.
- Also: Liquid.com (defunct crypto exchange), Liquid Group (Singapore payments), Liquid Web (hosting), Liquid Death, Shopify's Liquid template language, LiquidText.
- The subagent's recommendation: rename. A qualifier on the title card ("Liquid: sell by Sunday") helps but the bare word still fires recognition first.
- Alternatives it checked: gone (collides with Gone App, same category, 2013), sellby (four live apps), liquidate (B2B and bankruptcy flavor), cashout (genericized), offload (OFFLOADIT, B2B), clearout (Clearout.io SaaS), bythen (funded Indonesian AI startup), **dueby** (only small indie invoicing apps; the cleanest of the eight). Not checked: soldby, lastcall, outgo. No trademark or domain search was run.
- **This is the user's decision, not mine.** The name Liquid was chosen deliberately. The evidence is here for a two-minute decision in the morning; nothing in the plan depends on it.

**Change → v6**
1. **Failure matrix, one test per class.** The brief's failure section becomes a table over Lemma's seven classes plus drift plus crash, each with the catch, the test file, and the demo beat if any. New tests: Skipped Work (no "it's up" without a done outbox row), Out of Scope Work (I14 constraints), Retry Loop (capped backoff, dead-letter, no duplicates on recovery), Communication Failure (numbers in texts must exist in the producing ledger row; "sold" only after SOLD).
2. **I14, constraints are invariants.** local_only, ship_ok, instant_ok are enforced by the Guard on every fulfillment action, not just consulted by the policy.
3. **Brief written in the vocabulary above**, without pandering: twin, scenario, every commit, decision-ready, semantic failure.

**Scorecard v6**
| Criterion | v5 | v6 | Why |
|---|---|---|---|
| Technical execution (30) | 8.5 | 8.5 | Unchanged |
| Reliability & evaluation (25) | 9.5 | 9.7 | Full coverage of the host's seven classes with a test each, plus the class they don't name; capped retries and dead-letter close a real gap |
| Usefulness (20) | 8 | 8 | Unchanged |
| Originality (15) | 7.5 | 7.5 | Unchanged |
| Demo clarity (10) | 9 | 9 | Unchanged |
| **Weighted** | **8.55** | **8.6** | |

---

## Current idea · v6 · consolidated (02:02)
**One sentence.** Text a photo and a deadline to an iMessage contact; Liquid tells you what the item is worth now versus by your deadline, then sells it for the most money that actually clears in time, never below your floor, and books the courier, and it catches its own mistakes on the way.

**What the seller experiences.** Photo + "gone by sunday 6pm, not under 170". A confirmation if the model is ambiguous ("iPad Air 4th or 5th gen? reply 4 or 5"). A frontier card from a thousand simulated markets: $X guaranteed now, ~$Y likely today, ~$Z likely by the deadline, opening price, floor promise. Silence until something changes. Check-ins with reasons. One question only if the deadline nears with no executable offer at or above floor. A sold summary with the counterfactual and the courier pickup time. Nothing else to do.

**Engine.** Finite-horizon dynamic program each tick (Gallego–van Ryzin; Karlin/McCall reservation price = continuation value); arrival rates learned online (Gamma-Poisson, Aviv–Pazgal); channels arbitrated on net proceeds; standing offers with expiries give recall; hysteresis on repricing; escalation window; payment window; reroute on failure. Frontier and Monte Carlo from the same twin.

**Guard (invariants I1 to I14).** Floor · one live checkout, SOLD terminal, expire-before-reissue · no accept after deadline · SOLD only on verified payment ≥ agreed · fulfillment ordering · idempotency and webhook receipts · ledger row per action in the same transaction · floor changes only from the seller · no leaks in buyer text, every figure equals the allowed price · price never rises while live · I11 identity resolution across handle, email, Stripe customer · I12 value sanity (≥8 comps, comps vs independent prior within 25%, else confirm with seller) · I13 MODEL_DRIFT posterior predictive check · I14 seller constraints enforced on fulfillment.

**Apps (all real).** iMessage via BlueBubbles on a Mac with a dedicated Apple ID · eBay Browse (comps, production) · Stripe Checkout with real declines · DoorDash Drive sandbox with simulator webhooks · Google Calendar · Claude for vision, intent, comps filtering, negotiation drafts, seller voice. Pitch-only: eBay Sell listing, Shippo, mechanism routing (flash round by lead count), agentic checkout via Stripe Shared Payment Tokens, portfolio mode.

**Evidence.** Marketplace twin (2,400 seeded runs across 4 deadlines × 3 archetypes vs static, eBay-Best-Offer proxy, linear markdown, oracle) · DP-vs-twin agreement test · sensitivity sweep on haircut and priors · 20 hand-collected real sold prices → median value error · property tests over random event sequences · webhook tests · chaos tests · 30 LLM buyer personas red-teaming leaks · failure matrix over the host's seven classes · REAL/TWIN provenance on every ledger event.

**Demo (120s).** Real iPad Air, real deadline. 0:00 the sentence and the photo · 0:08 the ambiguity confirmation · 0:18 the frontier card and the histogram · 0:30 the clock runs, a reprice with its reason · 0:50 a buyer offer, a counter with the numbers · 1:05 accept, pay link · 1:15 decline narrated, expire, reroute, new link · 1:30 paid, courier dispatched, status advancing, calendar · 1:40 the sold text with the counterfactual · 1:48 the eval table and the failure matrix · 1:56 what was real, repo card.

**Exact edits to make in the morning** (none applied yet)
- docs/01: F10 → DoorDash Drive courier (Shippo to P1); F18 cancel-before-payment → P0; add F20 value-sanity confirmation; demo persona → iPad Air; add the demand numbers to the thesis.
- docs/02: `sim/` → `twin/`; add `buyer_identity` table and `fulfillment/doordash_client.py`; add `engine/value_function.py`; Guard panel in `web/dashboard.py`; REAL/TWIN column on LedgerEvent.
- docs/03: replace the objective section with the Bellman recursion; reservation price = V(τ); add citations; add MODEL_DRIFT check; add I12 pre-listing check; instant quote per category with reference points.
- docs/04: add DoorDash Drive section (auth, endpoints, simulator, webhooks) from iteration 3; Shippo demoted; note eBay Best Offer thresholds.
- docs/05: I11 to I14 in the invariant table with tests; failure matrix in Lemma's classes; relabel `static_90` as the eBay Best Offer proxy; calibration and sensitivity sections; provenance badges.
- docs/06: rewrite the script per the 120s structure above; add the honesty line; the word "audit" over the ledger; backup take rule.
- docs/07: convert to Eastern time (build 12:30 to 19:00 EDT), freeze P0 as v6, move mechanism routing and eBay Sell to pitch-only, add the calibration task and the 15:00 backup take.
- docs/09: headings in the host's vocabulary; the twelve-question crib as an appendix.
- Decide the name.

**Next iteration**: real reference prices for the demo item (published price guides and trade-in pages for an iPad Air, no scraping) so the instant quote in the demo can be a real published number rather than a modeled one, and the calibration set has a head start.

---

## Iteration 6 · 02:11 to 02:24 · Real numbers for the demo item; a pre-mortem of Sunday

**Research** (Sonnet on prices, 32 lookups, no scraping; Opus on the pre-mortem after reading docs/02, 04, 07, 08 and this log)

### A. The frontier can be real numbers (observed 2026-09-13)
iPad Air 5th gen (2022, M1, 64GB Wi-Fi, good):
- Market: Swappa average **sale $310** (list $367) https://swappa.com/prices/apple-ipad-air-5th-gen · BankMyCell "Good" $230 · Back Market refurb about $303 (estimate). Median reference **M ≈ $303**.
- Instant: BankMyCell best offer **$221** (GadgetPickup; Whiz Cells $220) https://www.bankmycell.com/sell/ipad-air-5-2022 · BuyBackWorld $190 (cross-confirmed on Swappa's trade-in aggregator) · SellCell "top price $280" (configuration unclear) · Apple Trade In shows only a blended "up to $490" for the newest Air; per-generation values are form-gated · Gazelle, Decluttr, Amazon, Back Market BuyBack all gated.
- **S/M ≈ 0.73.** Our modeled 0.72 haircut for electronics is validated by market data, slightly conservative. Cite this in the brief.

iPad Air 4th gen (2020, A14, 64GB Wi-Fi, good): Swappa sale $241, BankMyCell Good $180, SellCell $220 → **M ≈ $220**; best instant **$166** → S/M ≈ 0.75.

The confirmation beat is worth real money: Air 4 and Air 5 share an identical chassis and colors; the Air 5 is worth 30 to 40% more. Model numbers: A2316 (Air 4 Wi-Fi) vs A2588 (Air 5 Wi-Fi); Settings → General → About shows it. Accessory sellers bundle "A2588 A2589 A2591 A2316" together, evidence that buyers confuse them routinely. https://support.apple.com/en-us/108043

Depreciation: no per-SKU series exists; generic curves say year one retains 70 to 73%, year three about 40%; the Air 5 at 4.5 years retains 38 to 52% of its $599 launch price.

**Demo numbers to pre-fill** (Air 5, floor $220, deadline 72h): guaranteed now **$221** (real, sourced), likely today about $280, likely by the deadline about $305, opening price about $330. The instant path has no API, so "take the guaranteed $221" is a text with the vendor link; say so.

### B. Pre-mortem: the ten ways Sunday goes wrong, and the cheap fixes
| # | Failure | Bites (ET) | Cheapest mitigation |
|---|---|---|---|
| 1 | Three tracks build islands that meet at 16:00; nothing walks end to end | 16:00 | All three build one walking skeleton first (webhook in → tick → text out) before splitting; `ItemState` and `Action` frozen by 08:30 |
| 2 | Video recorded too late | 17:45 | Record an unedited backup take the moment the first dry run is green (~16:00), before freeze |
| 3 | ngrok URL rotates and silently kills three webhook registrations | any restart | Reserved ngrok domain at 07:00; `scripts/set_webhooks.py` re-registers Stripe and DoorDash by API; dashboard shows "last inbound: Ns ago" per channel |
| 4 | BlueBubbles inbound wrong: two events per photo, HEIC, Full Disk Access, `message` vs `text`, phone falls back to SMS | 07:00 if front-loaded | Full round trip from every phone at 07:00; pin the field name in `.env`; 3s thread buffer keyed by chat guid from line one; HEIC conversion in the download path |
| 5 | Stripe signature mismatch between CLI secret and dashboard endpoint secret | 14:00 | Loop `construct_event` over a list of secrets; stop running the CLI once the ngrok endpoint exists |
| 6 | SQLite "database is locked" under tick loop + worker + webhooks | 16:00 | WAL, `busy_timeout=5000`, one global write lock, and no HTTP call inside a transaction |
| 7 | Demo clock leaks wall time into deadline math | first dry run | A test that greps `app/` for `datetime.now`, `utcnow`, `time.time` outside `clock.py` and fails |
| 8 | DP nonsense at edges (σ tiny, M ≤ floor, non-monotone p*) | 15:00 | Clamp σ ≥ 0.08·M; if M ≤ 1.05·floor skip to escalate/instant; assert V non-decreasing in τ and p* non-increasing; fall back to linear markdown and log a Guard row |
| 9 | DoorDash JWT (raw vs base64url-decoded secret), 409 on reused ids, sandbox deliveries auto-cancel after an hour | 14:00 | Prove one quote+accept at 07:00; `external_delivery_id = item_id + ulid`; `demo/reset.py` cancels open deliveries |
| 10 | Time sinks: dashboard, Hypothesis shrinking, Claude rate limits, two people in one file | 15:00 | Dashboard capped at 90 min, server-rendered + SSE; Hypothesis 45 min with `max_examples=50`; Claude calls timeout → retry → template, concurrency 2; one owner per file, commit every 20 min |

Also: `.gitignore` in the first commit and a pre-commit grep for `sk_test|whsec_|sk-ant`.

### C. Revised plan, Eastern time, three people (★ before the official 12:30 window)
07:00 ★ the five de-risk items (ngrok reserved domain and all webhook URLs set once; iMessage round trip from all phones; `smoke_all.py` green including the DoorDash JWT; repo hygiene commit; beat sheet and recording setup frozen; decide the name) · 07:40 ★ walking skeleton together · **08:45 ★ S0: text in → tick → text out under the demo clock, one ledger row; red at 09:15 means everyone stays on it** · 09:15 ★ DP + frontier / attachments + vision + intent / eBay comps · 10:15 ★ policy / router / Stripe · 11:15 ★ guard + executor + scheduler / buyer agent + leak check / DoorDash quote → accept → simulator webhook · **12:15 ★ S1: photo from phone → comps → frontier card → LIVE; red means cut I11, mechanism routing, eBay Sell now** · 12:30 official start · 12:30 I12, I13, I14 / seller voice, escalation, cancel-before-payment / paid → courier → calendar chain · 13:30 twin + policies + run / full buyer thread / dashboard with Guard panel and REAL/TWIN badges (90 min cap) · 14:30 eval grid / copy polish / **calibration: 20 hand-collected sold prices, hard stop 15:15** · 15:30 dry run 1 · **16:00 backup take, unedited** · **16:30 P0 feature freeze**; property tests (45 min cap), chaos, brief · 17:15 rehearsal 2 · **17:45 code freeze, take 1** · 18:05 take 2 · 18:20 edit, brief final, tag · **18:45 submit** · 19:00 hard stop · 19:00 to 19:30 judging with the twelve-question crib open.

Hard cut rules: payments not green at 14:30 → buyer texts "paid", manual SOLD, disclosed on screen · courier 401 at 16:00 → calendar only · no eval table at 16:30 → golden tests plus the invariant table · nothing that is not on screen at 16:00 goes in the video.

First ten files, in order, so the first hour produces a walking skeleton: config, clock, db, models (minimal), ledger, engine/state + actions, engine/policy (returns a constant Reprice until 10:15), engine/executor, outbox/worker, main (with the BlueBubbles adapter). Green when a text from the seller's phone produces a ledger row and a reply, under the demo clock, with the process restarted mid-flight and nothing duplicated.

**Change → v7** (execution, not concept)
1. docs/07 to be replaced by the plan in C, in Eastern time, with S0 and S1 checkpoints and the backup take before freeze.
2. The ten mitigations in B become line items in docs/02 (db settings, clock test, DP clamps, Stripe secret list, external ids) and docs/08 (reserved ngrok domain, secret grep).
3. Demo numbers pre-filled from A; the instant quote is sourced and dated on screen.
4. A second metric from here on: **ship probability**, my estimate that the P0 spec is on screen by 16:00 ET. v6 without this plan: about 55%. v7: about 75%. The rubric score is unchanged; what changed is the chance of earning it.

**Scorecard v7**: rubric 8.6 (unchanged from v6); ship probability 55% → 75%.

**Next iteration**: a throwaway numeric check of the Bellman recursion and the twin in the scratchpad (not the repo) with the iPad numbers, to confirm the frontier card comes out sensible and the DP and Monte Carlo agree; then the results go in the log as the pre-computed demo numbers.

---

## Iteration 7 · 02:33 to 02:45 · The math, run for real (throwaway script in the scratchpad, not the repo)

Inputs: iPad Air 5 with M = $303, σ = $35, floor $220, instant S = $221, arrivals 2/day local and 4/day marketplace, fees per docs/03, buyers pay the list price when their willingness to pay covers it, unsold at the deadline takes the instant quote. Bellman recursion on a 15-minute grid over prices $220 to $394. Monte Carlo twin with 2,000 to 4,000 seeds per cell. Runtime under two seconds.

### What came out
**The price path is monotone and sane.** p* falls from $355 at 72h to $335 at 24h, $316 at 8h, $302 at 2h, $298 at 30 minutes; V(τ) falls from $304 toward the $221 instant quote. Opening price 1.17·M, inside the 1.3·M cap.

**The recursion and the twin agree.** V(T) = $280 / $304 / $319 at 24h / 72h / 168h; the twin's mean realized net under the same policy = $279 / $304 / $319. That agreement is the test the brief promised, and it holds before a line of product code exists.

**The frontier must use realized numbers, not the hold-price rule.** The docs/03 rule "largest price with P(sale by h) ≥ 0.85 if held" gives $319 / $346 / $362, which overstates what the seller gets because the optimal policy comes down as time passes. Realized under the policy: mean net given sold **$291 (84% sold) at 24h, $308 (96%) at 72h, $321 (99%) at 7 days**. The frontier card for the demo therefore reads:
```
your options
$221   guaranteed now        (BankMyCell best offer, 2026-09-13)
~$290  likely today          84% chance
~$305  likely by sunday      96% chance
~$320  likely within a week  99% chance
```

**Against an honest eBay Best Offer proxy** (list at M, accept any offer at or above 0.9·M at the buyer's price, auto-decline below): mean net including the instant fallback
| deadline | agent | Best Offer proxy | edge | agent sold | proxy sold |
|---|---|---|---|---|---|
| 12h | $263 | $264 | $-1 | 69% | 91% |
| 24h | $279 | $268 | +$11 | 83% | 99% |
| 72h | $304 | $269 | +$35 | 96% | 100% |
| 168h | $319 | $268 | +$51 | 98% | 100% |
Static list at M: $261 / $270 / $273 / $273. Linear markdown to the floor: $244 / $254 / $266 / $270. Oracle (sees every buyer): $295 / $315 / $338 / $353.

**The honest story, which differs from the pitch.** Static listings do sell; "static unsold at 24h" was wrong for any realistic parameters. The agent's gain comes from asking above market while there is time and coming down on evidence, so it grows with the horizon: nothing at 12 hours, $35 at three days, $51 at a week. At short deadlines its value is certainty, not price: it will take the instant quote rather than miss the deadline. With no instant option (S = 0) the engine prices down to $252 in the last half hour and sells 96 to 99%, so the seller's `instant_ok` constraint correctly reshapes the policy.

**Sensitivity (72h, policy solved with believed parameters, no online learning):** true value 10% below belief → agent $261 with 55% sold vs static $272; true value 10% above → agent $316 vs static $274; arrivals halved → $284 vs $272; arrivals up 50% → $310 vs $273; 15% payment failures → $300 vs $273. Floor breaches: zero in every cell, by construction. **Overestimating the item's value is the one failure that makes the agent worse than doing nothing clever**, which is exactly what I12 (pre-listing value sanity) and I13 (drift check) exist to catch. With online learning of arrivals, and an M update from scarce inquiries, the 0.9·M row improves; the brief should show both rows.

**Change → v8**
1. **Frontier definition** in docs/03: realized numbers from the recursion and the twin (mean net given sold, with the sale probability), not the 85% hold-price rule. The card shows the probability next to each price.
2. **Best Offer proxy baseline** defined as above in docs/05, replacing `static_90`.
3. **Claims in the video and brief** rewritten to the honest story: more money when there is time, certainty when there isn't, never below the floor, never past the deadline.
4. **M learning (P1, small):** treat standing offers as censored samples; after three or more offers, shift M toward the best offer / 0.95 and widen σ; the drift check triggers the same update when inquiries run far below prediction.
5. **Pre-registration.** The table above goes into the brief as expectations written before the build; Sunday's twin must reproduce it within Monte Carlo error. Few hackathon teams can say they pre-registered their evaluation.
6. **Demo numbers** for the frontier card, the reprice beat ($355 → $335 at 24h left, with the reason "no inquiries in 24h; arrival estimate down"), and the sold summary ("sold for $305, that's $84 more than the guaranteed offer").

**Scorecard v8**: rubric 8.6 → **8.7** (reliability 9.7 → 9.8 for pre-registration and a verified DP-twin agreement; demo clarity 9 → 9 with the card now carrying probabilities). Ship probability 75% (unchanged).

Script kept at the scratchpad path `engine_check.py` / `engine_check2.py` for reference; it is 120 lines of plain Python and can seed `engine/value_function.py` and `twin/world.py` on Sunday if the team wants, with the DT grid and clamps from the pre-mortem added.

**Next iteration**: re-run the adversarial panel on v8 to confirm the holes are closed and find the next weakest point; then start the morning briefing.

---

## Iteration 8 · 02:52 to 03:08 · The panel again, the twin gets a spine, and four twists

**Research** (Opus as the panel re-reading this file; Opus on originality twists; two more throwaway runs of the engine script)

### A. Panel re-run on v8
Earlier weaknesses: all three **partly closed**. Their evidence: I12's 25% tolerance barely covers the Air 4 / Air 5 gap and never says which denominator; the DP-twin agreement is "two implementations of one λ(p) agreeing with themselves"; P0 is still large and the file's own ship probability is 75%.

Next three weakest, in their words:
1. **Li:** "Your buyers arrive Poisson, pay list, and never counter. When your Monte Carlo agrees with your dynamic program to a dollar, what did the simulation tell you the recursion didn't?" Fix: give the twin's buyers counteroffers, ghosting, and payment failure, and report the DP-vs-twin **gap** as the number, not the match.
2. **Mundhra:** "Walk me through what was on disk at 9:30 Pacific." The Q&A crib's Q12 answer ("credentials only, no product code") contradicts the plan that starts code at 07:40 ET. Fix tonight: delete the sentence; say the true thing; confirm the rules at opening; show the commit log and the 9:30 to 16:00 diff.
3. **Ta:** "Waiting is worth money because buyers differ. You chose how much they differ. Show me the edge at σ = $20." Fix: estimate σ from the robust dispersion of the cleaned comps at intake, and add σ rows to the sensitivity sweep.

Below the line: eBay read-only looks thin in a multi-app agent hackathon (cheapest fix: create an unpublished draft offer with `autoDeclinePrice` = floor, so the agent operates eBay rather than reads it); say "Stripe test mode" before Tong does, and say what it doesn't prove (authorization, disputes, payouts); six beats in 120 seconds is too many, keep two catches on screen, narrate the decline as an injected fault because a test card that always declines is scripted; I11 belongs in an eval row, not a beat with two teammate phones; state the take rate and show the edge net of it; one sentence on strangers texting a single Apple ID.

Verdict: "a first-place build whose first place now turns on the twin's honesty rather than the engine's math: give the simulated buyers a spine and report what breaks, and it wins; leave them paying list price and it is an excellent second."

### B. Answered tonight with the script (spined twin: buyers counter at 85 to 100% of their value when the list is within 15%, the agent accepts any offer whose net beats the continuation value, otherwise counters at the smallest price that does, 30% ghost after a counter, payment fails 10% local / 3% marketplace)
| deadline | σ | DP V(T) | twin realized | gap | sold | static | Best Offer proxy | edge |
|---|---|---|---|---|---|---|---|---|
| 24h | 20 | $274 | $276 | +$2 | 97% | $270 | $262 | +$14 |
| 72h | 20 | $290 | $292 | +$2 | 100% | $272 | $262 | +$30 |
| 168h | 20 | $299 | $301 | +$2 | 100% | $272 | $262 | +$40 |
| 24h | 35 | $280 | $282 | +$2 | 95% | $270 | $263 | +$19 |
| 72h | 35 | $304 | $306 | +$2 | 100% | $272 | $264 | +$42 |
| 168h | 35 | $319 | $322 | +$2 | 100% | $272 | $263 | +$58 |
| 24h | 50 | $287 | $289 | +$2 | 94% | $270 | $264 | +$25 |
| 72h | 50 | $318 | $321 | +$3 | 99% | $272 | $265 | +$56 |
| 168h | 50 | $339 | $342 | +$2 | 100% | $272 | $265 | +$77 |
- The edge shrinks at σ = 20 but does not collapse: +$30 at three days. Ta's question has a number.
- σ mis-estimated by ±40% (policy solved at 35, world at 20 or 50): realized $296 / $311 vs $292 / $321 when solved correctly. Under $8 of proceeds. Robust.
- The gap is +$2 across the board because acceptance is governed by the continuation value: buyers who counter above V(τ) get taken, which the list-price twin could not do. Report the gap on Sunday whatever it is; a larger gap, shown, is more credible than a match.
- Net of a 5% take (Listx's rate): the edge at 24h is about +$5, at 72h about +$27, at 7 days about +$42. Honest line for the brief: at one day we roughly break even after our fee and the product is certainty; at three days and beyond it pays for itself.

### C. Originality twists (each under 45 minutes, LLM never near the money)
Adopted, in build order after S1 is green: **Where We Lose** (10 min: the one losing sensitivity cell printed on the dashboard with the detector that covers it) · **Sealed Envelope** (20 min: the pre-registered prediction table is hashed, the hash committed and shown at t=0, the table revealed at the end) · **Break Glass** (25 min: a strip of the host's seven failure classes as buttons on a parallel labeled item; click one, the injector fires, the Guard's red row names the class, the invariant, and the test file) · **Same Buyers, Three Sellers** (40 min, and it *is* the dashboard centerpiece within a 60-minute cap: one seeded buyer stream dispatched to agent, static, and oracle under common random numbers, three counters moving on the same events, all badged TWIN).
Parked as P1: **Ask Why** (re-solve at the historical state with one input reverted: "had two more buyers arrived I'd have held at $352") · **The Price of Time** (dV/dτ from the existing grid: "each extra day is worth $9.40 right now") · **Bring Your Own Quote** (I15: a seller-reported outside offer becomes salvage and a hard floor, badged UNVERIFIED).

**Change → v9**
1. Twin buyers with a spine (counter, ghost, payment failure) in `twin/world.py`; the brief reports the DP-vs-twin gap and the sold rate. Funded by cutting the dashboard cap from 90 to 60 minutes.
2. σ estimated at intake as 1.4826 × MAD of the cleaned comps, floored at 0.08·M; sensitivity rows for σ in the brief; the pre-registered table above replaces iteration 7's.
3. I12 tolerance tightened to **15% of the comps median** (denominator named). The Air 4 / Air 5 gap is 27 to 38%, so it fires with margin.
4. Q&A crib Q12 corrected: no claim about what code existed before 9:30 Pacific; confirm the rules at opening; keep the commit log honest and show the window diff.
5. eBay draft offer (unpublished) with `bestOfferTerms.autoDeclinePrice` = floor after S1 is green, so the agent writes to eBay, not only reads. Needs the sandbox user token; 25 to 40 minutes; drop at 14:30 if not green.
6. Video: two catches on screen (the I12 confirmation and the Guard rejecting a draft); courier status cut to 3 seconds; the decline narrated as an injected fault; "Stripe test mode" said first, with what it does not prove; identity resolution shown as an eval row.
7. Take rate stated (5%) and the edge shown net of it.
8. One sentence on the single Apple ID: a product would run one number per region behind a business messaging account; the Mac is the demo's bridge, not the architecture.

**Scorecard v9**
| Criterion | v8 | v9 | Why |
|---|---|---|---|
| Technical execution (30) | 8.5 | 8.7 | Twin with buyer behaviour, σ inferred not chosen, eBay written to, a common-random-numbers race on screen |
| Reliability & evaluation (25) | 9.8 | 9.8 | Gap reporting and the sealed envelope replace a match; already near the ceiling |
| Usefulness (20) | 8 | 8 | The take-rate honesty costs a little pitch and buys credibility |
| Originality (15) | 7.5 | 8.2 | Break Glass, the three-seller race, the sealed envelope, and "where we lose" are things this panel has not seen |
| Demo clarity (10) | 9 | 9 | Fewer beats, plainer words |
| **Weighted** | **8.7** | **8.8** | |
Ship probability: P0 unchanged at about 75%; the four twists are P0.5 and only start after S1 is green, so they cost the P0 nothing.

**Next iteration**: write the morning briefing as its own file (`docs/ideation/MORNING.md`): the final spec, the decisions only the team can make, the 07:00 checklist, the exact doc edits, the corrected Q&A crib, and the numbers. Then, if time remains before 06:00, the video script word for word and the brief draft.

---

## Iteration 9 · 03:14 to 03:24 · The morning briefing

No research this pass. Wrote `docs/ideation/MORNING.md`: the two-minute version, the four decisions only the team can make, the final idea, the frontier card with real numbers, the 120-second beat sheet, the 07:00 list, the Eastern-time schedule with checkpoints and cut rules, the exact edits per doc, the corrected twelve-question crib, the numbers and citations for the brief.

Also wrote `docs/ideation/preregistration.json` (the spined-twin expectations, the 72h price path, the frontier card, the sensitivity cells, zero expected violations) and its hash `efc88b944658fbcf09ba5b7a37d2272abf4d57315e2192de3ef2d26daa422b21` in `preregistration.sha256`. Committing those two files at 07:00 is the sealed envelope; that is the team's call, nothing is committed tonight.

No score change: v9 stands at 8.8.

**Next iterations** (in order, while the window lasts): the video script word for word with on-screen text; the brief draft in the host's vocabulary; the dashboard spec (what is on screen, where the Guard panel and the three-seller race sit); the twin spec (buyer behaviours, persona table, parameters file, common random numbers). Then a final adversarial check on the whole package before 06:00.

---

## Iteration 10 · 03:32 to 03:42 · The video, word for word

Wrote `docs/ideation/video-script.md`: eleven beats with time codes, what is on screen, the spoken narration (about 260 words, 140 to 150 wpm leaves 12 to 15 seconds of silence for the clock), the exact iMessage texts on both phones, operator cues for the demo clock and the courier simulator, a run sheet, and the cut order if the P0.5 twists are not built. The decline is narrated as an injected fault; "test mode" is said at beat 6; "audit" appears once at beat 10; the real-vs-twin line is the end card.

One consistency fix while writing it: the sold summary uses buyer A at $290 after the reroute, so the counterfactual line is "$69 more than the guaranteed offer" ($290 − $221), matching MORNING.md.

No score change: v9 stands at 8.8.

**Next iteration**: the brief draft in the host's vocabulary (`docs/ideation/brief-draft.md`), then the dashboard and twin specs.

---

## Iteration 11 · 03:49 to 03:58 · The brief, drafted

Wrote `docs/ideation/brief-draft.md` (about 1,100 words, two pages when set): what it does, why it is different with the honest edge, the system, the engine in five lines with citations, the failure matrix over the host's seven classes plus drift and crash with a test each, the twin section, identity resolution, the fourteen invariants, the evidence list with pre-registered numbers marked for replacement, the real / twin / modeled / decision-ready table, "where we lose", limitations, and how to run it.

No score change: v9 stands at 8.8.

**Next iteration**: the dashboard spec and the twin spec, then a final adversarial read of the whole package.

---

## Iteration 12 · 04:06 to 04:16 · Dashboard and twin specs

Wrote `docs/ideation/dashboard-spec.md` (layout sketch, seven panels in build order under a 60-minute cap, operator controls, endpoints, visual rules) and `docs/ideation/twin-spec.md` (world model with spined buyers and webhook realism, the five policies, common random numbers, the grid and its metrics, the intake Monte Carlo that renders the frontier, the parameters file, the thirty red-team personas, the calibration procedure, the sensitivity sweep, and the tests that gate trust in the grid).

No score change: v9 stands at 8.8.

**Next iteration**: a final adversarial read of the whole ideation package (MORNING, video script, brief, specs) by a fresh reviewer, looking for contradictions between files and anything a judge could catch. Then the loop winds down toward 06:00 with a closing summary.

---

## Iteration 13 · 04:23 to 05:00 · Consistency review and corrections

A fresh reviewer (Opus) read MORNING, the video script, the brief, both specs, the envelope, and iterations 7 to 12, and returned 44 fixes. The ones that mattered:
- **Rounding a judge could subtract.** The iteration 8 table's gaps and edges were computed from unrounded means (168h σ35: 322 − 319 reads as +3, shown +2; 322 − 263 reads as +59, shown +58). The envelope now carries a note, and every quoted edge is the envelope's.
- **Two world models in one envelope.** The frontier card's 84% / 96% came from the list-price twin (iteration 7) while the expectations came from the spined twin (iteration 8). Everything was recomputed from the spined twin with `engine_check5.py`: 72h-deadline card = 64% sold by 24h at about $311, 92% by 48h, 100% by 72h at $306; grid rows now include 12h (+$7, 85% sold); sensitivity at 72h: value −10% $284 vs $271, value +10% $314 vs $273, arrivals ×0.5 $295 vs $272, ×1.5 $309 vs $272, pay-fail 15% $306 vs $273, σ 20 $296 vs $272, σ 50 $311 vs $272. **With counteroffers no sensitivity cell loses**; the losing cell exists only in the list-price world. "Where we lose" now says exactly that.
- **New envelope hash** `874acade2334bbab93e67c54f3ca6bdc226628aab3c85bb697329abc705bb80c`; every reference updated. Committing the envelope at 07:00 is now mandatory because the video says it happened.
- **The video overran.** Beats 1, 10, 11 exceeded their windows at 150 wpm. Narration cut to 232 words (93 to 99 seconds), beat 11 is six words. The clock "skip" control replaces "three days in seventy seconds".
- **Policy consistency in the demo.** Buyer A's $280 is countered at $320 (the smallest price whose reliability-weighted net beats V(24h) = $280), A replies "290 is my max", B is accepted at $305, and after the injected decline A's standing $290 is accepted. No second checkout ever coexists with B's (I2). Sold for $290, $69 over the guaranteed $221.
- **Break Glass fires on the parallel item `demo-inject`**, never on the live item; the injected draft is narrated as injected.
- **Naming and paths**: Shippo → DoorDash in docs/00, 01, 05, 06; `sim/` → `twin/` also in docs/03 and docs/05; `static_90` is *replaced* by the Best Offer proxy, not relabeled; `twin/run.py` writes the reports; evals path unified; "instant ratio" vs "haircut" wording fixed; I11 is implemented and unit-tested, not an eval row (it is the first S1 cut).
- **Schedule**: `twin/intake.py` moved to 09:15 because S1 needs the card; sensitivity and the red team have slots; the eval-table decision moved to 15:45, before the backup take; the schedule is a table; headcount rule stated; decisions have defaults.
- **Honesty wording in the brief**: "measured" → "pre-registered expectation"; "Live run" → "Recorded run, demo mode".
Not changed on purpose: the iteration 8 table stays as printed by the script (history), with this note as the correction.

No rubric change: v9 stands at 8.8. Ship probability unchanged at about 75%.

**Next**: the loop winds down. One last pass at about 05:15 re-reads MORNING.md once more for stale statements, then a closing summary near 06:00 and stop.

---

## Closing · 05:51 EDT · loop stopped

Fifteen wakes between 00:02 and 05:51. Nothing was committed or pushed; `git status` shows `docs/ideation/` as untracked and the last commit is still the planning docs from Saturday night.

**What exists now, in `docs/ideation/`**
- `MORNING.md`: start here. Decisions with defaults, the final idea, the frontier card with real prices, the beat sheet, the 07:00 list, the Eastern-time schedule with checkpoints and cut rules, the exact edits per doc, the twelve-question crib, the numbers.
- `overnight-2026-09-13.md`: this trail, v1 (7.2) → v9 (8.8), with every source.
- `preregistration.json` + `preregistration.sha256`: the sealed envelope (`874acade…bb80c`), one world model for every number, to be committed at 07:00.
- `video-script.md`: eleven beats, 232 words of narration, both phones' texts, operator cues.
- `brief-draft.md`: the system and reliability brief in the host's vocabulary, numbers marked for replacement.
- `dashboard-spec.md`, `twin-spec.md`: what tracks C and A build, in order, under their caps.

**Where the idea landed.** Same product, sharper spine: a deadline-native selling agent in iMessage whose pricing engine is a finite-horizon dynamic program, whose evidence and pricing come from one marketplace twin with buyers who counter, ghost, and fail payment, whose Guard catches the failure classes the host company publishes, and whose numbers were pre-registered before a line of product code. Edge over an eBay Best Offer proxy in the twin: +$7 / +$19 / +$43 / +$59 at 12h / 1 / 3 / 7 days; certainty at short deadlines, money at long ones; never below the floor.

**Open only for the team**: the name (default: keep Liquid with a qualifier), the iPad in hand, the rules at opening.

**Not done, on purpose**: no edits to docs/00 to docs/09 (the edit list is in MORNING.md section 7); no product code; no commits. The four scratchpad scripts are session-local and disappear with the session; their logic is described in twin-spec.md and their numbers are in the envelope.
