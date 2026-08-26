"""Offline edge-case tests for VEDA v0.2 hybrid entity resolution."""
from __future__ import annotations
import os, tempfile
os.environ["VEDA_DATA_DIR"] = tempfile.mkdtemp(prefix="veda_retrieval_test_")
os.environ["VEDA_EMBEDDING_BACKEND"] = "hash"

from veda import db
from veda.retrieval.entities import extract_asset_tags, extract_location_tags
from veda.retrieval.engine import hybrid_search
from veda.retrieval.calibration import calibrated_probability


def add_act(pid, uid, name, wbs_path, status="not_started", start="2026-08-20", finish="2026-08-30"):
    tags = extract_asset_tags(name, wbs_path)
    locs = extract_location_tags(name, wbs_path)
    db.insert("activities", {"project_id": pid, "uid": uid, "display_id": f"A-{uid}",
        "name": name, "wbs": f"1.{uid}", "wbs_name": wbs_path.split(" > ")[-1],
        "wbs_path": wbs_path, "status": status, "start": start, "finish": finish,
        "is_summary": 0, "asset_tags_json": db.jdumps(tags),
        "location_tags_json": db.jdumps(locs)})


def main():
    db.init_db(); pid="edge"; db.insert("projects", {"id":pid,"name":"Edge cases"})
    add_act(pid, 100, "Fabricate spool P-1043", "Project > Unit 4 > Area B > Piping > Fabrication", "complete", "2026-08-01", "2026-08-10")
    add_act(pid, 110, "Erect process line P-1043", "Project > Unit 4 > Area B > Piping > Pipe Rack B > Erection")
    add_act(pid, 120, "Weld process line P-1043", "Project > Unit 4 > Area B > Piping > Pipe Rack B > Welding", start="2026-08-28", finish="2026-09-05")
    add_act(pid, 210, "Erect process line P-1043", "Project > Unit 4 > Area C > Piping > Pipe Rack C > Erection")
    add_act(pid, 310, "Erection Lot 31", "Project > Unit 4 > Area B > Piping > Pipe Rack B > Line P-2207 > Erection")
    db.insert("relationships", {"project_id":pid,"pred_uid":100,"succ_uid":110,"pred_name":"Fabricate spool P-1043","succ_name":"Erect process line P-1043","type":"FS","lag_days":0,"driving":1})
    db.insert("relationships", {"project_id":pid,"pred_uid":110,"succ_uid":120,"pred_name":"Erect process line P-1043","succ_name":"Weld process line P-1043","type":"FS","lag_days":0,"driving":1})

    cases = [
      ({"description":"24 inch P1043 spool installed at pipe rack B","discipline":"piping","location":"Rack B","date":"2026-08-26"}, 110),
      ({"description":"P-1043 erection completed Area C","discipline":"piping","location":"Area C","date":"2026-08-26"}, 210),
      ({"description":"line P2207 installed rack B","discipline":"piping","location":"Rack B","date":"2026-08-25"}, 310),
      ({"description":"welding on P1043 rack B started","discipline":"piping","location":"Rack B","date":"2026-08-29"}, 120),
    ]
    for ev, expected in cases:
        ev["asset_tags_json"] = db.jdumps(extract_asset_tags(ev["description"]))
        ev["location_tags_json"] = db.jdumps(extract_location_tags(ev.get("location"), ev["description"]))
        res = hybrid_search(pid, ev, top_k=4)
        got = res["candidates"][0]["activity"]["uid"]
        assert got == expected, (ev, got, expected, [(c["activity"]["uid"], c["score"]) for c in res["candidates"]])

    # Cold start explicitly declares a prior, not fake empirical calibration.
    cold = calibrated_probability(0.9, pid)
    assert cold["mode"] == "conservative_prior"

    # Enough labelled human decisions activate project-specific Platt calibration.
    for i in range(15):
        db.insert("evidence_links", {"project_id":pid,"evidence_id":f"p{i}","activity_uid":110,
            "human_decision":"accepted","feature_json":db.jdumps({"raw_score":0.82 + 0.01*(i%8)})})
        db.insert("evidence_links", {"project_id":pid,"evidence_id":f"n{i}","activity_uid":210,
            "human_decision":"rejected","feature_json":db.jdumps({"raw_score":0.20 + 0.02*(i%8)})})
    lo = calibrated_probability(0.25, pid); hi = calibrated_probability(0.9, pid)
    assert hi["mode"] == "project_platt" and hi["probability"] > lo["probability"], (lo, hi)

    # Rich reviewed decisions activate the feature-level confidence model, which
    # can learn exact tags/WBS/graph/date and agent agreement separately.
    for i in range(45):
        pos = {"raw_score":0.82 + 0.002*(i%10), "rerank":0.92, "dense":0.86, "sparse":0.88,
               "asset_exact":1.0, "location":1.0, "discipline":1.0, "wbs":0.9,
               "temporal":0.85, "graph":0.9, "chainage":0.5, "date_corroboration":0.82,
               "rank_margin":0.18, "agent_agreement":1.0, "agent_confidence":0.9}
        neg = {"raw_score":0.35 + 0.002*(i%10), "rerank":0.3, "dense":0.42, "sparse":0.35,
               "asset_exact":0.0, "location":0.2, "discipline":0.3, "wbs":0.25,
               "temporal":0.35, "graph":0.35, "chainage":0.5, "date_corroboration":0.4,
               "rank_margin":0.0, "agent_agreement":0.0, "agent_confidence":0.0}
        db.insert("evidence_links", {"project_id":pid,"evidence_id":f"rp{i}","activity_uid":110,
            "human_decision":"accepted","feature_json":db.jdumps(pos)})
        db.insert("evidence_links", {"project_id":pid,"evidence_id":f"rn{i}","activity_uid":210,
            "human_decision":"rejected","feature_json":db.jdumps(neg)})
    fhi = calibrated_probability(0.9, pid, pos); flo = calibrated_probability(0.35, pid, neg)
    assert fhi["mode"] == "project_feature_logit" and fhi["probability"] > flo["probability"], (flo, fhi)
    print("retrieval edge cases: PASS")

if __name__ == "__main__": main()
