"""Agent-facing complexity router.

The router chooses which capabilities are worth invoking.  It never decides that
an activity is true and never changes the schedule; it only plans the cheapest
reasonable investigation path.
"""
from __future__ import annotations

from .events import classify_event
from .sequence import model_advice
from ..retrieval.entities import extract_asset_tags, extract_location_tags


def plan(project_id: str, evidence: dict, candidates: list[dict] | None = None) -> dict:
    info=classify_event(evidence)
    tags=extract_asset_tags(evidence.get("description"), evidence.get("raw_json"))
    locs=extract_location_tags(evidence.get("location"), evidence.get("description"), evidence.get("raw_json"))
    cands=candidates or []
    top=cands[0] if cands else None
    margin=(top or {}).get("features",{}).get("rank_margin",0.0) if top else 0.0
    tools=[]; reasons=[]; level=1
    if tags:
        tools.append("veda_entity_lookup"); reasons.append("engineering identifier present")
    tools.append("veda_activity_search")
    if len(cands)>=2 and margin < .12:
        level=max(level,2); tools += ["veda_activity_context","links_query"]
        reasons.append("top candidates are close; structured context can discriminate")
    if not locs:
        level=max(level,2); reasons.append("location missing or unstructured")
    if info["non_progress"]:
        reasons.append("non-progress/planned/blocker state detected; identity may be resolved but progress mutation must be suppressed")
    advice=model_advice()
    if level>=2 and advice["recommended_strategy"] != "association_rules":
        tools.append("veda_historical_sequence"); level=max(level,3)
    if len(cands)>=2 and margin < .05:
        tools += ["veda_activity_context","veda_read_file","veda_evidence"]; level=max(level,4)
        reasons.append("residual ambiguity warrants agent investigation")
    tools=list(dict.fromkeys(tools))
    return {"level":level,"event":info,"asset_tags":tags,"locations":locs,
            "recommended_tools":tools,"reasons":reasons,"sequence_model_advice":advice,
            "principle":"Use the minimum-cost reasoning path that resolves the ambiguity; human review remains valid output."}
