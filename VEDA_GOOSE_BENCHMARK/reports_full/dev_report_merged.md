# VEDA Reality Graph + WorkfrontRank — FULL DEV (merged isolated shards)

- Activities: **12,940**
- Resolver cases: **116 / 116**
- Reality streams: **16**
- Backend: **hash-ngram-v2**

## Resolver comparison
| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic-only | 40.0% | 55.6% | 60.0% | 84.4% | 0.5155 |
| VEDA engineering rank | 62.2% | 81.1% | 86.7% | 92.2% | 0.7224 |
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