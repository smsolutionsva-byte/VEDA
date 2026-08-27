# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **23.34s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 0.0% | 25.0% | 25.0% | 100.0% | 0.1812 |
| VEDA v0.2.1 engineering rank | 0.0% | 25.0% | 50.0% | 100.0% | 0.2313 |
| VEDA + WorkfrontRank | 0.0% | 0.0% | 0.0% | 25.0% | 0.0683 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| granularity | 4 | 0.0% | 0.0% | 0.0% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **80.0%** (20 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **673.4 ms**
- One-pass p95: **802.3 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| DEV-0081 | granularity | 800357 | 6 | 5 | 7 | NEW_SCOPE |
| DEV-0082 | granularity | 800358 | 8 | 8 | 14 | NEW_SCOPE |
| DEV-0083 | granularity | 800359 | 10 | 10 | None | NEW_SCOPE |
| DEV-0084 | granularity | 800360 | 3 | 2 | 17 | NEW_SCOPE |