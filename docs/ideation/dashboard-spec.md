# Liquid · dashboard spec · draft v1 (04:08 EDT)

Purpose: the judges' second screen during the video and the operator's control surface during takes. Server-rendered Jinja + SSE (`sse-starlette`) + vanilla JS. No framework. Hard cap 60 minutes of build; the panel order below is the build order, stop when the cap hits.

## Layout (right two thirds of a 1920×1080 recording, about 1280×1080)
```
┌──────────────────────────────────────────────────────────────────────┐
│ ITEM  photo · iPad Air 5 (M1, 64GB) · cond B · M $303 σ $35 · floor  │
│ $220 · deadline SUN 18:00 · ⏱ 23h 40m left (sim, 1h/s) ▶ ⏸ ⏭skip ↺       │
│ mode DEMO · envelope 874acade… · channels: iMsg 3s ago · Stripe ok · │
│ DoorDash ok · Calendar ok · Claude ok                                 │
├───────────────────────────┬──────────────────────────────────────────┤
│ FRONTIER                  │ LEDGER (live)                            │
│ $221 now · ~$290 today    │ 23:40  TICK   reprice 355→335            │
│ (84%) · ~$305 by sun (96%)│        a_local 2.0→1.1/d · 0 inquiries   │
│ [histogram: 1,000 runs]   │        in 48h · V(24h)=$280   [TWIN]     │
│ list $335 · P(sold) 96%   │ 23:20  INBOUND buyer A "would you do 280"│
│                           │        → offer $280  [REAL]              │
├───────────────────────────┤ 23:20  COUNTER $320 · EV_acc 272 < V 280 │
│ GUARD                     │ (rejected drafts appear in the GUARD     │
│ accepted 41 · rejected 2  │  panel on item demo-inject, never here)  │
│ drift: none               │ ...                                      │
│ last: I1 floor · I12 ask  ├──────────────────────────────────────────┤
│ [break glass: 7 buttons]  │ BUYERS (identity-resolved)               │
├───────────────────────────┤ A  +1415… · a@x.com · cus_…  offer $280  │
│ SAME BUYERS, 3 SELLERS    │    r=0.90 · counter $320                 │
│ agent $306 · static $272  │ B  +1650… · none     accepted $305 ·     │
│ · oracle ⟦grid⟧ means/200│    pay FAILED · dropped                   │
│ [TWIN]                    ├──────────────────────────────────────────┤
│                           │ MONEY & LOGISTICS                        │
│                           │ Stripe cs_… OPEN 12:40 left → PAID       │
│                           │ DoorDash D-… created → picked_up → …     │
│                           │ Calendar: "pickup: ipad air" sun 16:10   │
└───────────────────────────┴──────────────────────────────────────────┘
```

## Panels, in build order
1. **Ledger stream** (15 min). One row per `LedgerEvent` over SSE: sim time, kind, action, the three inputs that mattered, the reason, a badge. Badges: REAL (green), TWIN (grey). Rejected Guard rows in red. Injected faults live on the parallel item `demo-inject` and show only in the Guard panel, badged INJECTED (amber). Newest at top, 40 rows visible.
2. **Guard panel** (10 min). Counters of accepted and rejected actions; the last three rejections with the invariant id; a MODEL_DRIFT indicator that turns red when I13 fires. The Break Glass strip: seven buttons named with Lemma's classes, each calling `POST /inject/{class}` on the parallel item `demo-inject`; the resulting Guard row names the class, the invariant, and the test file.
3. **Item header** (5 min). Photo thumbnail, identity, condition, M and σ, floor, deadline, the simulated countdown, mode, the envelope hash, channel health ("last inbound Ns ago" per channel, webhook registrations green/red).
4. **Frontier** (10 min). The card as texted, the histogram of the intake Monte Carlo (1,000 runs; bins of $10; the current list price as a vertical line), P(sold by deadline) at the current price.
5. **Same buyers, three sellers** (10 min inside the cap, the rest lives in `twin/race.py`). Three counters and a seed; they advance as the shared event stream is replayed at the demo clock's speed; all TWIN.
6. **Buyers** (5 min). Identity-resolved buyers with their linked identifiers, status, last offer, reliability.
7. **Money and logistics** (5 min). Stripe session state with the window countdown; DoorDash status timeline; calendar event.

## Operator controls
Clock ▶ ⏸, speed (1×, 60×, 3600×), and "skip to" a sim time (used at video beat 4); `↺ reset` calls `demo/reset.py`; `run twin` triggers the intake Monte Carlo again; the Break Glass buttons. All controls are behind `?op=1` so the recorded view can hide them.

## Endpoints
`GET /dashboard/{item_id}` · `GET /dashboard/{item_id}/events` (SSE) · `POST /clock/{pause|resume|speed|skip}` · `POST /inject/{class}` · `POST /demo/reset`

## Visual rules
One accent colour for interactive elements; red only for Guard rejections and drift; amber only for INJECTED; tabular numerals everywhere; no charts library, the histogram is 30 divs with heights. The dashboard must read at 50% scale in the video: 16px body, 22px numbers in the frontier and race panels.
