"""Focused offline checks for the planner workstation, voice correction and RAG pack."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TMP = tempfile.TemporaryDirectory(prefix="veda_review_voice_rag_")
os.environ["VEDA_DATA_DIR"] = TMP.name
sys.path.insert(0, str(ROOT))

from veda import db  # noqa: E402
from veda.api import routes  # noqa: E402
from veda.mcpc import veda_server  # noqa: E402
from veda.pipeline import field_capture  # noqa: E402


def check(value, message):
    if not value:
        raise AssertionError(message)


def main() -> None:
    try:
        db.init_db()
        project_id = db.insert("projects", {"name": "Reviewer UX regression"})
        for uid, display_id, name in (
                (501, "PIPE-WELD-01", "Mainline welding Spread A"),
                (502, "PIPE-WELD-02", "Mainline welding Spread B")):
            db.insert("activities", {
                "project_id": project_id, "uid": uid, "display_id": display_id,
                "name": name, "wbs": "Pipeline.Construction.Welding",
                "status": "in_progress", "is_summary": 0,
            })
        db.ex("UPDATE activities SET baseline_start=?,baseline_finish=?,actual_start=?,"
              "actual_finish=?,percent_complete=? WHERE project_id=? AND uid=?",
              ["2026-07-01", "2026-08-03", "2026-07-08", "2026-08-03", 100,
               project_id, 501])
        db.ex("UPDATE activities SET baseline_start=?,baseline_finish=?,percent_complete=? "
              "WHERE project_id=? AND uid=?",
              ["2026-08-01", "2026-09-15", 20, project_id, 502])

        hinglish = field_capture.interpret(project_id, {
            "text": "Spread A me 4 joints welding complete ho gaya, 100%",
            "occurred_at": "2026-08-03T10:00",
        })
        check(hinglish["draft"]["event_state"] == "finish", hinglish)
        typo = field_capture.interpret(project_id, {
            "text": "Spread A 4 joints welding complet ho gya, 100%",
            "occurred_at": "2026-08-03T10:00",
        })
        check(typo["draft"]["event_state"] == "finish", typo)
        remaining = field_capture.interpret(project_id, {
            "text": "PIPE-WELD-01 par kaam shuru, 2 din baki",
            "occurred_at": "2026-08-03T10:00",
        })
        check(remaining["draft"]["event_state"] == "start", remaining)
        check(remaining["draft"]["remaining_days"] == 2.0, remaining)
        with mock.patch("veda.pipeline.field_capture._local_language_pass",
                        new=mock.AsyncMock(side_effect=AssertionError("common note must stay instant"))):
            instant = asyncio.run(field_capture.interpret_adaptive(project_id, {
                "text": "Spread A welding completed, 100%", "language": "en",
                "occurred_at": "2026-08-03T10:00", "adaptive_language": True,
            }))
        check(instant["language_interpretation"]["mode"] == "deterministic", instant)

        adaptive_payload = {
            "event_state": "finish", "action": "cable_pull",
            "normalized_activity_description": "Cable pulling for P-101",
            "observed_progress": 100, "remaining_days": 0, "quantity": None,
            "unit": None, "location_label": "Spread A", "asset_tags": ["P-101"],
            "confidence": .88, "language_note": "Uncommon Hinglish normalized",
        }
        with mock.patch("veda.pipeline.field_capture._local_language_pass",
                        new=mock.AsyncMock(return_value=(adaptive_payload, None))), \
                mock.patch("veda.pipeline.field_capture._candidate_rows", return_value=[]):
            adaptive = asyncio.run(field_capture.interpret_adaptive(project_id, {
                "text": "Spread A P-101 ka uncommon kaam ho gaya", "language": "hi-IN",
                "occurred_at": "2026-08-03T10:00", "adaptive_language": True,
            }))
        check(adaptive["language_interpretation"]["mode"] == "adaptive_local", adaptive)
        check(adaptive["draft"]["action"] == "cable_pull", adaptive)

        evidence_id = db.insert("evidence", {
            "project_id": project_id, "source_file": "DPR-2026-08-03.xlsx",
            "locator": "Welding!R18", "date": "2026-08-03",
            "description": "Spread A me 4 joints welding complete ho gaya",
            "activity_description": "Mainline welding Spread A",
            "document_type": "dpr", "observation_type": "activity_progress",
            "extraction_method": "typed_register", "extraction_confidence": 0.94,
            "security_state": "clean", "state": "needs_review",
        })
        review = {"kind": "clarification", "options": ["Spread A", "Spread B"],
                  "context": {"option_uids": {"Spread A": 501, "Spread B": 502}}}
        component_features = {
            "rerank": .91, "dense": .82, "sparse": .88, "asset_exact": 1.0,
            "action": .95, "phase": .9, "location": 1.0, "wbs": .86,
            "discipline": 1.0, "temporal": .8, "date_corroboration": .75,
            "graph": .7, "driving_pred_ready": .8, "relationship_consistency": .7,
            "source_trust": .8, "historical_sequence": .72,
        }
        for uid, probability, score in ((501, .87, .90), (502, .72, .76)):
            db.insert("evidence_links", {
                "project_id": project_id, "evidence_id": evidence_id,
                "activity_uid": uid, "activity_name": "candidate",
                "rank_score": score, "calibrated_probability": probability,
                "calibration_is_empirical": 1, "feature_json": db.jdumps(component_features),
                "supporting_signals": db.jdumps(["location agrees"]),
                "conflicting_signals": db.jdumps([]), "is_candidate": 1,
            })
            db.insert("evidence_links", {
                "project_id": project_id, "evidence_id": evidence_id,
                "activity_uid": uid, "activity_name": "confirmed multi-activity scope",
                "confidence": .91, "relation": "part_of", "is_candidate": 0,
                "human_decision": "accepted",
            })
        db.insert("execution_events", {
            "project_id": project_id, "activity_uid": 501,
            "event_state": "finish", "event_date": "2026-08-03",
            "observed_progress": 100, "quantity": 4, "unit": "joints",
            "confidence": .94, "source_count": 1, "state": "confirmed",
        })
        db.insert("relationships", {
            "project_id": project_id, "pred_uid": 501, "succ_uid": 502,
            "pred_name": "Mainline welding Spread A",
            "succ_name": "Mainline welding Spread B", "type": "FS",
            "lag_days": 0, "driving": 1,
        })
        explained = routes._review_candidate_explanations(project_id, review, [evidence_id])
        check(len(explained) == 2 and len(explained[0]["score_components"]) == 8, explained)
        check(explained[0]["review_band"] == "strong" and not explained[0]["ambiguous"], explained)
        db.ex("UPDATE evidence_links SET calibrated_probability=? "
              "WHERE evidence_id=? AND activity_uid=? AND is_candidate=1", [.81, evidence_id, 501])
        db.ex("UPDATE evidence_links SET calibrated_probability=? "
              "WHERE evidence_id=? AND activity_uid=? AND is_candidate=1", [.75, evidence_id, 502])
        ambiguous = routes._review_candidate_explanations(project_id, review, [evidence_id])
        check(ambiguous[0]["review_band"] == "review" and ambiguous[0]["ambiguous"], ambiguous)

        fake_candidates = [{
            "activity": db.q1("SELECT * FROM activities WHERE project_id=? AND uid=501",
                              [project_id]),
            "score": .9, "features": component_features,
            "supporting": ["exact activity identifier"], "conflicting": [],
        }]
        with mock.patch("veda.retrieval.engine.hybrid_search", return_value={
                "candidates": fake_candidates, "diagnostics": {}}):
            packed = veda_server.t_grounded_search({
                "query": "What field evidence supports PIPE-WELD-01?", "limit": 8,
                "expand_graph": True,
            }, PROJECT_ID=project_id)
        body = json.loads(packed["content"][0]["text"])
        citations = {item["citation"] for item in body["context_items"]}
        check("activity:501" in citations and "evidence:" + evidence_id in citations, body)
        check(any(item["kind"] == "canonical_execution_event"
                  for item in body["context_items"]), body)
        check(any(item["kind"] == "schedule_relationship"
                  for item in body["context_items"]), body)
        evidence_item = next(item for item in body["context_items"]
                             if item["citation"] == "evidence:" + evidence_id)
        check(evidence_item["activity_uids"] == [501, 502], evidence_item)
        check(body["mode"] == "execution_evidence", body)

        insights = routes._control_room_insights(project_id, {
            "data_date": "2026-08-31", "status_date": "2026-08-31"})
        check(insights["activity_distribution"]["counts"] == {
            "completed": 1, "in_progress": 1, "not_started": 0, "not_evaluable": 0,
        }, insights)
        trajectory = insights["completion_trajectory"]
        check(trajectory["reference_coverage"] == 2 and
              trajectory["recorded_finish_coverage"] == 1 and
              trajectory["verified_finish_coverage"] == 1, trajectory)

        views = (ROOT / "veda" / "web" / "views.js").read_text(encoding="utf-8")
        capture = (ROOT / "veda" / "web" / "field-capture.js").read_text(encoding="utf-8")
        vision = (ROOT / "veda" / "web" / "vision-tracker.js").read_text(encoding="utf-8")
        app = (ROOT / "veda" / "web" / "app.js").read_text(encoding="utf-8")
        overlay = (ROOT / "extension" / "content" / "overlay.js").read_text(encoding="utf-8")
        check("review-queue-shell" in views and "score-components" in views, "review workstation missing")
        check("completionTrajectoryCard" in views and "activityDistributionCard" in views,
              "control-room visuals missing")
        check("const text = el('capture-confirmed').value.trim();" in capture,
              "voice extraction must use the corrected transcript")
        check("invalidateExtraction('Re-extract corrected transcript')" in capture,
              "transcript edits must invalidate stale extraction")
        check("recognition.start(track)" in capture and "capture-microphone" in capture,
              "voice transcription must follow the selected microphone when supported")
        check("id=\"capture-cctv\"" in views and "CCTV_1.mp4" in views and
              "CCTV_2.mp4" in views and "data-cctv-observation" in views and
              "data-capture-cctv-mode=\"raw\"" in views,
              "CCTV footage review workstation is missing")
        check("useCctvObservation" in capture and "await interpretEvent(projectId)" in capture and
              "Local CCTV observation; human verification required." in capture,
              "CCTV observations must enter the governed editable capture flow")
        check("visual progress is estimated at ' + progress + '%. Work remains." in capture and
              "if (progressRadio) progressRadio.checked = true;" in capture,
              "CCTV percentages below 100 must remain progress events")
        check("hasUnsavedState" in capture and "const captureBusy = S.view === 'capture'" in app,
              "live refreshes must not erase an in-progress CCTV or field draft")
        check("siteVisionDashboard" in views and "LiveCamera_1.mp4" in views and
              "id=\"site-worker-scan\"" in views and "id=\"site-worker-share\"" in views,
              "dashboard Site Vision and worker-upload review are missing")
        check("window.VisionTracks" in vision and "requestAnimationFrame(loop)" in vision and
              "frameAt(payload" in vision and "data-model-track" in vision,
              "camera boxes must follow time-indexed model tracks during playback")
        check("Worker tracks use local pose detection" in views and
              "preconfigured against" not in views and "cctvBoxMarkup" not in capture,
              "static demo boxes must not be presented as live computer vision")
        for clip in ("CCTV_1", "CCTV_2", "LiveCamera_1"):
            track_path = ROOT / "veda" / "web" / "staticcams" / "detections" / f"{clip}.json"
            track_payload = json.loads(track_path.read_text(encoding="utf-8"))
            check(track_payload.get("schema") == "veda.vision.tracks.v1" and
                  track_payload.get("frames") and
                  any(frame.get("detections") for frame in track_payload["frames"]),
                  f"{clip} must have non-empty model-generated track data")
        cam3_path = ROOT / "veda" / "web" / "staticcams" / "detections" / "CCTV_2.json"
        cam3 = json.loads(cam3_path.read_text(encoding="utf-8"))
        check(cam3.get("sample_fps", 0) >= 3.5 and
              "pose + objects + temporal safety" in cam3.get("model", {}).get("name", ""),
              "CAM-03 must use the higher-rate local pose/object ensemble")
        for target in (4, 5, 6, 7, 8):
            frame = min(cam3["frames"], key=lambda item: abs(float(item["t"]) - target))
            check(any(item.get("class") == "worker" and item.get("basis") == "pose"
                      for item in frame.get("detections", [])),
                  f"CAM-03 worker pose track dropped around {target}s")
        check(any(68 <= float(frame["t"]) <= 71 and
                  any(item.get("class") == "suspended-load" and item.get("review_required")
                      for item in frame.get("detections", []))
                  for frame in cam3["frames"]),
              "CAM-03 hook must become a governed lifting-corridor candidate")
        scene_frames = sum(any(item.get("state") == "scene_memory" and item.get("w", 0) > 20
                               for item in frame.get("detections", []))
                           for frame in cam3["frames"])
        check(scene_frames >= len(cam3["frames"]) * .95,
              "CAM-03 parked vehicle must remain visible through fixed-camera scene memory")
        safety_events = cam3.get("events") or []
        check(len(safety_events) == 1 and 6 <= safety_events[0].get("t", 0) <= 10 and
              safety_events[0].get("status") == "needs_supervisor_review" and
              "not a confirmed incident" in safety_events[0].get("disclaimer", ""),
              "CAM-03 must surface one conservative, review-only near-miss candidate")
        check("id=\"site-safety-watch\"" in views and "Review moment" in views and
              "fixed_camera_scene_memory" in views and "camera_calibrated_lifting_corridor" in views,
              "dashboard safety review and explainable detector provenance are missing")
        check("veda-visual-capture-draft" in views and "consumeVisualCaptureDraft" in capture,
              "visual observations must hand off to governed field capture")
        check("hasActiveSiteVision" in views and "const siteVisionBusy = S.view === 'overview'" in app,
              "live refreshes must preserve camera playback and supervisor draft text")
        check("id=\"ask-voice\"" in views and "toggleVoiceInput" in overlay and
              "data-va-voice" in overlay,
              "Ask VEDA and VEDA Anywhere must expose draft voice input")
        print("review / voice correction / grounded retrieval regression: PASS")
    finally:
        db.close()
        TMP.cleanup()


if __name__ == "__main__":
    main()
