"""Reality-first execution-event model.

Field observations are not schedule activities.  They are evidence of execution
reality which may be finer/coarser than the current WBS, may contradict earlier
reports, may describe rework/removal/replacement, and may survive schedule
revisions.  This module preserves that reality before projecting it onto P6/MSP.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from .. import db
from ..retrieval.entities import (
    extract_asset_tags, asset_alias_set, extract_location_tags,
)
from .events import classify_event

REL_EXACT = "EXACT"
REL_PART_OF = "PART_OF"
REL_AGGREGATES = "AGGREGATES"
REL_SPLIT_ACROSS = "SPLIT_ACROSS"
REL_AMBIGUOUS = "AMBIGUOUS"
REL_NEW_SCOPE = "NEW_SCOPE"
REL_CORROBORATES = "CORROBORATES"
REL_CONTRADICTS = "CONTRADICTS"
REL_SUPERSEDES = "SUPERSEDES"

_REPLACE = re.compile(
    r"\b(?:replaced|replace|substituted|swapped)\b.*?\b(?:with|by)\b", re.I
)
_REMOVE = re.compile(r"\b(?:removed|dismantled|taken\s+out|pulled\s+out|de-installed|deinstalled)\b", re.I)
_REINSTALL = re.compile(r"\b(?:reinstalled|re-installed|installed\s+again|put\s+back|re-erected|reerected)\b", re.I)
_REPAIR = re.compile(r"\b(?:repaired|rectified|fixed|reworked|re-worked)\b", re.I)
_FAILURE = re.compile(r"\b(?:broke|broken|failed|failure|defect|damaged|rejected|leak(?:ed|ing)?)\b", re.I)
_CORRECTION = re.compile(r"\b(?:correction|corrected|supersedes|please\s+read\s+as|revised\s+entry|actually)\b", re.I)
_CALL_SOURCE = re.compile(r"\b(?:call|phone|whatsapp|walkie|radio|verbal)\b", re.I)


def _date(v: Any):
    if not v:
        return None
    try:
        return datetime.strptime(str(v).split("T")[0], "%Y-%m-%d").date()
    except Exception:
        return None


def _text(ev: dict) -> str:
    # Source filename/channel is provenance, not engineering content. Including
    # it in NER can create nonsense identifiers from timestamps or file codes.
    return " ".join(str(ev.get(k) or "") for k in ("description", "notes", "raw_json"))


def canonical_observation(ev: dict) -> dict:
    """Normalize one source observation without forcing a schedule identity."""
    text = _text(ev)
    info = classify_event(ev)
    entity_text = re.sub(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b", " ", text)
    tags = extract_asset_tags(entity_text, custom=ev.get("raw_json"))
    aliases = sorted(asset_alias_set(tags))
    locations = extract_location_tags(ev.get("location"), text, ev.get("raw_json"))

    # Rework/replacement semantics are execution facts rather than merely status.
    action = info.get("action")
    semantic_kind = "normal"
    if _REPLACE.search(text):
        action = "replacement"; semantic_kind = "replacement"
    elif _REINSTALL.search(text):
        action = "reinstallation"; semantic_kind = "reinstallation"
    elif _REMOVE.search(text):
        action = "removal"; semantic_kind = "removal"
    elif _REPAIR.search(text):
        action = "repair"; semantic_kind = "repair"

    replacement = None
    if semantic_kind == "replacement":
        parts=re.split(r"\b(?:with|by)\b", entity_text, maxsplit=1, flags=re.I)
        if len(parts)==2:
            left=extract_asset_tags(parts[0]); right=extract_asset_tags(parts[1])
            def ordered_tag(segment, items, last=False):
                up=segment.upper(); compact=re.sub(r"[^A-Z0-9]","",up); ranked=[]
                for item in items:
                    tag=str(item.get("tag") or "").upper(); pos=up.find(tag)
                    if pos<0:
                        ctag=re.sub(r"[^A-Z0-9]","",tag); pos=compact.find(ctag)
                    ranked.append((pos if pos>=0 else 10**9,tag))
                ranked=[x for x in ranked if x[0]<10**9]
                if not ranked: return None
                ranked.sort(); return ranked[-1][1] if last else ranked[0][1]
            if left and right:
                old=ordered_tag(parts[0],left,last=True); new=ordered_tag(parts[1],right,last=False)
                if old and new: replacement={"old_asset":old,"new_asset":new}
        if replacement is None and len(tags)>=2:
            replacement={"old_asset":tags[0]["tag"],"new_asset":tags[1]["tag"]}

    return {
        "observation_id": ev.get("id"),
        "date": ev.get("date"),
        "action": action,
        "state": info.get("state"),
        "event_info": info,
        "asset_tags": tags,
        "asset_aliases": aliases,
        "locations": locations,
        "discipline": ev.get("discipline"),
        "quantity": ev.get("quantity"),
        "unit": ev.get("unit"),
        "progress": info.get("progress"),
        "semantic_kind": semantic_kind,
        "replacement": replacement,
        "failure_or_rejection": bool(_FAILURE.search(text)),
        "is_correction": bool(_CORRECTION.search(text)) or info.get("state") == "correction",
        "informal_channel": bool(_CALL_SOURCE.search(text)),
        "raw_text": text.strip(),
        "source_file": ev.get("source_file"),
        "locator": ev.get("locator"),
    }


def canonical_key(obs: dict) -> str:
    assets = ",".join(sorted(str(x.get("tag") or "") for x in obs.get("asset_tags") or [])) or "NO_ASSET"
    loc = ",".join(sorted(obs.get("locations") or [])) or "NO_LOC"
    action = obs.get("action") or "observation"
    day = obs.get("date") or "NO_DATE"
    # State belongs in the key because complete -> rejected -> reworked -> complete
    # is a legitimate event cycle, not four duplicates.
    state = obs.get("state") or "observation"
    return f"{assets}|{action}|{state}|{loc}|{day}"


def _asset_set_from_candidate(c: dict) -> set[str]:
    meta = (c.get("features") or {}).get("activity_metadata") or {}
    vals = set(meta.get("asset_aliases") or [])
    if vals:
        return vals
    act = c.get("activity") or {}
    return asset_alias_set(extract_asset_tags(act.get("name"), act.get("custom_json"), act.get("wbs_path")))


def relation_hypothesis(project_id: str, ev: dict, candidates: list[dict]) -> dict:
    """Infer event->schedule relationship without forcing one-to-one identity."""
    obs = canonical_observation(ev)
    if not candidates:
        return {"relation": REL_NEW_SCOPE, "uids": [], "reason": "no schedule candidate", "observation": obs}

    # Explicit lineage hint used by imported historical evidence.  Old activity
    # identities may split/merge in later revisions.
    old_uid = ev.get("source_activity_uid") or ev.get("historical_activity_uid")
    if old_uid is not None:
        rows = db.q("SELECT to_uid,relation,score FROM activity_lineage WHERE project_id=? AND from_uid=? ORDER BY score DESC",
                    [project_id, old_uid])
        split = [int(r["to_uid"]) for r in rows if r.get("relation") == "split_candidate" and r.get("to_uid") is not None]
        if len(split) >= 2:
            return {"relation": REL_SPLIT_ACROSS, "uids": split, "reason": "historical activity split across current revision", "observation": obs}

    ev_alias = set(obs.get("asset_aliases") or [])
    top = candidates[0]
    top_alias = _asset_set_from_candidate(top)
    action = obs.get("action")

    # An explicit physical identifier absent from every plausible candidate is
    # much more likely to be new/unplanned scope than a fuzzy match to a random
    # similarly-worded activity. Keep this conservative: require an identity
    # conflict plus weak overall ranking.
    if ev_alias:
        overlaps=[bool(ev_alias & _asset_set_from_candidate(c)) for c in candidates[:8]]
        top_score=float(top.get("score") or 0.0)
        if not any(overlaps) and top_alias and top_score < .78:
            return {"relation": REL_NEW_SCOPE, "uids": [],
                    "reason": "explicit field asset is absent from candidate schedule identities", "observation": obs}

    # Multiple physical assets can legitimately summarize several L6 nodes.
    if len(obs.get("asset_tags") or []) > 1:
        hits = []
        for c in candidates:
            ca = _asset_set_from_candidate(c)
            if ev_alias & ca:
                hits.append(int(c["activity"]["uid"]))
        if len(set(hits)) >= 2:
            return {"relation": REL_AGGREGATES, "uids": list(dict.fromkeys(hits)),
                    "reason": "one field observation covers multiple asset-specific activities", "observation": obs}

    # A precise field asset linked to a coarser L5 task is PART_OF rather than
    # pretending the event and schedule activity have identical granularity.
    if ev_alias and not top_alias:
        return {"relation": REL_PART_OF, "uids": [int(top["activity"]["uid"])],
                "reason": "field event is more granular than schedule activity", "observation": obs}

    # Close semantically identical candidates without an identity anchor remain
    # an explicit candidate set; the graph/risk layer may still resolve them.
    if not ev_alias and len(candidates) >= 2:
        margin = float(top.get("score") or 0) - float(candidates[1].get("score") or 0)
        if margin < 0.035:
            return {"relation": REL_AMBIGUOUS,
                    "uids": [int(c["activity"]["uid"]) for c in candidates[:3]],
                    "reason": "no asset identity and several schedule nodes remain equivalent", "observation": obs}

    return {"relation": REL_EXACT, "uids": [int(top["activity"]["uid"])],
            "reason": "single schedule identity supported", "observation": obs}


def stream_events(observations: list[dict]) -> dict:
    """Build a small reality graph from longitudinal source observations.

    Used by the benchmark and available to the runtime for audit/explanation.
    It deliberately keeps correction/rework cycles instead of last-write-wins.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    by_key: dict[str, dict] = {}
    by_asset: defaultdict[str, list[dict]] = defaultdict(list)

    ordered = sorted(observations, key=lambda x: (str(x.get("date") or ""), str(x.get("time") or ""), str(x.get("id") or "")))
    for ev in ordered:
        obs = canonical_observation(ev)
        key = canonical_key(obs)
        if key in by_key:
            existing = by_key[key]
            existing.setdefault("sources", []).append(obs.get("observation_id"))
            edges.append({"type": REL_CORROBORATES, "from": obs.get("observation_id"), "to": existing["id"]})
            continue

        node = {
            "id": "rg:" + str(obs.get("observation_id") or len(nodes)+1),
            "key": key,
            **obs,
            "sources": [obs.get("observation_id")],
            "status": "observed",
        }
        nodes.append(node); by_key[key] = node

        tags = [str(x.get("tag") or "") for x in obs.get("asset_tags") or []]
        prior_candidates = []
        for tag in tags:
            prior_candidates.extend(by_asset[tag])

        # A later explicit correction/replacement/removal/rework supersedes the
        # previous interpretation but never deletes history.
        if prior_candidates and (obs.get("is_correction") or obs.get("semantic_kind") in {"replacement","removal","reinstallation","repair"}):
            prior = prior_candidates[-1]
            edges.append({"type": REL_SUPERSEDES, "from": node["id"], "to": prior["id"],
                          "reason": obs.get("semantic_kind")})
            prior["status"] = "superseded"

        # Same physical identity/action/location with incompatible states is a
        # contradiction unless the later record explicitly declares correction.
        for prior in prior_candidates[-4:]:
            same_action = prior.get("action") == obs.get("action")
            same_loc = bool(set(prior.get("locations") or []) & set(obs.get("locations") or [])) or (not prior.get("locations") and not obs.get("locations"))
            states={prior.get("state"),obs.get("state")}
            neg={"blocked","no_progress","cancelled"}
            if obs.get("state")=="mixed" and obs.get("failure_or_rejection"): neg.add("mixed")
            incompatible = bool(states & {"finish"} and states & neg)
            if same_action and same_loc and incompatible and not obs.get("is_correction"):
                edges.append({"type": REL_CONTRADICTS, "from": node["id"], "to": prior["id"]})
                node["status"] = "conflicting"; prior["status"] = "conflicting"

        for tag in tags:
            by_asset[tag].append(node)

    return {
        "events": nodes,
        "edges": edges,
        "summary": {
            "observations": len(observations),
            "canonical_events": len(nodes),
            "corroborations": sum(1 for e in edges if e["type"] == REL_CORROBORATES),
            "contradictions": sum(1 for e in edges if e["type"] == REL_CONTRADICTS),
            "supersessions": sum(1 for e in edges if e["type"] == REL_SUPERSEDES),
        },
    }


def persist_relation(project_id: str, execution_event_id: str, relation: dict) -> None:
    """Persist set-valued event-to-schedule relations for audit/memory."""
    for uid in relation.get("uids") or [None]:
        db.insert("execution_event_links", {
            "project_id": project_id,
            "execution_event_id": execution_event_id,
            "activity_uid": uid,
            "relation": relation.get("relation") or REL_AMBIGUOUS,
            "confidence": relation.get("confidence"),
            "basis": relation.get("reason"),
            "created_at": db.now(),
        })
