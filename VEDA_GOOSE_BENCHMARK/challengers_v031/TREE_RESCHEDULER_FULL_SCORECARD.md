# VEDA TreeRank + Rescheduler Full Challenger Scorecard

**Status:** Complete challenger experiment  
**Code state:** Frozen before TEST; no Tree/Rescheduler/harness changes after freeze.  
**Freeze hashes:**
```text
e402ef600b11983e053391a65796bd5c5c8eb6db1c230b4d6b0f1416668fc0fc  veda/resolution/tree_resolver.py
4b0aa208558b0889327ba021e2a73f2da1173847facd12ed43f74a96f8f5e1e4  veda/resolution/rescheduler.py
8ef9296dbd85f2612e35e847300392ca79f9e6a932df692be3a4cde8476bdb52  VEDA_GOOSE_BENCHMARK/run_challengers_fast.py
```

## 1. Evaluation design

Two challenger architectures were evaluated against the existing VEDA baselines:

- **TreeRank (standalone):** hierarchy-native schedule resolver using parent/child/sibling ancestry, branch context, leaf evidence, action, phase, location and dates. It also emits granularity relation hypotheses.
- **Rescheduler (standalone):** opportunistic/continual-planning resolver. It performs indexed evidence-directed candidate screening and then counterfactual rolling-horizon beam search over a small disputed candidate set. It asks which candidate produces the most coherent changed world and near-term continuation.

Existing baselines are **SemanticRank**, **EngineeringRank**, and **WorkfrontRank**. The mixed holdout also includes the previously frozen **Adaptive ExecutionRank** gate.

### Datasets

| Dataset | Schedule activities | Relationships | Total cases | UID-labelled cases | Non-EXACT relation cases |
|---|---:|---:|---:|---:|---:|
| DEV | 12,940 | 10,056 | 116 | 90 | 36 |
| TEST | 12,940 | 10,056 | 116 | 90 | 36 |
| Mixed v0.3 holdout | 13,436 | 10,120 | 180 | 154 | 36 |

**Important caveat:** DEV and TEST have different schedule/distractor seeds and UIDs, but many evidence templates are structurally mirrored. The 180-case mixed holdout is therefore the stronger cross-condition stress test for these challengers.

Tie-aware evaluation is conservative: when TreeRank or Rescheduler assigns the expected candidate exactly the same score as other indistinguishable candidates, the expected candidate receives the **worst rank in the tie group**. Deterministic UID/insertion order cannot create fake Top-1 wins.

---

## 2. Full DEV scorecard — 116 / 116 complete

| Resolver | N | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| SemanticRank | 90 | 40.00% | 55.56% | 60.00% | 84.44% | 0.5155 |
| EngineeringRank | 90 | 62.22% | 81.11% | 86.67% | 92.22% | 0.7224 |
| WorkfrontRank | 90 | 62.22% | 86.67% | 90.00% | 94.44% | 0.7301 |
| TreeRank (standalone) | 90 | 58.89% | 92.22% | 94.44% | 100.00% | 0.7680 |
| Rescheduler (standalone) | 90 | 48.89% | 77.78% | 91.11% | 91.11% | 0.6652 |

### DEV category Top-1

| Category | N | Semantic | Engineering | Workfront | Adaptive | Tree | Rescheduler |
|---|---:|---:|---:|---:|---:|---:|---:|
| granularity | 10 | 0.00% | 20.00% | 0.00% | — | 10.00% | 0.00% |
| hard_negative | 16 | 100.00% | 100.00% | 100.00% | — | 100.00% | 100.00% |
| new_scope | 0 | — | — | — | — | — | — |
| out_of_sequence | 12 | 0.00% | 0.00% | 0.00% | — | 0.00% | 0.00% |
| phase | 12 | 58.33% | 100.00% | 100.00% | — | 100.00% | 0.00% |
| revision | 0 | — | — | — | — | — | — |
| temporal | 12 | 100.00% | 100.00% | 100.00% | — | 100.00% | 100.00% |
| wbs | 12 | 8.33% | 83.33% | 16.67% | — | 100.00% | 0.00% |
| workfront | 16 | 0.00% | 25.00% | 87.50% | — | 0.00% | 100.00% |

