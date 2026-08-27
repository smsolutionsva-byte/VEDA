# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **23.70s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 60.0% | 60.0% | 70.0% | 95.0% | 0.6598 |
| VEDA v0.2.1 engineering rank | 60.0% | 95.0% | 95.0% | 100.0% | 0.7750 |
| VEDA + WorkfrontRank | 60.0% | 95.0% | 95.0% | 100.0% | 0.7333 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| out_of_sequence | 8 | 0.0% | 0.0% | 0.0% |
| temporal | 12 | 100.0% | 100.0% | 100.0% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **427.3 ms**
- One-pass p95: **882.2 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| DEV-0053 | out_of_sequence | 800226 | 5 | 2 | 2 | EXACT |
| DEV-0054 | out_of_sequence | 800234 | 8 | 2 | 3 | EXACT |
| DEV-0055 | out_of_sequence | 800242 | 6 | 3 | 3 | EXACT |
| DEV-0056 | out_of_sequence | 800250 | 6 | 2 | 3 | EXACT |
| DEV-0057 | out_of_sequence | 800258 | 10 | 2 | 3 | EXACT |
| DEV-0058 | out_of_sequence | 800266 | 9 | 2 | 3 | EXACT |
| DEV-0059 | out_of_sequence | 800274 | 13 | 6 | 6 | EXACT |
| DEV-0060 | out_of_sequence | 800282 | 4 | 2 | 3 | EXACT |