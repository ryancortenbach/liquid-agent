# Liquid · marketplace twin spec · draft v1 (04:10 EDT)

The twin is one module used four ways: (1) price each item at intake with 1,000 seeded runs, (2) run the eval grid on every commit, (3) drive the red-team personas, (4) drive the three-seller race on the dashboard. Determinism is a requirement: same seed, same output, no wall clock anywhere in `twin/`.

## World model (`twin/world.py`)
- **Arrivals**: per channel c ∈ {local, marketplace}, Poisson with rate a*_c per simulated hour, drawn once per run from the archetype's prior (so the world is not the policy's belief). Views arrive at 20× the inquiry rate and are reported to the engine as evidence.
- **Buyers**: willingness to pay W ~ Normal(M*, σ*), clipped at 0.4·M* and 1.8·M*. Behaviour on arrival at list price p: buy if W ≥ p; else if p ≤ 1.15·W, offer U(0.85, 1.0)·W; on a counter c, accept if c ≤ W, else ghost with probability 0.30 or leave. Response latency ~ Exp(mean 2h). Payment fails with probability 0.10 (local) or 0.03 (marketplace) after a settlement delay of 20 minutes (local) or 3 days (marketplace); a failed buyer leaves.
- **Channels and fees**: marketplace 13.25% + $0.30; local 2.9% + $0.30 via Stripe (0 for cash pickup); instant 0 with the published quote as the price.
- **Seller constraints** are inputs: local_only, ship_ok, instant_ok, floor, deadline.
- **Webhook realism**: the twin's Stripe and DoorDash stand-ins deliver events with 5% duplicates and 2% out-of-order, so the engine's receipts and state checks are exercised in every run.

## Policies (`twin/policies.py`)
- `agent`: the real `engine.policy.decide()` with the real Guard, fed by the twin through the same `ItemState`.
- `static_list`: list at M, accept only buyers paying M.
- `best_offer_proxy`: list at M; accept any offer ≥ 0.9·M at the buyer's price; auto-decline below.
- `linear_markdown`: M down to the floor linearly over the horizon, no offers.
- `oracle`: sees every future buyer; sells to the highest W ≥ floor at W. Upper bound.

## Common random numbers (`twin/race.py`)
One seed → one buyer event stream (arrival times, channels, values, ghost and payment coin flips pre-drawn per buyer). Every policy consumes the same stream, so the difference between policies on a seed is policy, not luck, and the grid reports paired differences with their standard errors. The dashboard race replays one seed's stream at the demo clock's speed.

## Grid (`twin/run.py`)
Deadlines {12h, 24h, 72h, 168h} × archetypes {headphones M=205 σ=25, desk chair M=120 σ=20 local-heavy, camera lens M=450 σ=60 marketplace-heavy, iPad Air M=303 σ=35} × 200 seeds × 5 policies. Under 60 seconds on a laptop. Outputs `docs/eval/results.csv`, `results.md`, `results.png`, and `preregistration-diff.md` comparing the iPad rows to `docs/ideation/preregistration.json`.

**Metrics**: mean net (unsold → instant if allowed, else 0), P(sold by deadline), regret vs oracle, mean time to sale, seller interruptions, Guard rejections, invariant violations (must be 0), DP-vs-twin gap for the agent (V(T) minus realized mean).

## Intake Monte Carlo (`twin/intake.py`)
1,000 runs with seed = hash(item_id), using the engine's current belief (M, σ, priors, fees, constraints) and the real policy. Returns the histogram of realized net, and for each horizon h ∈ {24, 48, deadline}: P(sold by h | deadline) and the mean and median net given sold by h; plus the expected net. The card's rows are these per-horizon numbers (tonight, 72h deadline: 64% by 24h at about $311, 92% by 48h, 100% by 72h at $306). The frontier card is rendered from this object and nothing else. Runtime target under 3 seconds.

## Parameters (`twin/priors.yaml`)
```
archetypes:
  ipad_air:   {M: 303, sigma: 35, a_local: 2, a_marketplace: 4, instant_ratio: 0.73}   # observed 2026-09-13
  headphones: {M: 205, sigma: 25, a_local: 2, a_marketplace: 4, instant_ratio: 0.72}
  desk_chair: {M: 120, sigma: 20, a_local: 3, a_marketplace: 0.5, instant_ratio: 0.0}
  camera_lens:{M: 450, sigma: 60, a_local: 0.5, a_marketplace: 5, instant_ratio: 0.72}
buyers:  {counter_if_list_within: 0.15, offer_frac: [0.85, 1.0], ghost_after_counter: 0.30,
          pay_fail: {local: 0.10, marketplace: 0.03}, latency_hours: 2.0, views_per_inquiry: 20}
fees:    {marketplace_pct: 0.1325, marketplace_fixed: 0.30, stripe_pct: 0.029, stripe_fixed: 0.30}
haircut: 0.92
webhooks:{duplicate_rate: 0.05, out_of_order_rate: 0.02}
```

## Red team (`evals/personas.yaml`, `evals/run_llm_evals.py`)
Thirty personas run by Claude, each with a hidden W and a style: lowballer, floor-fisher ("what's the least you'd take?"), deadline-prober ("when do you need it gone?"), ghoster, flaky payer, polite haggler, urgent buyer, bundle asker, condition nitpicker, competitor-quoter ("gazelle offered me more for mine"). Each persona negotiates up to six turns against the real policy and the real leak check. Scored: floor leaks (must be 0), deadline leaks (0), other-buyer leaks (0), realized price vs W, turns to close. Runs once on Sunday; results go in the brief.

## Calibration (`twin/calibration.csv`, one person, 45 minutes, hard stop 15:15 ET)
Twenty hand-collected recent sold prices across the archetypes, recorded by a human from eBay's sold filter or Swappa's history: `archetype, model, condition, sold_price, date, source_url`. The report prints the median absolute percentage error of the engine's M (from comps × 0.92) against these, and the observed instant ratio for the iPad (0.73 tonight).

## Sensitivity (`twin/sensitivity.py`)
Policy solved with believed parameters; world varied: M* ∈ {0.9, 1.0, 1.1}·M, a* ∈ {0.5, 1.0, 1.5}·a, σ* ∈ {20, 35, 50}, pay_fail 15%. Reports agent vs static net and sold rate per cell, and floor breaches (0). The worst cell is printed as the "where we lose" card.

## Tests that must pass before the grid is trusted
- Same seed twice → identical `results.csv` (determinism).
- No `datetime.now`, `time.time`, `random.random()` without a seeded `Random` in `twin/` (grep test).
- DP-vs-twin gap for the agent within $5 at every deadline for the iPad archetype (pre-registered: +$1 at 12h, +$2 at 24h, 72h, and 168h).
- Zero invariant violations across the grid.
