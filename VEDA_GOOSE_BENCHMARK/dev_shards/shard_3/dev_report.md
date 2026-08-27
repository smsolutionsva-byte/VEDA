# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **26.68s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 0.0% | 30.0% | 40.0% | 90.0% | 0.2202 |
| VEDA v0.2.1 engineering rank | 20.0% | 70.0% | 90.0% | 100.0% | 0.4476 |
| VEDA + WorkfrontRank | 0.0% | 50.0% | 60.0% | 80.0% | 0.2603 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| granularity | 6 | 0.0% | 33.3% | 0.0% |
| out_of_sequence | 4 | 0.0% | 0.0% | 0.0% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **62.5%** (16 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **423.8 ms**
- One-pass p95: **908.1 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| DEV-0061 | out_of_sequence | 800290 | 7 | 3 | 3 | EXACT |
| DEV-0062 | out_of_sequence | 800298 | 12 | 4 | 2 | EXACT |
| DEV-0063 | out_of_sequence | 800306 | 8 | 2 | 2 | EXACT |
| DEV-0064 | out_of_sequence | 800314 | 7 | 3 | 3 | EXACT |
| DEV-0075 | granularity | 800351 | 2 | 1 | 8 | NEW_SCOPE |
| DEV-0076 | granularity | 800352 | 4 | 3 | 9 | NEW_SCOPE |
| DEV-0077 | granularity | 800353 | 6 | 4 | 12 | NEW_SCOPE |
| DEV-0078 | granularity | 800354 | 3 | 1 | 3 | NEW_SCOPE |
| DEV-0079 | granularity | 800355 | 8 | 7 | 12 | NEW_SCOPE |
| DEV-0080 | granularity | 800356 | 3 | 3 | 5 | NEW_SCOPE |