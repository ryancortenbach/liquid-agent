# Liquid

**Take a picture. Set a deadline. We'll get it sold.**

Entry for the [Multi-App AI Agent Hackathon](https://multiappagenthackathon.com) · Sunday, September 13, 2026.

Liquid is a deadline-native selling agent that lives in your iMessages. You text it a photo and a deadline. It identifies the item, works out how much cash it can reliably become and how fast, lists it, reprices, negotiates with buyers, routes to the best executable exit before your deadline, takes payment, buys the shipping label, and puts the drop-off on your calendar. It texts you only when it needs a decision.

> Normal marketplaces optimize listings. Liquid optimizes liquidation.

## External apps
iMessage (via BlueBubbles on a Mac) · eBay · Stripe · Shippo · Google Calendar · Claude (vision, intent, language)

## Docs
| File | What it defines |
|---|---|
| [docs/00-brief.md](docs/00-brief.md) | The hackathon brief, rubric, submission list, and how we score each line |
| [docs/01-product.md](docs/01-product.md) | Product spec: thesis, the core loop, every feature by priority, conversation design, promises |
| [docs/02-architecture.md](docs/02-architecture.md) | System design, repo skeleton, data model, state machine, clock, config, dependencies |
| [docs/03-engine.md](docs/03-engine.md) | The liquidation engine: demand model, objective, frontier, offer logic, reprice rules, pseudocode |
| [docs/04-integrations.md](docs/04-integrations.md) | Each external app: endpoints, auth, payloads, gotchas, fallbacks |
| [docs/05-reliability.md](docs/05-reliability.md) | Invariants, guard layer, idempotency, eval harness, tests, chaos, what is real vs modeled |
| [docs/06-demo.md](docs/06-demo.md) | The two-minute demo script, time compression, screen layout, fallback plan |
| [docs/07-schedule.md](docs/07-schedule.md) | Hour-by-hour build plan with parallel tracks and cut lines |
| [docs/08-setup.md](docs/08-setup.md) | Tonight's checklist: accounts, keys, Mac permissions, smoke tests |
| [docs/09-brief-template.md](docs/09-brief-template.md) | Skeleton of the "system and reliability brief" we submit |

Status: planning complete 2026-09-12. Code starts 2026-09-13.