### DEV Tree granularity / relation accuracy

| Relation | N | Tree accuracy |
|---|---:|---:|
| AGGREGATES | 10 | 100.00% |
| NEW_SCOPE | 8 | 100.00% |
| PART_OF | 10 | 0.00% |
| SPLIT_ACROSS | 8 | 100.00% |
| **Overall non-EXACT** | **36** | **72.22%** |

---

## 3. Full frozen TEST scorecard — 116 / 116 complete

| Resolver | N | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| SemanticRank | 90 | 44.44% | 54.44% | 60.00% | 83.33% | 0.5404 |
| EngineeringRank | 90 | 60.00% | 77.78% | 90.00% | 94.44% | 0.7116 |
| WorkfrontRank | 90 | 61.11% | 84.44% | 90.00% | 95.56% | 0.7281 |
| TreeRank (standalone) | 90 | 58.89% | 92.22% | 94.44% | 100.00% | 0.7680 |
| Rescheduler (standalone) | 90 | 48.89% | 77.78% | 91.11% | 91.11% | 0.6652 |

### TEST category Top-1

| Category | N | Semantic | Engineering | Workfront | Adaptive | Tree | Rescheduler |
|---|---:|---:|---:|---:|---:|---:|---:|
| granularity | 10 | 20.00% | 20.00% | 0.00% | — | 10.00% | 0.00% |
| hard_negative | 16 | 100.00% | 100.00% | 100.00% | — | 100.00% | 100.00% |
| new_scope | 0 | — | — | — | — | — | — |
| out_of_sequence | 12 | 8.33% | 8.33% | 0.00% | — | 0.00% | 0.00% |
| phase | 12 | 75.00% | 100.00% | 100.00% | — | 100.00% | 0.00% |
| revision | 0 | — | — | — | — | — | — |
| temporal | 12 | 100.00% | 100.00% | 100.00% | — | 100.00% | 100.00% |
| wbs | 12 | 0.00% | 75.00% | 16.67% | — | 100.00% | 0.00% |
| workfront | 16 | 0.00% | 12.50% | 81.25% | — | 0.00% | 100.00% |

### TEST Tree granularity / relation accuracy

| Relation | N | Tree accuracy |
|---|---:|---:|
| AGGREGATES | 10 | 100.00% |
| NEW_SCOPE | 8 | 100.00% |
| PART_OF | 10 | 0.00% |
| SPLIT_ACROSS | 8 | 100.00% |
| **Overall non-EXACT** | **36** | **72.22%** |

---

## 4. Mixed v0.3 holdout — 180 / 180 complete

This set adds 64 mixed adversarial cases on top of the original challenge families and searches against **13,436 activities**.

| Resolver | N | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| SemanticRank | 154 | 46.10% | 55.19% | 62.34% | 82.47% | 0.5506 |
| EngineeringRank | 154 | 61.69% | 76.62% | 86.36% | 91.56% | 0.7102 |
| WorkfrontRank | 154 | 58.44% | 76.62% | 83.12% | 88.96% | 0.6841 |
| Adaptive ExecutionRank | 154 | 64.94% | 81.17% | 88.31% | 94.81% | 0.7444 |
| TreeRank (standalone) | 154 | 65.58% | 82.47% | 84.42% | 87.66% | 0.7358 |
| Rescheduler (standalone) | 154 | 43.51% | 76.62% | 90.91% | 94.81% | 0.6338 |

### Exact-link-only ranking — 144 cases

