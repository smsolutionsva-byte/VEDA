# VEDA Reality Graph + WorkfrontRank — TEST benchmark

- Activities: **12,940**
- Resolver cases: **20**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **20.78s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 20.0% | 30.0% | 50.0% | 80.0% | 0.3342 |
| VEDA v0.2.1 engineering rank | 20.0% | 50.0% | 100.0% | 100.0% | 0.4483 |
| VEDA + WorkfrontRank | 0.0% | 30.0% | 50.0% | 90.0% | 0.2189 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| granularity | 6 | 33.3% | 33.3% | 0.0% |
| out_of_sequence | 4 | 0.0% | 0.0% | 0.0% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **62.5%** (16 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **571.2 ms**
- One-pass p95: **1017.7 ms**

## First failures
| ID | Category | Expected | Semantic | VEDA | Workfront | Relation |
|---|---|---:|---:|---:|---:|---|
| TEST-0061 | out_of_sequence | 900290 | 8 | 2 | 3 | EXACT |
| TEST-0062 | out_of_sequence | 900298 | 11 | 4 | 5 | EXACT |
| TEST-0063 | out_of_sequence | 900306 | 12 | 5 | 4 | EXACT |
| TEST-0064 | out_of_sequence | 900314 | 6 | 2 | 2 | EXACT |
| TEST-0075 | granularity | 900351 | 1 | 1 | 9 | NEW_SCOPE |
| TEST-0076 | granularity | 900352 | 3 | 3 | 9 | NEW_SCOPE |
| TEST-0077 | granularity | 900353 | 5 | 4 | 12 | NEW_SCOPE |
| TEST-0078 | granularity | 900354 | 1 | 1 | 3 | NEW_SCOPE |
| TEST-0079 | granularity | 900355 | 5 | 5 | 10 | NEW_SCOPE |
| TEST-0080 | granularity | 900356 | 7 | 4 | 6 | NEW_SCOPE |