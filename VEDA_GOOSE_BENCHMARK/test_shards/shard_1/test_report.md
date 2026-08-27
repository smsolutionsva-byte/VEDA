# VEDA Reality Graph + WorkfrontRank — TEST benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **20.63s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 15.0% | 25.0% | 25.0% | 45.0% | 0.2318 |
| VEDA v0.2.1 engineering rank | 30.0% | 50.0% | 70.0% | 75.0% | 0.4237 |
| VEDA + WorkfrontRank | 85.0% | 100.0% | 100.0% | 100.0% | 0.9167 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| phase | 4 | 75.0% | 100.0% | 100.0% |
| workfront | 16 | 0.0% | 12.5% | 81.2% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **783.7 ms**
- One-pass p95: **1685.2 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| TEST-0025 | workfront | 900074 | 14 | 8 | 1 | AMBIGUOUS |
| TEST-0026 | workfront | 900082 | 17 | 3 | 2 | AMBIGUOUS |
| TEST-0029 | workfront | 900106 | 24 | 5 | 1 | AMBIGUOUS |
| TEST-0030 | workfront | 900114 | 20 | 3 | 2 | EXACT |
| TEST-0032 | workfront | 900130 | None | None | 1 | AMBIGUOUS |
| TEST-0035 | workfront | 900154 | 10 | 3 | 1 | AMBIGUOUS |
| TEST-0036 | workfront | 900162 | 8 | 1 | 1 | AMBIGUOUS |
| TEST-0037 | workfront | 900170 | 9 | 5 | 1 | AMBIGUOUS |
| TEST-0038 | workfront | 900178 | 12 | 5 | 3 | AMBIGUOUS |
| TEST-0039 | workfront | 900186 | 9 | 4 | 1 | AMBIGUOUS |
| TEST-0040 | workfront | 900194 | 20 | 2 | 1 | AMBIGUOUS |