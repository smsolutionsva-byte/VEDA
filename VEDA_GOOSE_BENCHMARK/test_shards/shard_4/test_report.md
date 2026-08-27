# VEDA Reality Graph + WorkfrontRank — TEST benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **26.68s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 0.0% | 0.0% | 25.0% | 100.0% | 0.1617 |
| VEDA v0.2.1 engineering rank | 0.0% | 0.0% | 25.0% | 100.0% | 0.1677 |
| VEDA + WorkfrontRank | 0.0% | 0.0% | 0.0% | 25.0% | 0.0760 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| granularity | 4 | 0.0% | 0.0% | 0.0% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **80.0%** (20 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **523.6 ms**
- One-pass p95: **807.8 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| TEST-0081 | granularity | 900357 | 9 | 9 | 14 | NEW_SCOPE |
| TEST-0082 | granularity | 900358 | 7 | 7 | 13 | NEW_SCOPE |
| TEST-0083 | granularity | 900359 | 4 | 4 | 18 | NEW_SCOPE |
| TEST-0084 | granularity | 900360 | 7 | 6 | 10 | NEW_SCOPE |