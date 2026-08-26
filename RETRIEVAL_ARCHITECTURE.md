# VEDA Hybrid Schedule Entity Resolution (v0.2)

VEDA resolves messy field evidence to L5/L6 schedule activities using independent,
explainable signals. Horizun remains the schedule truth/CPM engine; retrieval never
mutates the schedule.

## Retrieval pipeline

1. **Engineering entity extraction** — equipment/line/instrument/spool/drawing tags,
   event type, richer location ontology, discipline and chainage.
2. **Progressive metadata filtering** — exact asset anchor first, then safe/soft
   location, discipline, event type, execution-window and human-confirmed WBS priors.
   Filters only narrow a pool when enough candidates survive, protecting recall.
3. **Hybrid retrieval** — BM25 lexical retrieval + dense embeddings, fused with RRF.
4. **BGE-M3 reranking (recommended)** — when `FlagEmbedding` and a local BGE-M3
   model are available, VEDA uses BGE-M3 dense vectors and its dense+sparse+late-
   interaction pair score on the short candidate set.
5. **Schedule context reranking** — WBS ancestry, actual/planned date semantics,
   FS/SS/FF/SF predecessor readiness (with lag and driving relationships), locations,
   disciplines, chainage and exact engineering tags.
6. **Agent judgement as a feature** — agent agreement/confidence can corroborate a
   candidate but is never added to another probability as if independent.
7. **Probability calibration** — raw retrieval/ranking score is separate from match
   probability. Human accept/reject decisions fit a Platt logistic calibrator. Before
   enough labels exist, the UI/API explicitly reports `conservative_prior` rather
   than pretending the score is empirically calibrated.
8. **Deterministic validation + human review** — security, date, location, tag,
   discipline, duplication and source-trust gates remain outside the LLM.

## Recommended high-accuracy setup

```bash
pip install -r requirements.txt
pip install -r requirements-retrieval.txt
```

Cache `BAAI/bge-m3` on the target machine, then set either:

```bash
VEDA_EMBEDDING_BACKEND=bge-m3
VEDA_EMBEDDING_MODEL_PATH=/models/bge-m3
```

or, only on a development machine where model downloads are acceptable:

```bash
VEDA_EMBEDDING_BACKEND=bge-m3
VEDA_ALLOW_MODEL_DOWNLOAD=1
```

Offline/uncached environments automatically use `hash-ngram-v2`; this is a safety
fallback, not the recommended production embedding model.

## New MCP tools

- `veda_activity_search` — hybrid schedule entity resolution for evidence/query text.
- `veda_activity_context` — WBS + tags + relationships for one stable activity UID.
- `veda_match_calibration` — calibration mode, Brier score and reliability bins.

## Confidence semantics

`retrieval_score` ranks candidates. It is **not a probability**.

`confidence` on new evidence links is the calibrated/provisional probability returned
by the calibration layer. `calibration_mode` declares whether it came from project
labels, organization-wide labels, or the conservative cold-start prior.
