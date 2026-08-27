# VEDA v0.3.0 — Adaptive ExecutionRank fresh holdout

## Evaluation hygiene
- Gate coefficients were trained **only on DEV**.
- The previous TEST split had already influenced the architecture choice, so it is not used as the headline validation set.
- A new holdout was generated only after the gate was frozen: seed `104729`, **13,436 activities**, **10,120 relationships**, **180 resolver cases**.
- **154 cases** contain a target UID and support Top-k candidate ranking evaluation. Of those, **144 are EXACT links** and 10 are `PART_OF` granularity links.
- **36 cases** test non-EXACT relation inference (`AGGREGATES`, `PART_OF`, `NEW_SCOPE`, `SPLIT_ACROSS`).
- Benchmark category/family labels are analysis-only and are **not gate features**.

## DEV gate training / out-of-fold estimate
- EngineeringRank Top-1: **62.22%**
- WorkfrontRank Top-1: **62.22%**
- Adaptive gate 5-fold out-of-fold Top-1: **73.33%**
- Two-expert DEV oracle ceiling: **73.33%**
- Gate OOF ROC-AUC: **0.9818**; Brier: **0.0320**

## Fresh holdout — UID-labelled ranking (154 cases)
| Resolver | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic only | 46.10% | 55.19% | 62.34% | 82.47% | 0.5506 |
| EngineeringRank | 61.69% | 76.62% | 86.36% | 91.56% | 0.7102 |
| Always-on WorkfrontRank | 58.44% | 76.62% | 83.12% | 88.96% | 0.6841 |
| Adaptive ExecutionRank | 64.94% | 81.17% | 88.31% | 94.81% | 0.7444 |

## Fresh holdout — EXACT links only (144 cases)
| Resolver | Top-1 | R@3 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|---:|
| Semantic only | 48.61% | 56.94% | 63.19% | 81.25% | 0.5690 |
| EngineeringRank | 65.28% | 78.47% | 87.50% | 90.97% | 0.7353 |
| Always-on WorkfrontRank | 62.50% | 81.94% | 88.89% | 94.44% | 0.7267 |
| Adaptive ExecutionRank | 68.75% | 83.33% | 89.58% | 94.44% | 0.7719 |

**Two-expert oracle Top-1 ceiling on UID-labelled cases:** 70.13%
**Adaptive net Top-1 change vs EngineeringRank:** +3.25 percentage points.
**Cases rescued vs EngineeringRank:** 12; **cases harmed:** 7.

## Category Top-1 (UID-labelled cases)
| Category | N | Semantic | Engineering | Workfront | Adaptive |
|---|---:|---:|---:|---:|---:|
| adaptive_mixed | 64 | 53.12% | 62.50% | 57.81% | 59.38% |
| granularity | 10 | 10.00% | 10.00% | 0.00% | 10.00% |
| hard_negative | 16 | 100.00% | 100.00% | 100.00% | 100.00% |
| out_of_sequence | 12 | 0.00% | 0.00% | 0.00% | 0.00% |
| phase | 12 | 58.33% | 100.00% | 100.00% | 100.00% |
| temporal | 12 | 100.00% | 100.00% | 100.00% | 100.00% |
| wbs | 12 | 8.33% | 83.33% | 16.67% | 83.33% |
| workfront | 16 | 0.00% | 25.00% | 68.75% | 68.75% |

## New mixed-adversarial families
| Family | N | Semantic | Engineering | Workfront | Adaptive |
|---|---:|---:|---:|---:|---:|
| location_identity_vs_misleading_frontier | 8 | 12.50% | 25.00% | 0.00% | 25.00% |
| missing_identity_unique_execution_frontier | 8 | 0.00% | 37.50% | 25.00% | 25.00% |
| multiple_hot_frontiers_action_decides | 8 | 12.50% | 37.50% | 0.00% | 0.00% |
| oos_explicit_identity_vs_ready_wrong_graph | 8 | 100.00% | 100.00% | 100.00% | 100.00% |
| phase_identity_vs_hot_wrong_phase | 8 | 100.00% | 100.00% | 100.00% | 100.00% |
| strong_identity_vs_misleading_frontier | 8 | 100.00% | 100.00% | 100.00% | 100.00% |
| temporal_identity_when_graph_non_discriminative | 8 | 100.00% | 100.00% | 100.00% | 100.00% |
| weak_location_graph_breaks_tie | 8 | 0.00% | 0.00% | 37.50% | 25.00% |

## Relation / Reality Graph evaluation
- Overall non-EXACT relation accuracy: **75.00%** across 36 cases.
- `AGGREGATES`: **100.00%** (10 cases)
- `NEW_SCOPE`: **100.00%** (8 cases)
- `PART_OF`: **10.00%** (10 cases)
- `SPLIT_ACROSS`: **100.00%** (8 cases)
- Longitudinal Reality Graph stream accuracy: **100.00%** on 16 frozen streams.

## Routing behavior
- Engineering selected: **123 / 154**
- Workfront selected: **31 / 154**
- No `category`, `edge_case`, or hardcoded `if WBS -> Engineering` feature exists in the gate.
- If the model artifact is missing or incompatible, runtime safely defaults to EngineeringRank.

## Interpretation
- Adaptive preserved WBS Top-1 at **83.33%**, avoiding the **16.67%** always-on Workfront collapse.
- Adaptive preserved the original workfront-rescue category at **68.75%**, versus EngineeringRank **25.00%**.
- On EXACT links only, Adaptive reached **68.75%**, compared with EngineeringRank **65.28%** and WorkfrontRank **62.50%**.
- The gate remains below the two-expert oracle ceiling, and the new mixed families expose misroutes. Those holdout failures are not tuned away in v0.3.0; they should become training evidence only for a future independently-generated benchmark.
- `PART_OF` relation inference remains weak (**10%**) and is a separate Reality Graph/granularity problem rather than something the expert gate should hide.