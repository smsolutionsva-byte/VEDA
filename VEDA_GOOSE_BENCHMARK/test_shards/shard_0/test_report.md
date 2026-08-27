# VEDA Reality Graph + WorkfrontRank — TEST benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **13.92s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 30.0% | 55.0% | 65.0% | 95.0% | 0.4973 |
| VEDA v0.2.1 engineering rank | 85.0% | 100.0% | 100.0% | 100.0% | 0.9167 |
| VEDA + WorkfrontRank | 50.0% | 90.0% | 100.0% | 100.0% | 0.6558 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| phase | 8 | 75.0% | 100.0% | 100.0% |
| wbs | 12 | 0.0% | 75.0% | 16.7% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **534.7 ms**
- One-pass p95: **2027.8 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| TEST-0001 | wbs | 900001 | 2 | 1 | 3 | AMBIGUOUS |
| TEST-0002 | wbs | 900006 | 9 | 2 | 3 | AMBIGUOUS |
| TEST-0003 | wbs | 900011 | 2 | 1 | 1 | AMBIGUOUS |
| TEST-0004 | wbs | 900016 | 7 | 1 | 3 | AMBIGUOUS |
| TEST-0005 | wbs | 900017 | 4 | 1 | 4 | EXACT |
| TEST-0006 | wbs | 900022 | 6 | 1 | 1 | AMBIGUOUS |
| TEST-0007 | wbs | 900027 | 6 | 1 | 3 | AMBIGUOUS |
| TEST-0008 | wbs | 900032 | 8 | 3 | 3 | AMBIGUOUS |
| TEST-0009 | wbs | 900033 | 11 | 2 | 5 | EXACT |
| TEST-0010 | wbs | 900038 | 7 | 1 | 3 | EXACT |
| TEST-0011 | wbs | 900043 | 4 | 1 | 3 | AMBIGUOUS |
| TEST-0012 | wbs | 900048 | 2 | 1 | 3 | AMBIGUOUS |