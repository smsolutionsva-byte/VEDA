# VEDA Reality Graph + WorkfrontRank — TEST benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **23.66s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 65.0% | 70.0% | 70.0% | 95.0% | 0.7035 |
| VEDA v0.2.1 engineering rank | 65.0% | 95.0% | 100.0% | 100.0% | 0.8042 |
| VEDA + WorkfrontRank | 60.0% | 95.0% | 100.0% | 100.0% | 0.7792 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| out_of_sequence | 8 | 12.5% | 12.5% | 0.0% |
| temporal | 12 | 100.0% | 100.0% | 100.0% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **400.1 ms**
- One-pass p95: **653.9 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| TEST-0053 | out_of_sequence | 900226 | 1 | 1 | 2 | AMBIGUOUS |
| TEST-0054 | out_of_sequence | 900234 | 8 | 3 | 2 | EXACT |
| TEST-0055 | out_of_sequence | 900242 | 3 | 2 | 2 | EXACT |
| TEST-0056 | out_of_sequence | 900250 | 8 | 2 | 2 | EXACT |
| TEST-0057 | out_of_sequence | 900258 | 9 | 2 | 2 | EXACT |
| TEST-0058 | out_of_sequence | 900266 | 6 | 2 | 3 | EXACT |
| TEST-0059 | out_of_sequence | 900274 | 12 | 4 | 4 | EXACT |
| TEST-0060 | out_of_sequence | 900282 | 8 | 2 | 2 | EXACT |