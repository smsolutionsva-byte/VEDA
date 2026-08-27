# VEDA Reality Graph + WorkfrontRank — UNTOUCHED TEST (merged frozen shards)

- Activities: **12,940**
- Resolver cases: **116 / 116**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Resolver/reality code and TEST labels were frozen before execution.
- Benchmark harness received one isolation-only fix (per-shard temp SQLite); resolver logic and labels were unchanged.

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 44.4% | 54.4% | 60.0% | 83.3% | 0.5404 |
| VEDA engineering rank | 60.0% | 77.8% | 90.0% | 94.4% | 0.7116 |
| VEDA + WorkfrontRank | 61.1% | 84.4% | 90.0% | 95.6% | 0.7281 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| granularity | 10 | 20.0% | 20.0% | 0.0% |
| hard_negative | 16 | 100.0% | 100.0% | 100.0% |
| out_of_sequence | 12 | 8.3% | 8.3% | 0.0% |
| phase | 12 | 75.0% | 100.0% | 100.0% |
| temporal | 12 | 100.0% | 100.0% | 100.0% |
| wbs | 12 | 0.0% | 75.0% | 16.7% |
| workfront | 16 | 0.0% | 12.5% | 81.2% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **72.2%** (36 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Execution note
Accuracy is exact over all 116 TEST cases. Latency is intentionally not aggregated as a single p50/p95 because the timeout-safe test was executed in six parallel isolated shards.

## First failures
| ID | Category | Expected | Semantic rank | VEDA rank | Workfront rank | Relation |
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
| TEST-0053 | out_of_sequence | 900226 | 1 | 1 | 2 | AMBIGUOUS |
| TEST-0054 | out_of_sequence | 900234 | 8 | 3 | 2 | EXACT |
| TEST-0055 | out_of_sequence | 900242 | 3 | 2 | 2 | EXACT |
| TEST-0056 | out_of_sequence | 900250 | 8 | 2 | 2 | EXACT |
| TEST-0057 | out_of_sequence | 900258 | 9 | 2 | 2 | EXACT |
| TEST-0058 | out_of_sequence | 900266 | 6 | 2 | 3 | EXACT |
| TEST-0059 | out_of_sequence | 900274 | 12 | 4 | 4 | EXACT |
| TEST-0060 | out_of_sequence | 900282 | 8 | 2 | 2 | EXACT |
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
| TEST-0081 | granularity | 900357 | 9 | 9 | 14 | NEW_SCOPE |
| TEST-0082 | granularity | 900358 | 7 | 7 | 13 | NEW_SCOPE |
| TEST-0083 | granularity | 900359 | 4 | 4 | 18 | NEW_SCOPE |
| TEST-0084 | granularity | 900360 | 7 | 6 | 10 | NEW_SCOPE |