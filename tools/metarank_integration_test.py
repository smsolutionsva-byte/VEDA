#!/usr/bin/env python3
"""Production integration regression tests for VEDA v0.3.2 MetaRank.

These tests focus on failure containment and API contracts rather than model
accuracy. Accuracy is evaluated by the frozen benchmark harness.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "VEDA_GOOSE_BENCHMARK"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BENCH))


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _fake(uid, score, features=None):
    return {
        "activity": {"uid": uid, "name": f"Activity {uid}"},
        "score": score,
        "features": dict(features or {}),
        "supporting": [],
        "conflicting": [],
        "from_agent": False,
    }


def direct_meta_tests():
    from veda.resolution import meta_router

    health = meta_router.model_health()
    assert_true(health.get("ok"), f"Meta model health failed: {health}")

    experts = {
        "semantic": [_fake(1, .9, {"rerank": .9, "dense": .8}), _fake(2, .8)],
        "engineering": [_fake(2, .92, {"engineering_rank_score": .92, "rank_margin": .12, "evidence_asset_count": 2, "asset_coverage": .5}), _fake(1, .85)],
        "tree": [_fake(1, .95, {"tree_branch": .9, "tree_leaf_text": .8}), _fake(3, .7)],
        "rescheduler": [_fake(3, .93, {"replan_oos_detected": True, "replan_recent_state": .8}), _fake(1, .7)],
    }
    ev = {"description": "P-101 alignment completed in Area B", "date": "2026-08-27"}
    rows, _ = meta_router.candidate_rows(ev, experts, {e: .5 for e in meta_router.EXPERTS})
    uids = [r["uid"] for r in rows]
    assert_true(len(uids) == len(set(uids)), "Candidate union contains duplicate UIDs")
    assert_true(set(uids) == {1, 2, 3}, f"Unexpected union: {uids}")

    out = meta_router.rank(ev, experts, limit=10)
    assert_true(out["candidates"], "MetaRank returned no candidates")
    assert_true(all(0 <= float(c["score"]) <= 1 for c in out["candidates"]), "Public ranking score left [0,1]")
    assert_true(all("meta_rank_raw" in c.get("features", {}) for c in out["candidates"]), "Raw LambdaMART margin missing")
    assert_true("rank_margin" in out["candidates"][0].get("features", {}), "Final rank margin missing")
    # Safety feature from Engineering must survive candidate-level fusion.
    c2 = next(c for c in out["candidates"] if int(c["activity"]["uid"]) == 2)
    assert_true(c2["features"].get("evidence_asset_count") == 2, "Engineering safety feature was lost")
    assert_true(c2["features"].get("asset_coverage") == .5, "Engineering asset coverage was lost")

    # Force ranker-model absence. The system must still return a normalized
    # utility-RRF ranking rather than raising or returning raw tiny RRF scores.
    old_ranker = meta_router.RANKER_MODEL
    try:
        meta_router.RANKER_MODEL = ROOT / "definitely-missing-metarank.json"
        meta_router._schema_health_cached.cache_clear()
        meta_router._booster_cached.cache_clear()
        fb = meta_router.rank(ev, experts, limit=10)
        assert_true(fb["diagnostics"]["mode"] == "utility_rrf_fallback", f"Unexpected fallback: {fb['diagnostics']}")
        assert_true(fb["candidates"], "Fallback returned no candidates")
        assert_true(all(0 <= float(c["score"]) <= 1 for c in fb["candidates"]), "Fallback ranking score left [0,1]")
    finally:
        meta_router.RANKER_MODEL = old_ranker
        meta_router._schema_health_cached.cache_clear()
        meta_router._booster_cached.cache_clear()


def engine_tests():
    import run as bench
    from veda.retrieval import engine
    from veda.resolution import tree_resolver
    from veda.retrieval import calibration
    from veda.resolution import risk

    tmp, pid, _, _, _ = bench.setup("holdout_v032", "hash")
    os.environ["VEDA_METARANK"] = "1"
    cases = [c for c in bench.load_jsonl(BENCH / "data" / "holdout_v032" / "cases.jsonl") if c.get("expected_uid") is not None]
    # One representative from each major failure family, including OOS.
    wanted_edges = {
        "same_name_different_wbs", "missing_asset_graph_and_frontier",
        "progress_override_active_workfront", "fine_event_coarse_schedule",
        "implicit_oos_changed_world", "ss_lag_oos", "same_branch_leaf_semantics",
        "physical_identity_vs_hot_state",
    }
    selected = []
    seen = set()
    for c in cases:
        edge = c.get("edge_case")
        if edge in wanted_edges and edge not in seen:
            selected.append(c); seen.add(edge)
    assert_true(len(selected) == len(wanted_edges), f"Missing representative edges: {wanted_edges-seen}")

    for c in selected:
        ev = dict(c["evidence"])
        ev.update({"id": c["id"], "project_id": pid, "state": "new"})
        if c["evidence"].get("historical_activity_uid") is not None:
            ev["historical_activity_uid"] = c["evidence"]["historical_activity_uid"]
        result = engine.hybrid_search(pid, ev, top_k=24, ensure_index=False)
        d = result["diagnostics"]
        assert_true(d.get("metarank_enabled") is True, f"MetaRank not default for {c['id']}")
        assert_true(result.get("engineering_candidates"), f"Engineering expert empty for {c['id']}")
        assert_true(result.get("semantic_candidates"), f"Semantic expert empty for {c['id']}")
        assert_true(result.get("candidates"), f"Final candidates empty for {c['id']}")
        assert_true(all(0 <= float(x["score"]) <= 1 for x in result["candidates"]), f"Bad score scale {c['id']}")
        best = result["candidates"][0]
        # Existing calibration/risk layers must accept MetaRank output without
        # confusing LambdaMART's raw margin for probability.
        cal = calibration.calibrated_probability(best["score"], pid, features=best.get("features") or {})
        pol = risk.assess(candidates=result["candidates"], calibration=cal,
                          validator={"result": "pass", "checks": []},
                          event={"state": "finish"})
        assert_true(pol.get("schedule_write_allowed") is not True, "MetaRank bypassed schedule-write safety")

    # End-to-end linker boundary: MetaRank -> calibration -> validators -> risk
    # -> evidence_links persistence.  This guards against score-semantics bugs
    # that unit-level ranking tests cannot see.
    from veda import db
    from veda.pipeline import linking
    link_case = selected[0]
    link_ev = dict(link_case["evidence"])
    link_id = "meta-integration-link-e1"
    db.insert("evidence", {
        "id": link_id, "project_id": pid, "source_file": link_ev.get("source_file") or "integration.txt",
        "locator": "integration:1", "date": link_ev.get("date"),
        "discipline": link_ev.get("discipline"), "location": link_ev.get("location"),
        "description": link_ev.get("description"), "state": "new", "security_state": "clean",
        "provenance": "SOURCE_FILE", "created_at": db.now(),
    })
    persisted_ev = db.q1("SELECT * FROM evidence WHERE id=?", [link_id])
    linking.link_evidence(pid, evidence_rows=[persisted_ev], raise_reviews=False)
    links = db.q("SELECT * FROM evidence_links WHERE evidence_id=? ORDER BY is_candidate ASC, rank_score DESC", [link_id])
    assert_true(bool(links), "MetaRank linker produced no persisted evidence_links")
    top_link = links[0]
    feature_payload = json.loads(top_link.get("feature_json") or "{}")
    assert_true("meta_rank_raw" in feature_payload, "Persisted link lost MetaRank raw margin")
    assert_true(0 <= float(top_link.get("rank_score") or 0) <= 1, "Persisted MetaRank score outside [0,1]")
    policy_payload = json.loads(top_link.get("policy_json") or "{}") if top_link.get("policy_json") else {}
    assert_true(policy_payload.get("schedule_write_allowed") is not True, "Linker persistence bypassed schedule-write safety")

    # Explicit legacy flags must disable MetaRank automatically, preserving old
    # benchmark/reproducibility behavior.
    c = selected[0]
    ev = dict(c["evidence"]); ev.update({"id": c["id"]+"-legacy", "project_id": pid, "state": "new"})
    legacy = engine.hybrid_search(pid, ev, top_k=8, ensure_index=False,
                                  use_workfront=False, use_adaptive_gate=False)
    assert_true(legacy["diagnostics"].get("metarank_enabled") is False, "Explicit legacy flags no longer reproduce legacy path")

    # Expert failure isolation: Tree can fail and retrieval must still complete,
    # with the exception recorded for auditability.
    original = tree_resolver.rerank
    def boom(*args, **kwargs):
        raise RuntimeError("synthetic tree failure")
    tree_resolver.rerank = boom
    try:
        failed = engine.hybrid_search(pid, ev, top_k=8, ensure_index=False, use_metarank=True)
        assert_true(failed.get("candidates"), "Partial expert failure killed retrieval")
        assert_true("tree" in (failed["diagnostics"].get("expert_errors") or {}), "Expert failure was not audited")
    finally:
        tree_resolver.rerank = original

    tmp.cleanup()


def main():
    direct_meta_tests()
    engine_tests()
    print(json.dumps({"status": "PASS", "suite": "metarank_integration_test"}, indent=2))


if __name__ == "__main__":
    main()
