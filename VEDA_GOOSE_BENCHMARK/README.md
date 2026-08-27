# VEDA Reality Graph + WorkfrontRank benchmark

This benchmark is intentionally adversarial. Each split contains **12,940 schedule activities** (more than 10,000 distractors), repeated names/tags/actions/WBS branches, schedule-network relationships, live workfront history, schedule-revision lineage, and longitudinal field evidence.

It compares three systems on the exact same retrieved candidate pool:

1. **Semantic-only** — reranker/dense/sparse evidence only.
2. **VEDA engineering rank** — v0.2.1 entity/WBS/date/graph reranking.
3. **VEDA + WorkfrontRank** — engineering rank plus dynamic execution-frontier prior and local heterogeneous Personalized PageRank.

The Reality Graph is tested separately on set-valued/granularity/revision links and longitudinal event streams: duplicate corroboration, contradictions, removal/reinstallation, asset replacement, monthly corrections, and location history.

`dev` and `test` use different schedule seeds and identities. Do not tune after inspecting `test`.

Run:

```powershell
python VEDA_GOOSE_BENCHMARK\generate.py
python VEDA_GOOSE_BENCHMARK\run.py --split dev --backend hash
python VEDA_GOOSE_BENCHMARK\run.py --split test --backend hash
# On a machine with the optional local BGE weights:
python VEDA_GOOSE_BENCHMARK\run.py --split test --backend bge-m3
```