| Resolver | N | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| SemanticRank | 144 | 48.61% | 56.94% | 63.19% | 81.25% | 0.5690 |
| EngineeringRank | 144 | 65.28% | 78.47% | 87.50% | 90.97% | 0.7353 |
| WorkfrontRank | 144 | 62.50% | 81.94% | 88.89% | 94.44% | 0.7267 |
| Adaptive ExecutionRank | 144 | 68.75% | 83.33% | 89.58% | 94.44% | 0.7719 |
| TreeRank (standalone) | 144 | 69.44% | 86.11% | 86.81% | 86.81% | 0.7653 |
| Rescheduler (standalone) | 144 | 46.53% | 80.56% | 95.83% | 100.00% | 0.6697 |

### Mixed holdout category Top-1

| Category | N | Semantic | Engineering | Workfront | Adaptive | Tree | Rescheduler |
|---|---:|---:|---:|---:|---:|---:|---:|
| adaptive_mixed | 64 | 53.12% | 62.50% | 57.81% | 59.38% | 75.00% | 39.06% |
| granularity | 10 | 10.00% | 10.00% | 0.00% | 10.00% | 10.00% | 0.00% |
| hard_negative | 16 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| out_of_sequence | 12 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| phase | 12 | 58.33% | 100.00% | 100.00% | 100.00% | 100.00% | 0.00% |
| temporal | 12 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| wbs | 12 | 8.33% | 83.33% | 16.67% | 83.33% | 100.00% | 0.00% |
| workfront | 16 | 0.00% | 25.00% | 68.75% | 68.75% | 0.00% | 87.50% |

### Mixed adversarial families

| Mixed adversarial family | N | Tree Top-1 | Rescheduler Top-1 |
|---|---:|---:|---:|
| `location_identity_vs_misleading_frontier` | 8 | 100.00% | 0.00% |
| `missing_identity_unique_execution_frontier` | 8 | 0.00% | 12.50% |
| `multiple_hot_frontiers_action_decides` | 8 | 100.00% | 0.00% |
| `oos_explicit_identity_vs_ready_wrong_graph` | 8 | 100.00% | 100.00% |
| `phase_identity_vs_hot_wrong_phase` | 8 | 100.00% | 0.00% |
| `strong_identity_vs_misleading_frontier` | 8 | 100.00% | 100.00% |
| `temporal_identity_when_graph_non_discriminative` | 8 | 100.00% | 100.00% |
| `weak_location_graph_breaks_tie` | 8 | 0.00% | 0.00% |

### Holdout Tree granularity / relation accuracy

| Relation | N | Tree accuracy |
|---|---:|---:|
| AGGREGATES | 10 | 100.00% |
| NEW_SCOPE | 8 | 100.00% |
| PART_OF | 10 | 0.00% |
| SPLIT_ACROSS | 8 | 100.00% |
| **Overall non-EXACT** | **36** | **72.22%** |

For comparison, the existing Reality Graph relation inference on this same holdout scored **75.00% overall**, including **10.00% on PART_OF**; TreeRank scored **72.22% overall** and **0.00% on PART_OF**. Tree's current hierarchy model therefore does not yet solve the key “field event finer than scheduled leaf” problem.

---

## 5. Main findings

### TreeRank

1. **Strong hierarchy expert.** On frozen TEST it scored **100% Top-1** on WBS, phase, temporal and hard-negative categories.
2. **Mixed holdout win.** Overall UID-labelled Top-1 on the 180-case mixed holdout was **65.58%**, slightly above Adaptive ExecutionRank (**64.94%**) and EngineeringRank (**61.69%**).
3. **Exact-link subset:** TreeRank reached **69.44% Top-1** on 144 exact links, versus Adaptive ExecutionRank at **68.75%**.
4. **Excellent when identity is hierarchical; weak when identity is purely live-state based.** Tree scored **0% Top-1** on the legacy workfront category because it intentionally has no recent-execution-state signal.
5. **Granularity is only partially solved.** AGGREGATES, NEW_SCOPE and SPLIT_ACROSS were each **100%**, but PART_OF was **0%**. The missing abstraction is a virtual/latent field child beneath a coarse scheduled leaf.

