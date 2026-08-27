# VEDA Reality Graph + WorkfrontRank — DEV benchmark

- Activities: **12,940**
- Resolver cases: **116**
- Reality streams: **16**
- Backend: **hash-ngram-v2**
- Index time: **8.19s**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 40.0% | 55.6% | 60.0% | 84.4% | 0.5155 |
| VEDA v0.2.1 engineering rank | 62.2% | 81.1% | 86.7% | 92.2% | 0.7224 |
| VEDA + WorkfrontRank | 62.2% | 86.7% | 90.0% | 94.4% | 0.7301 |

## Hard-category Top-1
| Category | N | Semantic | VEDA | + WorkfrontRank |
|---|---:|---:|---:|---:|
| granularity | 10 | 0.0% | 20.0% | 0.0% |
| hard_negative | 16 | 100.0% | 100.0% | 100.0% |
| out_of_sequence | 12 | 0.0% | 0.0% | 0.0% |
| phase | 12 | 58.3% | 100.0% | 100.0% |
| temporal | 12 | 100.0% | 100.0% | 100.0% |
| wbs | 12 | 8.3% | 83.3% | 16.7% |
| workfront | 16 | 0.0% | 25.0% | 87.5% |

## Reality-first behavior
- Set/granularity/revision relation accuracy: **72.2%** (36 cases)
- Longitudinal event-stream accuracy: **100.0%** (16 streams)

## Latency
- One-pass semantic + WorkfrontRank median: **382.3 ms**
- One-pass p95: **791.2 ms**

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
| DEV-0025 | workfront | 800074 | 9 | 4 | 1 | AMBIGUOUS |
| DEV-0028 | workfront | 800098 | None | None | 1 | AMBIGUOUS |
| DEV-0031 | workfront | 800122 | 21 | 5 | 2 | EXACT |
| DEV-0034 | workfront | 800146 | 10 | 1 | 1 | AMBIGUOUS |
| DEV-0035 | workfront | 800154 | 11 | 1 | 1 | AMBIGUOUS |
| DEV-0036 | workfront | 800162 | 13 | 3 | 1 | AMBIGUOUS |
| DEV-0037 | workfront | 800170 | 7 | 2 | 2 | AMBIGUOUS |
| DEV-0039 | workfront | 800186 | 10 | 6 | 1 | AMBIGUOUS |
| DEV-0053 | out_of_sequence | 800226 | 5 | 2 | 2 | EXACT |
| DEV-0054 | out_of_sequence | 800234 | 8 | 2 | 3 | EXACT |
| DEV-0055 | out_of_sequence | 800242 | 6 | 3 | 3 | EXACT |
| DEV-0056 | out_of_sequence | 800250 | 6 | 2 | 3 | EXACT |
| DEV-0057 | out_of_sequence | 800258 | 10 | 2 | 3 | EXACT |
| DEV-0058 | out_of_sequence | 800266 | 9 | 2 | 3 | EXACT |
| DEV-0059 | out_of_sequence | 800274 | 13 | 6 | 6 | EXACT |
| DEV-0060 | out_of_sequence | 800282 | 4 | 2 | 3 | EXACT |
| DEV-0061 | out_of_sequence | 800290 | 7 | 3 | 3 | EXACT |
| DEV-0062 | out_of_sequence | 800298 | 12 | 4 | 2 | EXACT |
| DEV-0063 | out_of_sequence | 800306 | 8 | 2 | 2 | EXACT |
| DEV-0064 | out_of_sequence | 800314 | 7 | 3 | 3 | EXACT |
| DEV-0075 | granularity | 800351 | 2 | 1 | 8 | NEW_SCOPE |
| DEV-0076 | granularity | 800352 | 4 | 3 | 9 | NEW_SCOPE |
| DEV-0077 | granularity | 800353 | 6 | 4 | 12 | NEW_SCOPE |
| DEV-0078 | granularity | 800354 | 3 | 1 | 3 | NEW_SCOPE |
| DEV-0079 | granularity | 800355 | 8 | 7 | 12 | NEW_SCOPE |
| DEV-0080 | granularity | 800356 | 3 | 3 | 5 | NEW_SCOPE |
| DEV-0081 | granularity | 800357 | 6 | 5 | 7 | NEW_SCOPE |
| DEV-0082 | granularity | 800358 | 8 | 8 | 14 | NEW_SCOPE |
| DEV-0083 | granularity | 800359 | 10 | 10 | None | NEW_SCOPE |
| DEV-0084 | granularity | 800360 | 3 | 2 | 17 | NEW_SCOPE |