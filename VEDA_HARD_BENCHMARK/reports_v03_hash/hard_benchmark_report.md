# VEDA OIL/SIH26122 Hard Benchmark

- Cases: **382**
- Backend: **hash-ngram-v2**
- Dataset SHA-256: `f6601f98032ce3c0657d680e5ba98651e3681e63d8f2bffe65641d27381d253b`

## Retrieval
- Recall@1: **70.23%**
- Recall@3: **97.69%**
- Recall@5: **100.00%**
- MRR: **0.8370**

## Actual production linking pipeline
- Expected-outcome accuracy: **4.71%**
- Auto-link precision: **N/A (no auto-links)**
- Auto-link coverage: **0.00%**
- UNSAFE auto-links on review/negative cases: **0**

## Category matrix
| Category | N | Retrieval Top1* | Pipeline outcome | Unsafe auto-links |
|---|---:|---:|---:|---:|
| ambiguity | 36 | N/A | 0.0% | 0 |
| asset_tags | 52 | 78.8% | 0.0% | 0 |
| graph | 44 | 2.3% | 0.0% | 0 |
| location | 44 | 72.7% | 0.0% | 0 |
| metadata | 40 | 100.0% | 0.0% | 0 |
| safety_reporting | 54 | 100.0% | 33.3% | 0 |
| temporal | 40 | 92.5% | 0.0% | 0 |
| terminology | 42 | 88.1% | 0.0% | 0 |
| wbs | 30 | 3.3% | 0.0% | 0 |

*For expected-review cases without a single correct UID, retrieval Top1 is not treated as a failure; pipeline abstention is what matters.

## First 40 failures
| ID | Category | Edge | Expected | Retrieval rank | Pipeline state | Pipeline UID | Unsafe |
|---|---|---|---|---:|---|---:|---|
| OIL-HARD-0001 | terminology | erection | match / 1000 | 1 | historical | None | False |
| OIL-HARD-0002 | terminology | erection | match / 1100 | 1 | historical | None | False |
| OIL-HARD-0003 | terminology | erection | match / 1200 | 1 | historical | None | False |
| OIL-HARD-0004 | terminology | installation | match / 1010 | 1 | historical | None | False |
| OIL-HARD-0005 | terminology | installation | match / 1110 | 1 | historical | None | False |
| OIL-HARD-0006 | terminology | installation | match / 1210 | 1 | historical | None | False |
| OIL-HARD-0007 | terminology | alignment | match / 1020 | 1 | historical | None | False |
| OIL-HARD-0008 | terminology | alignment | match / 1120 | 1 | historical | None | False |
| OIL-HARD-0009 | terminology | alignment | match / 1220 | 1 | historical | None | False |
| OIL-HARD-0010 | terminology | fitup | match / 1030 | 1 | historical | None | False |
| OIL-HARD-0011 | terminology | fitup | match / 1130 | 1 | historical | None | False |
| OIL-HARD-0012 | terminology | fitup | match / 1230 | 1 | historical | None | False |
| OIL-HARD-0013 | terminology | welding | match / 1040 | 1 | historical | None | False |
| OIL-HARD-0014 | terminology | welding | match / 1140 | 2 | historical | None | False |
| OIL-HARD-0015 | terminology | welding | match / 1240 | 1 | historical | None | False |
| OIL-HARD-0016 | terminology | ndt | match / 1050 | 1 | historical | None | False |
| OIL-HARD-0017 | terminology | ndt | match / 1150 | 1 | historical | None | False |
| OIL-HARD-0018 | terminology | ndt | match / 1250 | 1 | historical | None | False |
| OIL-HARD-0019 | terminology | hydrotest | match / 1060 | 1 | historical | None | False |
| OIL-HARD-0020 | terminology | hydrotest | match / 1160 | 1 | historical | None | False |
| OIL-HARD-0021 | terminology | hydrotest | match / 1260 | 1 | historical | None | False |
| OIL-HARD-0022 | terminology | cable_pulling | match / 1070 | 1 | historical | None | False |
| OIL-HARD-0023 | terminology | cable_pulling | match / 1170 | 1 | historical | None | False |
| OIL-HARD-0024 | terminology | cable_pulling | match / 1270 | 1 | historical | None | False |
| OIL-HARD-0025 | terminology | termination | match / 1080 | 1 | historical | None | False |
| OIL-HARD-0026 | terminology | termination | match / 1180 | 1 | historical | None | False |
| OIL-HARD-0027 | terminology | termination | match / 1280 | 1 | historical | None | False |
| OIL-HARD-0028 | terminology | loop_check | match / 1090 | 1 | historical | None | False |
| OIL-HARD-0029 | terminology | loop_check | match / 1190 | 1 | historical | None | False |
| OIL-HARD-0030 | terminology | loop_check | match / 1290 | 1 | historical | None | False |
| OIL-HARD-0031 | terminology | calibration | match / 1100 | 1 | historical | None | False |
| OIL-HARD-0032 | terminology | calibration | match / 1200 | 1 | historical | None | False |
| OIL-HARD-0033 | terminology | calibration | match / 1300 | 1 | historical | None | False |
| OIL-HARD-0034 | terminology | excavation | match / 1110 | 2 | historical | None | False |
| OIL-HARD-0035 | terminology | excavation | match / 1210 | 2 | historical | None | False |
| OIL-HARD-0036 | terminology | excavation | match / 1310 | 2 | historical | None | False |
| OIL-HARD-0037 | terminology | backfill | match / 1120 | 1 | historical | None | False |
| OIL-HARD-0038 | terminology | backfill | match / 1220 | 1 | historical | None | False |
| OIL-HARD-0039 | terminology | backfill | match / 1320 | 1 | historical | None | False |
| OIL-HARD-0040 | terminology | concrete | match / 1130 | 1 | historical | None | False |

## Interpretation
A high retrieval score with poor pipeline outcome means the semantic engine may be working while the production linker is not using it correctly. Unsafe auto-links matter more than raw accuracy. Do not tune against this synthetic set alone; hold out real projects when NDA/sample OIL data becomes available.