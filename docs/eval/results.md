# Evaluation results

Seeded simulation with 12,000 policy runs.

| Deadline | agent | static_list | static_90 | linear_markdown | oracle | Agent market sale | Agent exit | Violations |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 12h | $212 | $134 | $155 | $156 | $232 | 70% | 100% | 0 |
| 24h | $226 | $191 | $195 | $199 | $254 | 89% | 100% | 0 |
| 72h | $245 | $225 | $203 | $217 | $280 | 97% | 100% | 0 |
| 168h | $260 | $225 | $202 | $221 | $296 | 99% | 100% | 0 |

The oracle sees every future executable buyer and represents an upper bound. Agent exit rate includes the modeled instant exit at the deadline. Agent market sale rate excludes it. Baselines report zero for unsold inventory. This first harness models prices, Poisson arrivals, willingness to pay, offers, close reliability, ghosting, and fees. Response latency and delayed settlement are not modeled yet.
