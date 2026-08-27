# VEDA Reality Graph + WorkfrontRank — TEST benchmark

- Activities: **12,940**
- Resolver cases: **16**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **23.55s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 100.0% | 100.0% | 100.0% | 100.0% | 1.0000 |
| VEDA v0.2.1 engineering rank | 100.0% | 100.0% | 100.0% | 100.0% | 1.0000 |
| VEDA + WorkfrontRank | 100.0% | 100.0% | 100.0% | 100.0% | 1.0000 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| hard_negative | 16 | 100.0% | 100.0% | 100.0% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **477.6 ms**
- One-pass p95: **7713.0 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|