### Rescheduler

1. **Not a good universal activity resolver in its present form.** Frozen TEST Top-1 was **48.89%**, below EngineeringRank (**60.00%**) and WorkfrontRank (**61.11%**).
2. **Very strong workfront specialist.** Frozen TEST workfront Top-1 was **100%**, versus WorkfrontRank **81.25%** and EngineeringRank **12.50%**.
3. On the mixed holdout workfront family it retained **87.50% Top-1**, versus WorkfrontRank and Adaptive at **68.75%**.
4. It fails hard when a strong WBS/phase identity should override a more attractive future plan: **0% WBS Top-1** and **0% phase Top-1** on frozen TEST.
5. The current benchmark measures **activity identity**, not actual schedule-repair quality. These results therefore show that the Rescheduler is best treated as a specialist **state-transition / next-plan expert**, not as the primary observation-to-activity matcher.

### Complementarity

The challengers fail in opposite regimes:

- **TreeRank:** excellent at hierarchy, poor at pure live-workfront ambiguity.
- **Rescheduler:** excellent at live-workfront continuity, poor when hierarchy/phase identity should dominate.
- **EngineeringRank:** strongest general baseline.
- **WorkfrontRank:** useful graph-state prior.
- **Adaptive ExecutionRank:** learned two-expert routing already outperforms either Engineering or Workfront alone on the mixed holdout.

This strongly supports a **multi-expert architecture** rather than replacing VEDA with either challenger.

---

## 6. Recommended VEDA architecture after this experiment

```text
Observation
   |
   +--> EngineeringRank  -- physical/semantic identity
   |
   +--> TreeRank         -- hierarchical identity + granularity
   |
   +--> WorkfrontRank    -- live execution-state prior
   |
   +--> Rescheduler      -- counterfactual state transition / near-term plan coherence
   |
   '--> Learned contextual gate / agent investigation
          |
          +-- expert authority based on evidence
          +-- abstain when experts disagree without discriminating evidence
          '-- deterministic safety before schedule mutation
```

**Do not** hardcode rules such as `if WBS -> Tree` or `if asset missing -> Rescheduler`. The next experiment should train a multi-expert gate on DEV using context-only features and evaluate it on a new holdout that is not used during architecture design.

---

## 7. Runtime note

The challenger sweeps were executed in isolated shards because the counterfactual planner and hierarchy resolver can be expensive over 13k+ activities. The current harness did not retain per-case timing, so a single global median cannot be reconstructed exactly. Shard-level observed ranges were:

| Dataset | Tree shard-median range | Max Tree shard p95 | Rescheduler shard-median range | Max Rescheduler shard p95 |
|---|---:|---:|---:|---:|
| DEV | 629–1503 ms | 21218 ms | 186–671 ms | 11449 ms |
| TEST | 957–1543 ms | 13370 ms | 154–1193 ms | 9420 ms |
| Mixed holdout | 1078–2367 ms | 16705 ms | 430–2643 ms | 10711 ms |

These are engineering diagnostics, not production latency claims; the runs used the deterministic/hash-oriented local benchmark environment and multiple concurrent shards.

---

## 8. Verdict

**TreeRank survives and deserves promotion to a first-class VEDA expert.** It produced the strongest standalone Top-1 result on the 180-case mixed holdout and clearly improves hierarchy-sensitive cases.

**Rescheduler does not survive as a universal resolver, but it absolutely survives as a specialist.** Its 100% frozen-TEST and 87.5% mixed-holdout workfront scores show that counterfactual/continual-plan reasoning carries useful information when identity is weak and execution state matters.

The next “golden goose” experiment should therefore be a **four-expert learned gate** rather than choosing one architecture:
Engineering + Tree + Workfront + Rescheduler.
