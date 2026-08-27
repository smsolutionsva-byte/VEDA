# VEDA OIL/SIH26122 Hard Benchmark

- Cases: **54**
- Backend: **bge-m3:BAAI/bge-m3**

## Retrieval
- Recall@1: **62.50%**
- Recall@3: **100.00%**
- Recall@5: **100.00%**
- MRR: **0.8125**

## Actual production linking pipeline
- Expected-outcome accuracy: **22.22%**
- Auto-link precision: **0.00%**
- Auto-link coverage: **0.00%**
- UNSAFE auto-links on review/negative cases: **0**

## Category matrix
| Category | N | Retrieval Top1* | Pipeline outcome | Unsafe auto-links |
|---|---:|---:|---:|---:|
| ambiguity | 6 | 100.0% | 100.0% | 0 |
| asset_tags | 6 | 100.0% | 0.0% | 0 |
| graph | 6 | 0.0% | 0.0% | 0 |
| location | 6 | 100.0% | 0.0% | 0 |
| metadata | 6 | 100.0% | 0.0% | 0 |
| safety_reporting | 6 | 100.0% | 100.0% | 0 |
| temporal | 6 | 0.0% | 0.0% | 0 |
| terminology | 6 | 100.0% | 0.0% | 0 |
| wbs | 6 | 0.0% | 0.0% | 0 |

*For expected-review cases without a single correct UID, retrieval Top1 is not treated as a failure; pipeline abstention is what matters.

## First 40 failures
| ID | Category | Edge | Expected | Retrieval rank | Pipeline state | Pipeline UID | Unsafe |
|---|---|---|---|---:|---|---:|---|
| OIL-HARD-0001 | terminology | erection | match / 1000 | 1 | needs_review | None | False |
| OIL-HARD-0002 | terminology | erection | match / 1100 | 1 | needs_review | 1100 | False |
| OIL-HARD-0003 | terminology | erection | match / 1200 | 1 | needs_review | None | False |
| OIL-HARD-0004 | terminology | installation | match / 1010 | 1 | needs_review | None | False |
| OIL-HARD-0005 | terminology | installation | match / 1110 | 1 | needs_review | 1110 | False |
| OIL-HARD-0006 | terminology | installation | match / 1210 | 1 | needs_review | None | False |
| OIL-HARD-0043 | asset_tags | tag_0 | match / 2000 | 1 | needs_review | 2000 | False |
| OIL-HARD-0044 | asset_tags | tag_1 | match / 2200 | 1 | needs_review | 2203 | False |
| OIL-HARD-0045 | asset_tags | tag_2 | match / 2400 | 1 | needs_review | 2400 | False |
| OIL-HARD-0046 | asset_tags | tag_3 | match / 2600 | 1 | needs_review | 2600 | False |
| OIL-HARD-0047 | asset_tags | tag_0 | match / 2020 | 1 | needs_review | 2020 | False |
| OIL-HARD-0048 | asset_tags | tag_1 | match / 2220 | 1 | needs_review | 2223 | False |
| OIL-HARD-0083 | location | location_disambiguation | match / 3000 | 1 | needs_review | None | False |
| OIL-HARD-0084 | location | location_disambiguation | match / 3300 | 1 | needs_review | None | False |
| OIL-HARD-0085 | location | location_disambiguation | match / 3600 | 1 | needs_review | None | False |
| OIL-HARD-0086 | location | location_disambiguation | match / 3900 | 1 | needs_review | None | False |
| OIL-HARD-0087 | location | location_disambiguation | match / 3030 | 1 | needs_review | None | False |
| OIL-HARD-0088 | location | location_disambiguation | match / 3330 | 1 | needs_review | None | False |
| OIL-HARD-0127 | wbs | identical_name_different_branch | match / 4000 | 2 | needs_review | 4000 | False |
| OIL-HARD-0128 | wbs | identical_name_different_branch | match / 4020 | 2 | needs_review | 4020 | False |
| OIL-HARD-0129 | wbs | identical_name_different_branch | match / 4040 | 2 | needs_review | 4040 | False |
| OIL-HARD-0130 | wbs | identical_name_different_branch | match / 4060 | 2 | needs_review | 4074 | False |
| OIL-HARD-0131 | wbs | identical_name_different_branch | match / 4080 | 2 | needs_review | 4080 | False |
| OIL-HARD-0132 | wbs | identical_name_different_branch | match / 4100 | 2 | needs_review | 4100 | False |
| OIL-HARD-0157 | temporal | same_text_different_window | match / 5000 | 2 | needs_review | None | False |
| OIL-HARD-0158 | temporal | same_text_different_window | match / 5020 | 2 | needs_review | None | False |
| OIL-HARD-0159 | temporal | same_text_different_window | match / 5040 | 2 | needs_review | None | False |
| OIL-HARD-0160 | temporal | same_text_different_window | match / 5060 | 2 | needs_review | None | False |
| OIL-HARD-0161 | temporal | same_text_different_window | match / 5080 | 2 | needs_review | None | False |
| OIL-HARD-0162 | temporal | same_text_different_window | match / 5100 | 2 | needs_review | None | False |
| OIL-HARD-0197 | graph | relationship_fs | match / 6000 | 2 | needs_review | None | False |
| OIL-HARD-0198 | graph | relationship_ss | match / 6030 | 2 | needs_review | None | False |
| OIL-HARD-0199 | graph | relationship_ff | match / 6060 | 2 | needs_review | None | False |
| OIL-HARD-0200 | graph | relationship_sf | match / 6090 | 2 | needs_review | None | False |
| OIL-HARD-0201 | graph | relationship_fs | match / 6120 | 2 | needs_review | None | False |
| OIL-HARD-0202 | graph | relationship_ss | match / 6150 | 2 | needs_review | None | False |
| OIL-HARD-0319 | metadata | discipline_disambiguation | match / 11000 | 1 | needs_review | 11000 | False |
| OIL-HARD-0320 | metadata | discipline_disambiguation | match / 11031 | 1 | needs_review | None | False |
| OIL-HARD-0321 | metadata | discipline_disambiguation | match / 11062 | 1 | needs_review | None | False |
| OIL-HARD-0322 | metadata | discipline_disambiguation | match / 11090 | 1 | needs_review | 11090 | False |

## Interpretation
A high retrieval score with poor pipeline outcome means the semantic engine may be working while the production linker is not using it correctly. Unsafe auto-links matter more than raw accuracy. Do not tune against this synthetic set alone; hold out real projects when NDA/sample OIL data becomes available.