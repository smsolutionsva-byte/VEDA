# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **1**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **9.52s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 0.0% | 0.0% | 100.0% | 100.0% | 0.2500 |
| VEDA v0.2.1 engineering rank | 0.0% | 0.0% | 100.0% | 100.0% | 0.2500 |
| VEDA + WorkfrontRank | 0.0% | 0.0% | 100.0% | 100.0% | 0.2500 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| wbs | 1 | 0.0% | 0.0% | 0.0% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **0.0%** (0 cases)
- Longitudinal event-stream accuracy: **31.2%** (16 streams)

## Latency
- Base retrieval median: **3220.1 ms**
- Base retrieval p95: **3220.1 ms**
- WorkfrontRank incremental median: **15.7 ms**
- WorkfrontRank incremental p95: **15.7 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| DEV-0001 | wbs | 800001 | 4 | 4 | 4 | AMBIGUOUS |

### Reality-stream failures
- dev-replacement-0: corroboration
- dev-replacement-1: corroboration
- dev-replacement-2: corroboration
- dev-replacement-3: corroboration
- dev-replacement-4: corroboration
- dev-replacement-5: corroboration
- dev-contradict-0: contradiction
- dev-contradict-1: contradiction
- dev-contradict-2: contradiction
- dev-contradict-3: contradiction
- dev-contradict-4: contradiction