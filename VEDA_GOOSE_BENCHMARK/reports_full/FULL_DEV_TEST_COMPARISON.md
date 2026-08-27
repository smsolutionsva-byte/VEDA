# VEDA Goose Experiment — Full DEV + Untouched TEST

## Dataset
- DEV: 116 resolver cases, 16 longitudinal streams, 12,940 activities, 10,056 relationships.
- TEST: 116 resolver cases, 16 longitudinal streams, 12,940 activities, 10,056 relationships.
- TEST schedule/cases used a different frozen seed and were not tuned after inspection.
- Backend: hash-ngram-v2. Real BGE-M3/reranker validation remains outstanding.

## Overall comparison
| Split | Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| DEV | Semantic-only | 40.0% | 55.6% | 60.0% | 84.4% | 0.5155 |
| DEV | VEDA engineering | 62.2% | 81.1% | 86.7% | 92.2% | 0.7224 |
| DEV | VEDA + WorkfrontRank | 62.2% | 86.7% | 90.0% | 94.4% | 0.7301 |
| TEST | Semantic-only | 44.4% | 54.4% | 60.0% | 83.3% | 0.5404 |
| TEST | VEDA engineering | 60.0% | 77.8% | 90.0% | 94.4% | 0.7116 |
| TEST | VEDA + WorkfrontRank | 61.1% | 84.4% | 90.0% | 95.6% | 0.7281 |

## Category Top-1 — DEV
| Category | Semantic | VEDA | + Workfront |
|---|---:|---:|---:|
| granularity | 0.0% | 20.0% | 0.0% |
| hard_negative | 100.0% | 100.0% | 100.0% |
| out_of_sequence | 0.0% | 0.0% | 0.0% |
| phase | 58.3% | 100.0% | 100.0% |
| temporal | 100.0% | 100.0% | 100.0% |
| wbs | 8.3% | 83.3% | 16.7% |
| workfront | 0.0% | 25.0% | 87.5% |

## Category Top-1 — TEST
| Category | Semantic | VEDA | + Workfront |
|---|---:|---:|---:|
| granularity | 20.0% | 20.0% | 0.0% |
| hard_negative | 100.0% | 100.0% | 100.0% |
| out_of_sequence | 8.3% | 8.3% | 0.0% |
| phase | 75.0% | 100.0% | 100.0% |
| temporal | 100.0% | 100.0% | 100.0% |
| wbs | 0.0% | 75.0% | 16.7% |
| workfront | 0.0% | 12.5% | 81.2% |

## Reality Graph
| Metric | DEV | TEST |
|---|---:|---:|
| Set/granularity/revision relation accuracy | 72.2% | 72.2% |
| Longitudinal stream accuracy | 100.0% | 100.0% |

## Interpretation
- WorkfrontRank strongly improves the workfront/missing-identity category: DEV 25.0% -> 87.5%, TEST 12.5% -> 81.25%.
- Overall Top-1 does not materially improve: DEV 62.2% -> 62.2%, TEST 60.0% -> 61.1%.
- R@3 improves materially: DEV 81.1% -> 86.7%, TEST 77.8% -> 84.4%.
- Current WorkfrontRank damages WBS disambiguation and granularity cases, and does not solve out-of-sequence identity cases.
- Therefore WorkfrontRank should be routed conditionally when semantic/entity identity is weak and execution-frontier evidence is discriminative, rather than applied as a universal prior.
- Reality Graph longitudinal handling is strong on this synthetic suite (16/16 DEV and TEST), while set/granularity/revision relation inference remains only 72.2% and needs work.

## Scientific caveats
- These results use the deterministic hash backend, not BGE-M3 or bge-reranker-v2-m3.
- The DEV suite is development data. TEST used a separate frozen seed and labels; the only post-freeze code change was an isolation-only benchmark harness fix so parallel shards used separate SQLite files. Resolver/reality logic and TEST labels were unchanged.
- Parallel sharding was used to finish TEST under execution time limits, so shard latency numbers should not be interpreted as production p50/p95.