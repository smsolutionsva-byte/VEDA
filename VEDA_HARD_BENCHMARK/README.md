# VEDA OIL / SIH26122 Hard Benchmark Pack

This folder is designed to be copied **as one folder** into the root of the VEDA project.

It contains **382 deterministic adversarial cases** generated with seed `26122`.

## What it tests

- terminology/action confusion: erection vs fabrication vs welding vs NDT vs testing etc.
- engineering asset tags and punctuation drift
- tags hidden in Primavera/custom metadata
- same tag + wrong action/location hard negatives
- location, unit, area, pipe rack, building/floor/grid and chainage disambiguation
- identical activity names under different WBS branches
- planned vs actual temporal windows and stale-schedule behavior
- cross-source date corroboration
- FS/SS/FF/SF relationship context, lag, driving links and valid out-of-sequence execution
- discipline disambiguation
- negation, blocker, planned-future work, partial progress, duplicate and historical evidence
- genuinely ambiguous records and new/unplanned activities that must go to review
- multiple assets in one evidence row
- OCR-ish tag corruption
- integration gap between `hybrid_search()` and the actual production `link_evidence()` pipeline

## Safe run

From the VEDA repo root:

```powershell
python VEDA_HARD_BENCHMARK\integration_audit.py
python VEDA_HARD_BENCHMARKun_hard_benchmark.py --mode quick
python VEDA_HARD_BENCHMARKun_hard_benchmark.py --mode full --backend bge-m3
```

The runner creates a temporary database and does **not** mutate real projects.

Outputs appear in `VEDA_HARD_BENCHMARK/reports/`.

## Important scoring philosophy

The benchmark separates **retrieval** from the **production linking decision**. A correct Top-1 candidate is not enough if VEDA silently links a record that says `not started`, contains two equally plausible activities, or describes new/unplanned work.

The critical metrics are therefore not only Recall@K/Top-1, but also **auto-link precision**, **coverage**, and **unsafe auto-links**.

This is synthetic infrastructure/OIL-style data, not a substitute for real anonymized OIL samples under NDA.
