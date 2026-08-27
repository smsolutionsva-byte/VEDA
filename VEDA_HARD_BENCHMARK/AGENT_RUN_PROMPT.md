# Paste this to the local coding agent

You are evaluating VEDA against the bundled adversarial OIL/SIH26122 benchmark.

Rules:
1. Do NOT alter the benchmark cases, expected UIDs, expected outcomes, or scoring logic merely to improve the score.
2. Do NOT touch real VEDA project data. The runner creates a temporary VEDA_DATA_DIR itself.
3. Run `python VEDA_HARD_BENCHMARK/integration_audit.py` first.
4. Run the quick benchmark first using the already-installed environment:
   `python VEDA_HARD_BENCHMARK/run_hard_benchmark.py --mode quick`
5. If that runs, execute the full benchmark with the real BGE backend already installed:
   `python VEDA_HARD_BENCHMARK/run_hard_benchmark.py --mode full --backend bge-m3`
   Add `--allow-model-download` only if weights are not already available and the operator permits network/model downloads.
6. Paste/return BOTH generated files:
   - `VEDA_HARD_BENCHMARK/reports/hard_benchmark_report.md`
   - the `summary` object from `hard_benchmark_results.json`
7. Pay special attention to `unsafe_autolinks`. A system that abstains too often is annoying; a system that confidently writes false actuals is dangerous.
8. If retrieval Recall@K is high but production pipeline accuracy is poor, inspect whether `veda.pipeline.linking.link_evidence()` is actually consuming `veda.retrieval.engine.hybrid_search()` and calibrated confidence. Do not assume it is.
9. Fix production code, not benchmark expectations. After each fix rerun the full benchmark and show before/after metrics.
10. Preserve the architecture: embeddings + sparse retrieval + engineering tags + metadata + WBS + dates + graph + deterministic validators + calibrated confidence + human review. Do not replace all of this with one LLM call.
11. For review/ambiguous/negated/planned-work cases, false automatic links are a critical failure even if the top semantic candidate looks plausible.
12. Do not claim production accuracy from this synthetic benchmark. It is a hard regression/evaluation harness until real OIL sample/NDA data is available.

When reporting results, give:
- runtime/backend verification
- Recall@1/3/5/10 and MRR
- production pipeline outcome accuracy
- auto-link precision and coverage
- number and IDs of unsafe auto-links
- category-level table
- top failure modes
- whether hybrid retrieval is wired into the actual linker
- exact patches you recommend next
