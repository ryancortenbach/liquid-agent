# Evaluation results

Seeded simulation with 12,000 policy runs.

| Deadline | agent | static_list | static_90 | linear_markdown | oracle | Agent market sale | Agent exit | Violations |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 12h | $211 | $133 | $153 | $155 | $230 | 70% | 100% | 0 |
| 24h | $224 | $190 | $193 | $197 | $251 | 90% | 100% | 0 |
| 72h | $242 | $223 | $201 | $215 | $275 | 96% | 100% | 0 |
| 168h | $257 | $223 | $200 | $219 | $289 | 99% | 100% | 0 |

The oracle sees every future executable buyer and represents an upper bound. Agent exit rate includes the modeled instant exit at the deadline. Agent market sale rate excludes it. Baselines report zero for unsold inventory. This first harness models prices, Poisson arrivals, willingness to pay, offers, payment reliability, ghosting, and fees. Response latency and delayed settlement are not modeled yet.
