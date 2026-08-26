"""Hybrid, metadata-aware schedule activity retrieval.

Pipeline:
  engineering entity extraction -> progressive metadata candidate narrowing ->
  BM25 + dense retrieval -> reciprocal-rank fusion -> optional BGE-M3
  late-interaction rerank -> schedule/WBS/temporal/graph features.

The output is candidate identity evidence only. Validators and the review policy
remain the authority for accepting a link.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from .. import db
from . import embeddings
from .entities import (asset_alias_set, event_types, extract_asset_tags,
                       extract_location_tags, primary_event_type)

STOP = {"the", "and", "for", "with", "of", "to", "in", "on", "at", "a", "an",
        "works", "work", "site", "no", "nos", "shift", "day", "daily", "progress",
        "report", "section", "from", "as", "per", "is", "was", "were", "has", "have"}


def _tokens(text: str | None) -> list[str]:
    if not text:
        return []
    raw = re.findall(r"[a-z0-9][a-z0-9_./:-]*", str(text).lower())
    out = []
    for w in raw:
        compact = re.sub(r"[-_/.:]", "", w)
        if len(compact) > 2 and compact not in STOP:
            out.append(w)
            if compact != w and len(compact) > 2:
                out.append(compact)
    return out


def _d(v: Any):
    if not v:
        return None
    try:
        return datetime.strptime(str(v).split("T")[0], "%Y-%m-%d").date()
    except ValueError:
        return None


def _json(v: Any, default):
    if v in (None, ""):
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(str(v))
    except Exception:
        return default


def _custom_text(custom: Any) -> str:
    obj = _json(custom, {})
    vals = []
    def walk(x: Any, key: str = ""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, str(k))
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v, key)
        elif x not in (None, "") and re.search(
                r"tag|asset|equip|line|spool|loop|cable|drawing|dwg|iso|system|subsystem|package|area|location|unit",
                key, re.I):
            vals.append(str(x))
    walk(obj)
    return " ".join(vals[:40])


def build_activity_document(act: dict, network_context: dict | None = None) -> tuple[str, dict]:
    custom = _json(act.get("custom_json"), {})
    tags = _json(act.get("asset_tags_json"), None)
    if tags is None:
        tags = extract_asset_tags(act.get("display_id"), act.get("name"), act.get("notes"),
                                  act.get("wbs_path"), custom=custom)
    locs = _json(act.get("location_tags_json"), None)
    if locs is None:
        locs = extract_location_tags(act.get("name"), act.get("wbs_path"), act.get("wbs_name"),
                                     act.get("notes"), _custom_text(custom))
    tag_text = " ".join(t.get("tag", "") if isinstance(t, dict) else str(t) for t in tags)
    parts = [
        "Activity ID: " + str(act.get("display_id") or act.get("uid") or ""),
        "Activity: " + str(act.get("name") or ""),
        "WBS code: " + str(act.get("wbs") or ""),
        "WBS path: " + str(act.get("wbs_path") or ""),
        "WBS node: " + str(act.get("wbs_name") or ""),
        "Engineering tags: " + tag_text,
        "Location: " + " ".join(locs),
        "Status: " + str(act.get("status") or ""),
        "Notes: " + str(act.get("notes") or ""),
        "Custom: " + _custom_text(custom),
        "Predecessors: " + "; ".join((network_context or {}).get("predecessors") or []),
        "Successors: " + "; ".join((network_context or {}).get("successors") or []),
    ]
    text = "\n".join(p for p in parts if p.split(":", 1)[-1].strip())
    meta = {"asset_tags": tags, "asset_aliases": sorted(asset_alias_set(tags)),
            "location_tags": locs, "event_types": event_types(act.get("name")),
            "wbs": act.get("wbs"), "wbs_path": act.get("wbs_path"),
            "status": act.get("status"), "network_context": network_context or {}}
    return text, meta


def _fingerprint(text: str, meta: dict, model: str) -> str:
    payload = text + "\n" + json.dumps(meta, sort_keys=True, default=str) + "\n" + model
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def index_project(project_id: str, force: bool = False) -> dict:
    backend = embeddings.get_backend()
    acts = db.q("SELECT * FROM activities WHERE project_id=? AND is_summary=0", [project_id])
    existing = {int(r["activity_uid"]): r for r in db.q(
        "SELECT * FROM retrieval_documents WHERE project_id=?", [project_id])
        if r.get("activity_uid") is not None}
    pending = []
    keep = set()
    network: dict[int, dict[str, list[str]]] = defaultdict(lambda: {"predecessors": [], "successors": []})
    for rel in db.q("SELECT pred_uid,pred_name,succ_uid,succ_name,type,lag_days,driving FROM relationships WHERE project_id=?", [project_id]):
        puid, suid = rel.get("pred_uid"), rel.get("succ_uid")
        typ = str(rel.get("type") or "FS")
        lag = float(rel.get("lag_days") or 0.0)
        suffix = f" [{typ}{lag:+g}d" + (", driving" if rel.get("driving") else "") + "]"
        if suid is not None and puid is not None:
            network[int(suid)]["predecessors"].append(str(rel.get("pred_name") or puid) + suffix)
            network[int(puid)]["successors"].append(str(rel.get("succ_name") or suid) + suffix)
    for act in acts:
        uid = int(act["uid"])
        keep.add(uid)
        nctx = {k: v[:5] for k, v in network.get(uid, {}).items()} if uid in network else None
        text, meta = build_activity_document(act, nctx)
        fp = _fingerprint(text, meta, backend.name)
        old = existing.get(uid)
        if force or not old or old.get("fingerprint") != fp:
            pending.append((act, text, meta, fp))
    if pending:
        # Chunk indexing so a large P6 schedule does not hold every 1024-d vector
        # in memory at once. FlagEmbedding still batches internally; this bounds
        # VEDA's own peak memory and makes revision re-indexing predictable.
        chunk_size = 512
        for pos in range(0, len(pending), chunk_size):
            chunk = pending[pos:pos + chunk_size]
            vecs = backend.encode([x[1] for x in chunk])
            for (act, text, meta, fp), vec in zip(chunk, vecs):
                old = existing.get(int(act["uid"]))
                row = {"project_id": project_id, "activity_uid": int(act["uid"]),
                       "fingerprint": fp, "search_text": text,
                       "embedding_model": backend.name, "embedding_dim": len(vec),
                       "embedding_blob": embeddings.pack_vector(vec),
                       "metadata_json": db.jdumps(meta), "updated_at": db.now()}
                if old:
                    db.ex("UPDATE retrieval_documents SET fingerprint=?,search_text=?,embedding_model=?,"
                          "embedding_dim=?,embedding_blob=?,metadata_json=?,updated_at=? WHERE id=?",
                          [row["fingerprint"], row["search_text"], row["embedding_model"],
                           row["embedding_dim"], row["embedding_blob"], row["metadata_json"],
                           row["updated_at"], old["id"]])
                else:
                    db.insert("retrieval_documents", row)
    stale = [uid for uid in existing if uid not in keep]
    if stale:
        ph = ",".join("?" for _ in stale)
        db.ex("DELETE FROM retrieval_documents WHERE project_id=? AND activity_uid IN (" + ph + ")",
              [project_id] + stale)
    return {"activities": len(acts), "indexed": len(pending), "removed": len(stale),
            "embedding_backend": backend.name}


def _evidence_query(ev: dict) -> dict:
    desc = str(ev.get("description") or "")
    raw = _json(ev.get("raw_json"), {})
    tags = _json(ev.get("asset_tags_json"), None)
    if tags is None:
        tags = extract_asset_tags(desc, ev.get("location"), ev.get("discipline"), custom=raw)
    locs = _json(ev.get("location_tags_json"), None)
    if locs is None:
        locs = extract_location_tags(ev.get("location"), desc, raw)
    event = ev.get("event_type") or primary_event_type(desc)
    query = "\n".join([
        "Field report: " + desc,
        "Discipline: " + str(ev.get("discipline") or ""),
        "Location: " + str(ev.get("location") or "") + " " + " ".join(locs),
        "Engineering tags: " + " ".join(t.get("tag", "") if isinstance(t, dict) else str(t) for t in tags),
        "Event: " + str(event or ""),
    ])
    return {"text": query, "asset_tags": tags, "asset_aliases": asset_alias_set(tags),
            "location_tags": set(locs), "event_type": event,
            "discipline": str(ev.get("discipline") or "").strip().lower(),
            "date": _d(ev.get("date"))}


def _discipline(act: dict) -> str | None:
    # Reuse the mature validator dictionary without creating a module cycle at import time.
    from ..pipeline.validators import discipline_key
    return discipline_key(" ".join(str(act.get(k) or "") for k in ("name", "wbs_name", "wbs_path")))


def _context_wbs_priors(project_id: str, ev: dict) -> Counter:
    """Learn repeated crew/contractor/source attribution from human-confirmed links."""
    clauses, params = [], [project_id]
    for col in ("crew", "contractor", "source_file"):
        val = str(ev.get(col) or "").strip()
        if val:
            clauses.append("e." + col + "=?")
            params.append(val)
    if not clauses:
        return Counter()
    rows = db.q(
        "SELECT a.wbs FROM evidence_links l JOIN evidence e ON e.id=l.evidence_id "
        "JOIN activities a ON a.project_id=l.project_id AND a.uid=l.activity_uid "
        "WHERE l.project_id=? AND l.human_decision='accepted' AND (" + " OR ".join(clauses) + ")",
        params,
    )
    c = Counter()
    for r in rows:
        w = str(r.get("wbs") or "")
        if w:
            parts = re.split(r"[./>]", w)
            for n in range(1, min(len(parts), 4) + 1):
                c[".".join(parts[:n])] += 1
    return c


def _metadata_candidates(project_id: str, ev: dict, docs: list[dict]) -> tuple[list[dict], dict]:
    q = _evidence_query(ev)
    priors = _context_wbs_priors(project_id, ev)
    all_docs = docs
    diagnostics = {"initial": len(all_docs), "filters": [], "query": {
        "asset_tags": sorted(q["asset_aliases"]), "location_tags": sorted(q["location_tags"]),
        "discipline": q["discipline"], "event_type": q["event_type"],
        "date": q["date"].isoformat() if q["date"] else None}}

    # Exact physical identifiers are the strongest anchor, but granularity
    # mismatch is normal: a DPR may cite spool P-1043 while the schedule only has
    # a generic "Area B piping erection" task. Expand exact hits through one-hop
    # schedule relationships and WBS siblings before narrowing. Document/control
    # refs (ISO/RFI/NCR...) stay soft because they frequently belong to supporting
    # evidence rather than the executable task itself.
    physical_aliases = set()
    for item in q.get("asset_tags") or []:
        if not isinstance(item, dict) or item.get("type") != "document":
            from .entities import tag_aliases
            physical_aliases.update(tag_aliases(item.get("tag") if isinstance(item, dict) else str(item)))
    if physical_aliases:
        anchored = []
        for d in all_docs:
            meta = _json(d.get("metadata_json"), {})
            if physical_aliases & set(meta.get("asset_aliases") or []):
                anchored.append(d)
        if anchored:
            anchor_uids = {int(d["uid"]) for d in anchored if d.get("uid") is not None}
            expanded_uids = set(anchor_uids)
            if anchor_uids:
                ph = ",".join("?" for _ in anchor_uids)
                rels = db.q("SELECT pred_uid,succ_uid FROM relationships WHERE project_id=? "
                            "AND (pred_uid IN (" + ph + ") OR succ_uid IN (" + ph + "))",
                            [project_id] + list(anchor_uids) + list(anchor_uids))
                for r in rels:
                    if r.get("pred_uid") is not None: expanded_uids.add(int(r["pred_uid"]))
                    if r.get("succ_uid") is not None: expanded_uids.add(int(r["succ_uid"]))
            # Add siblings under the nearest WBS parent; this catches L6 field
            # detail mapped to a coarser L5 work package.
            prefixes = set()
            for d in anchored:
                w = str(d.get("wbs") or "")
                if "." in w: prefixes.add(w.rsplit(".", 1)[0])
            expanded = [d for d in all_docs if int(d.get("uid") or -1) in expanded_uids or
                        any(str(d.get("wbs") or "").startswith(p + ".") for p in prefixes)]
            # Avoid turning a top-level WBS prefix into a near-full scan.
            if expanded and len(expanded) <= max(250, len(anchored) * 20):
                diagnostics["filters"].append({"name": "asset_anchor_plus_graph_wbs",
                                               "before": len(all_docs), "exact": len(anchored),
                                               "after": len(expanded)})
                all_docs = expanded

    # Progressive 'should' filtering. Apply only when it reduces a still-large
    # pool and leaves enough alternatives for ambiguity detection.
    def maybe_filter(name, pred, min_keep=6):
        nonlocal all_docs
        if len(all_docs) <= min_keep:
            return
        hit = [d for d in all_docs if pred(d)]
        if len(hit) >= min_keep and len(hit) < len(all_docs):
            diagnostics["filters"].append({"name": name, "before": len(all_docs), "after": len(hit)})
            all_docs = hit

    if q["location_tags"]:
        maybe_filter("location", lambda d: bool(q["location_tags"] & set(_json(d.get("metadata_json"), {}).get("location_tags") or [])))

    qdisc = None
    from ..pipeline.validators import discipline_key
    qdisc = discipline_key(ev.get("discipline")) or discipline_key(ev.get("description"))
    if qdisc:
        maybe_filter("discipline", lambda d: _discipline(d) == qdisc)

    if q.get("event_type") and q["event_type"] not in ("start", "finish"):
        maybe_filter("event_type", lambda d: q["event_type"] in set(_json(d.get("metadata_json"), {}).get("event_types") or []), min_keep=6)

    if q["date"]:
        def in_temporal_neighborhood(d):
            s = _d(d.get("actual_start") or d.get("start") or d.get("baseline_start"))
            f = _d(d.get("actual_finish") or d.get("finish") or d.get("baseline_finish"))
            if not s and not f:
                return True
            lo = (s or f) - timedelta(days=75)
            hi = (f or s) + timedelta(days=120)
            return lo <= q["date"] <= hi
        maybe_filter("temporal_neighborhood", in_temporal_neighborhood, min_keep=10)

    if priors and len(all_docs) > 8:
        top_prefixes = {p for p, n in priors.most_common(4) if n >= 2}
        if top_prefixes:
            maybe_filter("human_confirmed_wbs_prior",
                         lambda d: any(str(d.get("wbs") or "").startswith(p) for p in top_prefixes), min_keep=6)
            diagnostics["wbs_priors"] = priors.most_common(6)

    diagnostics["final"] = len(all_docs)
    return all_docs, diagnostics


def _bm25(query_tokens: list[str], docs_tokens: list[list[str]]) -> list[float]:
    if not docs_tokens:
        return []
    n = len(docs_tokens)
    avgdl = sum(len(d) for d in docs_tokens) / max(1, n)
    df = Counter()
    for d in docs_tokens:
        df.update(set(d))
    k1, b = 1.5, 0.72
    scores = []
    for d in docs_tokens:
        tf = Counter(d)
        s = 0.0
        for term in set(query_tokens):
            if not tf.get(term):
                continue
            idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
            f = tf[term]
            denom = f + k1 * (1 - b + b * len(d) / max(avgdl, 1e-6))
            s += idf * (f * (k1 + 1) / denom)
        scores.append(s)
    return scores


def _rank(values: list[float], reverse: bool = True) -> dict[int, int]:
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=reverse)
    return {idx: r + 1 for r, idx in enumerate(order)}


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.0 if hi == 0 else 1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _temporal_features(ev: dict, act: dict, event: str | None) -> tuple[float, list[str], list[str]]:
    ed = _d(ev.get("date"))
    if not ed:
        return 0.5, [], []
    actual_s, actual_f = _d(act.get("actual_start")), _d(act.get("actual_finish"))
    plan_s = _d(act.get("start") or act.get("baseline_start"))
    plan_f = _d(act.get("finish") or act.get("baseline_finish"))
    support, conflict = [], []

    # Actuals, when already recorded, are stronger evidence than plan dates.
    anchor = None
    if event in ("finish", "erection", "welding", "ndt", "hydrotest", "alignment", "termination", "calibration", "commissioning"):
        anchor = actual_f or plan_f
    elif event == "start":
        anchor = actual_s or plan_s
    if anchor:
        days = abs((ed - anchor).days)
        scale = 20.0 if (actual_s or actual_f) else 45.0
        score = math.exp(-days / scale)
        if days <= 7:
            support.append("event date close to " + ("actual" if (actual_s or actual_f) else "planned") + " boundary")
        elif days > 90 and (actual_s or actual_f):
            conflict.append("event date far from recorded actual boundary")
        return max(0.05, min(1.0, score)), support, conflict

    s, f = actual_s or plan_s, actual_f or plan_f
    if s and f:
        if s - timedelta(days=14) <= ed <= f + timedelta(days=21):
            return 0.9, ["date within/near activity execution window"], []
        dist = min(abs((ed - s).days), abs((ed - f).days))
        score = max(0.08, math.exp(-dist / 60.0))
        if dist > 90:
            conflict.append("date remote from activity window")
        return score, support, conflict
    return 0.5, support, conflict



def _out_of_sequence_mode(project_id: str) -> str | None:
    snap = db.q1("SELECT info_json FROM schedule_snapshots WHERE project_id=? AND is_current=1 ORDER BY created_at DESC LIMIT 1", [project_id])
    obj = _json((snap or {}).get("info_json"), {})
    wanted = {"outofsequencescheduletype", "out_of_sequence_schedule_type", "outofsequencelogic",
              "out_of_sequence_logic", "progressedactivitylogic", "schedulelogic"}
    found = None
    def walk(x: Any):
        nonlocal found
        if found is not None: return
        if isinstance(x, dict):
            for k, v in x.items():
                nk = re.sub(r"[^a-z_]", "", str(k).lower())
                compact = nk.replace("_", "")
                if nk in wanted or compact in {w.replace("_", "") for w in wanted}:
                    sval = str(v or "").strip()
                    if sval: found = sval
                    return
                walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(obj)
    if not found: return None
    low = found.lower()
    if "override" in low: return "Progress Override"
    if "retain" in low: return "Retained Logic"
    if "actual" in low and "date" in low: return "Actual Dates"
    return found

def _graph_features(project_id: str, ev: dict, act: dict) -> tuple[float, list[str], list[str], dict]:
    """Relationship-aware execution plausibility.

    FS/SS/FF/SF and lag are handled differently.  This is intentionally a soft
    feature: construction can proceed out of sequence and schedules can be stale.
    """
    uid = act.get("uid")
    if uid is None:
        return 0.5, [], [], {}
    rels = db.q("SELECT * FROM relationships WHERE project_id=? AND (pred_uid=? OR succ_uid=?)",
                [project_id, uid, uid])
    if not rels:
        return 0.5, [], [], {"relationship_count": 0}
    pred_rels = [r for r in rels if r.get("succ_uid") == uid and r.get("pred_uid") is not None]
    succ_rels = [r for r in rels if r.get("pred_uid") == uid and r.get("succ_uid") is not None]
    related = list(dict.fromkeys([r.get("pred_uid") for r in pred_rels] +
                                 [r.get("succ_uid") for r in succ_rels]))
    rows = {}
    if related:
        ph = ",".join("?" for _ in related)
        rows = {r["uid"]: r for r in db.q(
            "SELECT uid,status,actual_start,actual_finish,start,finish FROM activities "
            "WHERE project_id=? AND uid IN (" + ph + ")", [project_id] + related)}
    ed = _d(ev.get("date"))
    logic_mode = _out_of_sequence_mode(project_id)

    def readiness(rel: dict) -> float:
        p = rows.get(rel.get("pred_uid"), {})
        typ = str(rel.get("type") or "FS").upper().replace("_", "")[:2]
        lag = float(rel.get("lag_days") or 0.0)
        if typ in ("SS", "SF"):
            actual = _d(p.get("actual_start"))
            planned = _d(p.get("start"))
            status_ok = p.get("status") in ("in_progress", "complete") or bool(actual)
        else:  # FS / FF depend primarily on predecessor finish
            actual = _d(p.get("actual_finish"))
            planned = _d(p.get("finish"))
            status_ok = p.get("status") == "complete" or bool(actual)
        if ed:
            threshold = ed - timedelta(days=lag)
            if actual:
                return 1.0 if actual <= threshold else 0.20
            if status_ok:
                return 0.88
            if planned and planned <= threshold:
                # Plan says the predecessor should have cleared, but no actual is
                # recorded. Useful context, not proof.
                return 0.62
            return 0.16
        if status_ok:
            return 0.92
        if p.get("status") == "in_progress":
            return 0.52
        return 0.20

    weighted = []
    for rel in pred_rels:
        w = 1.25 if rel.get("driving") else 1.0
        weighted.append((readiness(rel), w))
    pred_ready = (sum(v*w for v, w in weighted) / sum(w for _, w in weighted)) if weighted else 0.75
    support, conflict = [], []
    if pred_rels and pred_ready >= 0.8:
        support.append("relationship-aware predecessor readiness is high")
    elif pred_rels and pred_ready < 0.35:
        if logic_mode == "Progress Override":
            support.append("out-of-sequence progress is plausible under P6 Progress Override")
        else:
            conflict.append("predecessor logic is not yet satisfied; possible out-of-sequence work")

    successor_advanced = 0
    if ed:
        for rel in succ_rels:
            srow = rows.get(rel.get("succ_uid"), {})
            d = _d(srow.get("actual_start") or srow.get("actual_finish"))
            if d and d <= ed:
                successor_advanced += 1
    score = 0.25 + 0.65 * pred_ready
    if logic_mode == "Progress Override" and pred_rels:
        score = max(score, 0.48)
    elif logic_mode == "Retained Logic" and pred_rels and pred_ready < 0.35:
        score = max(0.12, score - 0.06)
    if successor_advanced:
        score = min(1.0, score + 0.08)
        support.append("successor activity has already advanced")
    return score, support, conflict, {
        "relationship_count": len(rels), "predecessors": len(pred_rels),
        "predecessor_readiness": round(pred_ready, 3), "successors": len(succ_rels),
        "successors_advanced": successor_advanced,
        "driving_predecessors": sum(1 for r in pred_rels if r.get("driving")),
        "out_of_sequence_mode": logic_mode,
    }



def _date_corroboration(project_id: str, ev: dict, q: dict) -> tuple[float, list[str], list[str], dict]:
    """Cross-check an observed event date against independent contemporaneous evidence.

    Planned dates answer when work *should* happen; corroborating daily/diary/log
    records answer when it *did* happen.  This signal is intentionally soft
    because one line/area can contain repeated events over several days.
    """
    ed = q.get("date")
    if not ed:
        return 0.5, [], [], {"independent_sources": 0}
    rows = db.q(
        "SELECT id,file_id,source_file,date,description,asset_tags_json,location_tags_json,event_type "
        "FROM evidence WHERE project_id=? AND date IS NOT NULL AND id<>?",
        [project_id, ev.get("id") or ""],
    )
    qaliases = set(q.get("asset_aliases") or [])
    qloc = set(q.get("location_tags") or [])
    qevent = q.get("event_type")
    near_sources, other_dates = set(), []
    relevant = 0
    for r in rows:
        rd = _d(r.get("date"))
        if not rd:
            continue
        rtags = _json(r.get("asset_tags_json"), None)
        if rtags is None:
            rtags = extract_asset_tags(r.get("description"))
        raliases = asset_alias_set(rtags)
        rloc = set(_json(r.get("location_tags_json"), []) or extract_location_tags(r.get("description")))
        revent = r.get("event_type") or primary_event_type(r.get("description"))

        # Require an identity anchor. Exact asset is strongest; without a tag,
        # require both location and action to avoid correlating unrelated work.
        asset_hit = bool(qaliases and raliases and qaliases & raliases)
        context_hit = bool(not qaliases and qloc and (qloc & rloc) and qevent and revent == qevent)
        if not (asset_hit or context_hit):
            continue
        if qevent and revent and qevent != revent:
            continue
        relevant += 1
        delta = abs((rd - ed).days)
        source = str(r.get("file_id") or r.get("source_file") or r.get("id"))
        if delta <= 1:
            near_sources.add(source)
        elif delta <= 21:
            other_dates.append(delta)

    support, conflict = [], []
    nsrc = len(near_sources)
    if nsrc >= 2:
        score = 1.0
        support.append(f"event date corroborated by {nsrc} independent evidence sources")
    elif nsrc == 1:
        score = 0.82
        support.append("event date corroborated by another evidence source")
    elif other_dates:
        # Weak disagreement only: a line/equipment item may legitimately have
        # repeated erection/welding/inspection events across several days.
        score = max(0.28, 0.55 - min(other_dates) / 90.0)
        conflict.append("related contemporaneous evidence records a different event date")
    else:
        score = 0.5
    return score, support, conflict, {
        "independent_sources": nsrc, "related_records": relevant,
        "nearest_other_date_days": min(other_dates) if other_dates else None,
    }

def _signal_features(project_id: str, ev: dict, act: dict, meta: dict, q: dict) -> dict:
    from ..pipeline.validators import discipline_key, chainage_values, chainage_window
    ev_alias = q["asset_aliases"]
    act_alias = set(meta.get("asset_aliases") or [])
    tag_overlap = ev_alias & act_alias
    evloc = q["location_tags"]
    actloc = set(meta.get("location_tags") or [])
    loc_overlap = evloc & actloc
    evdisc = discipline_key(ev.get("discipline")) or discipline_key(ev.get("description"))
    adisc = _discipline(act)
    disc = 1.0 if evdisc and adisc and evdisc == adisc else 0.15 if evdisc and adisc and evdisc != adisc else 0.5

    ev_ch = chainage_values(str(ev.get("chainage") or "") + " " + str(ev.get("description") or ""))
    lo, hi = chainage_window(" ".join(str(act.get(k) or "") for k in ("name", "wbs_path", "wbs_name")))
    chain = 0.5
    if ev_ch and lo is not None:
        if hi is None:
            hi = lo
        chain = 1.0 if any(lo - 500 <= c <= hi + 500 for c in ev_ch) else 0.0

    temporal, tsup, tcon = _temporal_features(ev, act, q.get("event_type"))
    corroboration, csup, ccon, cdetail = _date_corroboration(project_id, ev, q)
    graph, gsup, gcon, gdetail = _graph_features(project_id, ev, act)
    # WBS context agreement is represented by location/tag/discipline matches in
    # the resolved path plus lexical overlap with the path itself.
    qtok = set(_tokens(q["text"]))
    wtok = set(_tokens(" ".join(str(act.get(k) or "") for k in ("wbs", "wbs_path", "wbs_name"))))
    wbs_overlap = len(qtok & wtok) / max(1, min(8, len(qtok)))
    wbs_score = min(1.0, 0.25 + 1.8 * wbs_overlap + (0.25 if loc_overlap else 0.0))
    return {
        "asset_exact": 1.0 if tag_overlap else 0.0,
        "asset_overlap_count": min(1.0, len(tag_overlap) / 2.0),
        "location": 1.0 if loc_overlap else 0.0 if evloc and actloc else 0.5,
        "discipline": disc,
        "chainage": chain,
        "temporal": temporal,
        "date_corroboration": corroboration,
        "graph": graph,
        "wbs": wbs_score,
        "supports": [*(['exact engineering tag: ' + ', '.join(sorted(tag_overlap)[:3])] if tag_overlap else []),
                     *(['location: ' + ', '.join(sorted(loc_overlap)[:3])] if loc_overlap else []),
                     *tsup, *csup, *gsup],
        "conflicts": [*tcon, *ccon, *gcon],
        "graph_detail": gdetail,
        "date_detail": cdetail,
    }


def _raw_score(f: dict) -> float:
    # Ranking model, not probability.  Exact engineering identity and semantic
    # reranking lead; graph/date metadata are strong context but cannot veto
    # legitimate out-of-sequence/late construction.
    score = (
        0.20 * f.get("rerank", 0.0) +
        0.14 * f.get("dense", 0.0) +
        0.11 * f.get("sparse", 0.0) +
        0.17 * f.get("asset_exact", 0.0) +
        0.06 * f.get("asset_overlap_count", 0.0) +
        0.07 * f.get("location", 0.5) +
        0.06 * f.get("discipline", 0.5) +
        0.06 * f.get("wbs", 0.5) +
        0.04 * f.get("temporal", 0.5) +
        0.03 * f.get("date_corroboration", 0.5) +
        0.04 * f.get("graph", 0.5) +
        0.02 * f.get("chainage", 0.5)
    )
    if f.get("agent_agreement"):
        # Agent judgement is corroboration, not a second probability added to
        # the system score.  The calibrated layer learns how trustworthy this
        # feature really is from human review outcomes.
        score += 0.04 * max(0.0, min(1.0, f.get("agent_confidence", 0.5)))
    return max(0.0, min(1.0, score))


def hybrid_search(project_id: str, ev: dict, top_k: int = 8,
                  agent_links: list[dict] | None = None) -> dict:
    index_info = index_project(project_id)
    docs = db.q(
        "SELECT d.*,a.* FROM retrieval_documents d JOIN activities a "
        "ON a.project_id=d.project_id AND a.uid=d.activity_uid "
        "WHERE d.project_id=? AND a.is_summary=0", [project_id])
    if not docs:
        return {"candidates": [], "diagnostics": {"index": index_info}}
    q = _evidence_query(ev)
    pool, diagnostics = _metadata_candidates(project_id, ev, docs)
    if not pool:
        pool = docs
    backend = embeddings.get_backend()
    qvec = backend.encode([q["text"]])[0]
    dense_raw = [embeddings.cosine(qvec, embeddings.unpack_vector(d.get("embedding_blob"))) for d in pool]
    dense_norm = _normalize(dense_raw)
    query_tokens = _tokens(q["text"])
    doc_tokens = [_tokens(d.get("search_text")) for d in pool]
    sparse_raw = _bm25(query_tokens, doc_tokens)
    sparse_norm = _normalize(sparse_raw)
    dr, sr = _rank(dense_raw), _rank(sparse_raw)
    rrf = [1 / (60 + dr[i]) + 1 / (60 + sr[i]) for i in range(len(pool))]
    # Add exact tag ranking as a third retrieval channel when available.
    tag_hits = []
    for d in pool:
        meta = _json(d.get("metadata_json"), {})
        tag_hits.append(1.0 if q["asset_aliases"] & set(meta.get("asset_aliases") or []) else 0.0)
    if any(tag_hits):
        tr = _rank(tag_hits)
        rrf = [v + 1 / (60 + tr[i]) for i, v in enumerate(rrf)]
    first = sorted(range(len(pool)), key=lambda i: rrf[i], reverse=True)[:min(24, len(pool))]

    rerank_raw = [0.0] * len(pool)
    pairs = [(q["text"], pool[i].get("search_text") or "") for i in first]
    try:
        rr = backend.pair_scores(pairs)
    except Exception:
        rr = None
    if rr:
        rrn = _normalize(rr)
        for idx, val in zip(first, rrn):
            rerank_raw[idx] = val
    else:
        # Fused retrieval score is a deterministic fallback reranker.
        rrn = _normalize([rrf[i] for i in first])
        for idx, val in zip(first, rrn):
            rerank_raw[idx] = val

    agent_by_uid = {int(a.get("activity_uid")): a for a in (agent_links or [])
                    if a.get("activity_uid") is not None}
    candidates = []
    for i in first:
        act = pool[i]
        meta = _json(act.get("metadata_json"), {})
        sf = _signal_features(project_id, ev, act, meta, q)
        feat = {"dense": dense_norm[i], "dense_cosine": dense_raw[i],
                "sparse": sparse_norm[i], "sparse_bm25": sparse_raw[i],
                "rrf": rrf[i], "rerank": rerank_raw[i], **sf}
        ap = agent_by_uid.get(int(act["uid"]))
        if ap:
            feat["agent_agreement"] = 1.0
            feat["agent_confidence"] = float(ap.get("confidence") or 0.5)
            feat["supports"].extend(list(ap.get("supporting_signals") or []))
            feat["conflicts"].extend(list(ap.get("conflicting_signals") or []))
        else:
            feat["agent_agreement"] = 0.0
            feat["agent_confidence"] = 0.0
        feat["raw_score"] = _raw_score(feat)
        candidates.append({"activity": act, "score": feat["raw_score"],
                           "features": feat,
                           "supporting": list(dict.fromkeys(feat.pop("supports"))),
                           "conflicting": list(dict.fromkeys(feat.pop("conflicts"))),
                           "from_agent": bool(ap)})
    # Include an agent candidate outside retrieval Top-24 so the system can
    # explicitly evaluate disagreement rather than silently discard it.
    present = {int(c["activity"]["uid"]) for c in candidates}
    by_uid = {int(d["uid"]): d for d in docs}
    for uid, ap in agent_by_uid.items():
        if uid in present or uid not in by_uid:
            continue
        act = by_uid[uid]
        meta = _json(act.get("metadata_json"), {})
        sf = _signal_features(project_id, ev, act, meta, q)
        feat = {"dense": 0.0, "dense_cosine": 0.0, "sparse": 0.0, "sparse_bm25": 0.0,
                "rrf": 0.0, "rerank": 0.0, **sf,
                "agent_agreement": 1.0, "agent_confidence": float(ap.get("confidence") or 0.5)}
        feat["raw_score"] = _raw_score(feat)
        candidates.append({"activity": act, "score": feat["raw_score"], "features": feat,
                           "supporting": list(ap.get("supporting_signals") or []),
                           "conflicting": list(ap.get("conflicting_signals") or []),
                           "from_agent": True})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    # Separation from the nearest alternative is a powerful uncertainty signal.
    # Keep it outside the handcrafted rank score so the learned confidence layer
    # can discover how much margin actually predicts correctness.
    for pos, cand in enumerate(candidates):
        others = [c["score"] for j, c in enumerate(candidates) if j != pos]
        cand["features"]["rank_margin"] = max(0.0, cand["score"] - max(others)) if others else 1.0
        cand["features"]["rank_position"] = 1.0 / (pos + 1.0)
    diagnostics.update({"index": index_info, "embedding_backend": backend.name,
                        "retrieved_pool": len(pool), "reranked": len(first)})
    return {"candidates": candidates[:max(top_k, 1)], "diagnostics": diagnostics}


def activity_context(project_id: str, uid: int) -> dict:
    act = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?", [project_id, uid])
    if not act:
        return {}
    rel = db.q("SELECT pred_uid,pred_name,succ_uid,succ_name,type,lag_days,driving "
               "FROM relationships WHERE project_id=? AND (pred_uid=? OR succ_uid=?)",
               [project_id, uid, uid])
    doc = db.q1("SELECT search_text,embedding_model,metadata_json FROM retrieval_documents "
                "WHERE project_id=? AND activity_uid=?", [project_id, uid])
    if not doc:
        index_project(project_id)
        doc = db.q1("SELECT search_text,embedding_model,metadata_json FROM retrieval_documents "
                    "WHERE project_id=? AND activity_uid=?", [project_id, uid])
    return {"activity": act, "relationships": rel,
            "search_document": (doc or {}).get("search_text"),
            "retrieval_metadata": _json((doc or {}).get("metadata_json"), {}),
            "embedding_backend": (doc or {}).get("embedding_model")}
