# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **12**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **7.28s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 16.7% | 33.3% | 58.3% | 83.3% | 0.3502 |
| VEDA v0.2.1 engineering rank | 58.3% | 91.7% | 100.0% | 100.0% | 0.7708 |
| VEDA + WorkfrontRank | 16.7% | 83.3% | 91.7% | 100.0% | 0.4236 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| wbs | 12 | 16.7% | 58.3% | 16.7% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **367.7 ms**
- One-pass p95: **1661.2 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| DEV-0001 | wbs | 800001 | 2 | 1 | 3 | AMBIGUOUS |
| DEV-0002 | wbs | 800006 | 6 | 2 | 3 | AMBIGUOUS |
| DEV-0003 | wbs | 800011 | 4 | 1 | 1 | AMBIGUOUS |
| DEV-0004 | wbs | 800016 | 12 | 4 | 3 | AMBIGUOUS |
| DEV-0005 | wbs | 800017 | 12 | 2 | 6 | EXACT |
| DEV-0007 | wbs | 800027 | 3 | 1 | 3 | AMBIGUOUS |
| DEV-0008 | wbs | 800032 | 4 | 1 | 3 | AMBIGUOUS |
| DEV-0009 | wbs | 800033 | 7 | 2 | 4 | EXACT |
| DEV-0010 | wbs | 800038 | 7 | 2 | 3 | EXACT |
| DEV-0011 | wbs | 800043 | 1 | 1 | 3 | AMBIGUOUS |
| DEV-0012 | wbs | 800048 | 4 | 1 | 3 | AMBIGUOUS |