# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **20.37s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 30.0% | 65.0% | 70.0% | 95.0% | 0.5094 |
| VEDA v0.2.1 engineering rank | 90.0% | 100.0% | 100.0% | 100.0% | 0.9333 |
| VEDA + WorkfrontRank | 50.0% | 90.0% | 100.0% | 100.0% | 0.6583 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| phase | 8 | 62.5% | 100.0% | 100.0% |
| wbs | 12 | 8.3% | 83.3% | 16.7% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **694.8 ms**
- One-pass p95: **7991.6 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| DEV-0001 | wbs | 800001 | 2 | 1 | 3 | AMBIGUOUS |
| DEV-0002 | wbs | 800006 | 9 | 1 | 3 | AMBIGUOUS |
| DEV-0004 | wbs | 800016 | 4 | 1 | 3 | AMBIGUOUS |
| DEV-0005 | wbs | 800017 | 7 | 1 | 4 | EXACT |
| DEV-0006 | wbs | 800022 | 7 | 1 | 1 | AMBIGUOUS |
| DEV-0007 | wbs | 800027 | 6 | 1 | 3 | AMBIGUOUS |
| DEV-0008 | wbs | 800032 | 8 | 3 | 3 | AMBIGUOUS |
| DEV-0009 | wbs | 800033 | 12 | 3 | 4 | EXACT |
| DEV-0010 | wbs | 800038 | 3 | 1 | 3 | EXACT |
| DEV-0011 | wbs | 800043 | 2 | 1 | 3 | AMBIGUOUS |
| DEV-0012 | wbs | 800048 | 3 | 1 | 3 | AMBIGUOUS |