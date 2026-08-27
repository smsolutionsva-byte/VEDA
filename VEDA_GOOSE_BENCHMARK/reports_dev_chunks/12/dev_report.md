# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **12**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **7.60s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 83.3% | 100.0% | 100.0% | 100.0% | 0.9167 |
| VEDA v0.2.1 engineering rank | 100.0% | 100.0% | 100.0% | 100.0% | 1.0000 |
| VEDA + WorkfrontRank | 91.7% | 100.0% | 100.0% | 100.0% | 0.9583 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| phase | 12 | 83.3% | 100.0% | 91.7% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **244.9 ms**
- One-pass p95: **1864.6 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| DEV-0023 | phase | 800070 | 2 | 1 | 2 | EXACT |