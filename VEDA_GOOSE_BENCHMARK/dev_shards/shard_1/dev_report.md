# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **19.82s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 10.0% | 25.0% | 25.0% | 45.0% | 0.2040 |
| VEDA v0.2.1 engineering rank | 40.0% | 50.0% | 60.0% | 65.0% | 0.4725 |
| VEDA + WorkfrontRank | 90.0% | 100.0% | 100.0% | 100.0% | 0.9500 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| phase | 4 | 50.0% | 100.0% | 100.0% |
| workfront | 16 | 0.0% | 25.0% | 87.5% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **554.0 ms**
- One-pass p95: **8809.6 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| DEV-0025 | workfront | 800074 | 9 | 4 | 1 | AMBIGUOUS |
| DEV-0028 | workfront | 800098 | None | None | 1 | AMBIGUOUS |
| DEV-0031 | workfront | 800122 | 21 | 5 | 2 | EXACT |
| DEV-0034 | workfront | 800146 | 10 | 1 | 1 | AMBIGUOUS |
| DEV-0035 | workfront | 800154 | 11 | 1 | 1 | AMBIGUOUS |
| DEV-0036 | workfront | 800162 | 13 | 3 | 1 | AMBIGUOUS |
| DEV-0037 | workfront | 800170 | 7 | 2 | 2 | AMBIGUOUS |
| DEV-0039 | workfront | 800186 | 10 | 6 | 1 | AMBIGUOUS |