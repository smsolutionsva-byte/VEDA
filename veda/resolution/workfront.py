"""Dynamic execution-frontier ranking (WorkfrontRank).

Semantic relevance answers "what does this observation sound like?".  This
module answers the orthogonal question "where in the live execution graph is
this work plausible now?".  The second signal is a prior, never a hard veto:
Primavera explicitly permits out-of-sequence progress under multiple scheduling
modes.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from .. import db
from ..retrieval.entities import extract_asset_tags, asset_alias_set, extract_location_tags

_RECENT_CACHE: dict[tuple[str,str], tuple[list[dict],list[dict]]] = {}


def _date(v: Any):
    if not v: return None
    try: return datetime.strptime(str(v).split("T")[0], "%Y-%m-%d").date()
    except Exception: return None


def _prefix(wbs: Any, levels: int = 3) -> str:
    raw = str(wbs or "").strip()
    if not raw: return ""
    parts = [p for p in raw.replace(">", ".").replace("/", ".").split(".") if p]
    return ".".join(parts[:levels])


def _norm(values: dict[int, float]) -> dict[int, float]:
    if not values: return {}
    lo, hi = min(values.values()), max(values.values())
    if hi-lo < 1e-12:
        return {k: (1.0 if hi > 0 else 0.0) for k in values}
    return {k: (v-lo)/(hi-lo) for k,v in values.items()}


def _status_prior(act: dict, day) -> float:
    status = str(act.get("status") or "").lower()
    astart, afin = _date(act.get("actual_start")), _date(act.get("actual_finish"))
    if day and afin and afin < day - timedelta(days=45):
        return 0.12
    if day and astart and astart <= day and (not afin or afin >= day):
        return 1.0
    if status in {"in_progress", "started", "active"}: return 1.0
    if status in {"not_started", "not started", "planned", "ready"}: return 0.78
    if status in {"complete", "completed", "finished"}: return 0.35
    return 0.58


def _recent_rows(project_id: str, day):
    key=(project_id,day.isoformat())
    if key in _RECENT_CACHE: return _RECENT_CACHE[key]
    start=(day-timedelta(days=28)).isoformat(); end=day.isoformat()
    acts=db.q("SELECT uid,wbs,wbs_path,name,actual_start,actual_finish FROM activities WHERE project_id=? AND ((actual_start BETWEEN ? AND ?) OR (actual_finish BETWEEN ? AND ?))",[project_id,start,end,start,end])
    evs=db.q("SELECT ee.activity_uid,ee.event_date,a.wbs,a.wbs_path,a.name FROM execution_events ee LEFT JOIN activities a ON a.project_id=ee.project_id AND a.uid=ee.activity_uid WHERE ee.project_id=? AND ee.event_date BETWEEN ? AND ?",[project_id,start,end])
    _RECENT_CACHE[key]=(acts,evs); return acts,evs

def _recent_workfront(project_id: str, ev: dict, act: dict) -> dict:
    day = _date(ev.get("date"))
    if not day:
        return {"score":0.5,"wbs":0.5,"location":0.5,"event":0.5,"samples":0}
    rows,recent_events=_recent_rows(project_id,day)
    target_wbs = _prefix(act.get("wbs") or act.get("wbs_path"), 3)
    target_loc = set(extract_location_tags(act.get("wbs_path"), act.get("name"), act.get("location_tags_json")))
    w_hits=0.0; loc_hits=0.0; samples=0
    for r in rows:
        if int(r.get("uid") or -1)==int(act.get("uid") or -2): continue
        samples += 1; rp=_prefix(r.get("wbs") or r.get("wbs_path"),3)
        if target_wbs and rp:
            if rp==target_wbs:w_hits+=1.0
            elif rp.split(".")[:2]==target_wbs.split(".")[:2]:w_hits+=.45
        rloc=set(extract_location_tags(r.get("wbs_path"),r.get("name")))
        if target_loc and rloc and target_loc&rloc:loc_hits+=1.0
    wscore=min(1.0,w_hits/3.0) if samples else .5; lscore=min(1.0,loc_hits/3.0) if samples else .5
    ev_hits=0.0
    for r in recent_events:
        rp=_prefix(r.get("wbs") or r.get("wbs_path"),3)
        if target_wbs and rp==target_wbs:ev_hits+=1.0
        rloc=set(extract_location_tags(r.get("wbs_path"),r.get("name")))
        if target_loc and rloc and target_loc&rloc:ev_hits+=.65
    escore=min(1.0,ev_hits/2.0) if recent_events else .5
    return {"score":.45*wscore+.25*lscore+.30*escore,"wbs":wscore,"location":lscore,"event":escore,"samples":samples,"recent_events":len(recent_events)}


def _readiness(project_id: str, ev: dict, act: dict) -> dict:
    uid=act.get("uid"); day=_date(ev.get("date"))
    if uid is None: return {"score":0.5,"pred_ready":0.5,"succ_advanced":0,"count":0}
    rels=db.q("SELECT pred_uid,succ_uid,type,lag_days,driving FROM relationships WHERE project_id=? AND (pred_uid=? OR succ_uid=?)",
              [project_id,uid,uid])
    preds=[r for r in rels if int(r.get("succ_uid") or -1)==int(uid)]
    succs=[r for r in rels if int(r.get("pred_uid") or -1)==int(uid)]
    ids=list({int(r["pred_uid"]) for r in preds if r.get("pred_uid") is not None} | {int(r["succ_uid"]) for r in succs if r.get("succ_uid") is not None})
    rows={}
    if ids:
        ph=','.join('?' for _ in ids)
        rows={int(x['uid']):x for x in db.q("SELECT uid,status,actual_start,actual_finish,start,finish FROM activities WHERE project_id=? AND uid IN ("+ph+")",[project_id]+ids)}
    vals=[]
    for r in preds:
        p=rows.get(int(r.get("pred_uid") or -1),{})
        typ=str(r.get("type") or "FS").upper()[:2]
        lag=float(r.get("lag_days") or 0.0)
        anchor=_date(p.get("actual_start") if typ in {"SS","SF"} else p.get("actual_finish"))
        planned=_date(p.get("start") if typ in {"SS","SF"} else p.get("finish"))
        if day and anchor:
            ready=1.0 if anchor + timedelta(days=lag) <= day else 0.08
        elif anchor: ready=.92
        elif day and planned and planned + timedelta(days=lag) <= day: ready=.60
        elif str(p.get("status") or "").lower() in {"complete","completed"}: ready=.80
        else: ready=.18
        if r.get("driving"): ready=min(1.0, ready*1.08)
        vals.append(ready)
    pred_ready=sum(vals)/len(vals) if vals else .72
    succ_adv=0
    if day:
        for r in succs:
            s=rows.get(int(r.get("succ_uid") or -1),{})
            d=_date(s.get("actual_start") or s.get("actual_finish"))
            if d and d<=day: succ_adv+=1
    score=0.2+0.72*pred_ready+min(.08,.04*succ_adv)
    return {"score":max(0,min(1,score)),"pred_ready":pred_ready,"succ_advanced":succ_adv,"count":len(rels)}


def frontier_uids(project_id: str, ev: dict, limit: int = 72) -> dict:
    """Generate candidates from the live execution frontier, independent of text.

    This is the PageRank-shaped retrieval channel: if semantic evidence omits an
    asset/location entirely, active workfront topology can still put the right
    activity into the candidate set before reranking.
    """
    day=_date(ev.get("date"))
    if not day: return {"uids":[],"scores":{},"basis":"no_date"}
    recent,_=_recent_rows(project_id,day)
    recent=recent[-600:]
    scores=defaultdict(float); recent_uids=[]; active_prefix=defaultdict(float)
    for r in recent:
        uid=int(r.get("uid") or -1)
        if uid<0: continue
        recent_uids.append(uid)
        dt=_date(r.get("actual_finish") or r.get("actual_start"))
        rec=math.exp(-abs((day-dt).days)/10.0) if dt else .4
        scores[uid]+=0.25*rec
        p=_prefix(r.get("wbs") or r.get("wbs_path"),3)
        if p: active_prefix[p]=max(active_prefix[p],rec)
    # Direct/second-hop successors of recently executed work.
    if recent_uids:
        ph=','.join('?' for _ in recent_uids)
        rel=db.q("SELECT pred_uid,succ_uid,driving FROM relationships WHERE project_id=? AND pred_uid IN ("+ph+")",[project_id]+recent_uids)
        first=[]
        for r in rel:
            su=r.get("succ_uid")
            if su is None: continue
            su=int(su); first.append(su); scores[su]+=1.0 if r.get("driving") else .78
        if first:
            ph=','.join('?' for _ in set(first))
            for r in db.q("SELECT pred_uid,succ_uid,driving FROM relationships WHERE project_id=? AND pred_uid IN ("+ph+")",[project_id]+list(set(first))):
                if r.get("succ_uid") is not None: scores[int(r['succ_uid'])]+=.38 if r.get('driving') else .24
    # Planned/in-progress nodes inside a currently hot WBS branch belong to the
    # frontier even when predecessors are stale or work runs out of sequence.
    if active_prefix:
        lo=(day-timedelta(days=21)).isoformat(); hi=(day+timedelta(days=35)).isoformat()
        near=db.q("SELECT uid,wbs,wbs_path,start,finish,status FROM activities WHERE project_id=? AND is_summary=0 AND ((start<=? AND finish>=?) OR start BETWEEN ? AND ?)",[project_id,hi,lo,lo,hi])
        for a in near:
            p=_prefix(a.get('wbs') or a.get('wbs_path'),3)
            if p in active_prefix:
                scores[int(a['uid'])]+=.62*active_prefix[p]
    ranked=sorted(scores.items(),key=lambda x:x[1],reverse=True)[:limit]
    norm=_norm(dict(ranked))
    return {"uids":[u for u,_ in ranked],"scores":norm,"basis":"recent_actuals+successors+active_wbs","recent_activities":len(recent_uids),"active_wbs":len(active_prefix)}


def execution_prior(project_id: str, ev: dict, cand: dict) -> dict:
    act=cand.get("activity") or {}
    f=cand.get("features") or {}
    day=_date(ev.get("date"))
    pred=float(f.get("pred_ready",.5)); graph=float(f.get("graph",.5))
    ready={"score":.35+.65*pred,"pred_ready":pred,"succ_advanced":float(f.get("successor_progress",0)),"count":0}
    recent=_recent_workfront(project_id,ev,act)
    temporal=float(f.get("temporal",.5))
    status=_status_prior(act,day)
    # Network readiness is the strongest live-state signal. Dates/workfront are
    # priors, not truth, because stale schedules and OOS progress are normal.
    score=(.34*ready["score"] + .18*graph + .18*recent["score"] +
           .18*temporal + .12*status)
    return {"score":max(0,min(1,score)),"readiness":ready,"recent":recent,
            "temporal":temporal,"status":status}


def _add_edge(adj: dict[str, dict[str,float]], a: str, b: str, w: float):
    if not a or not b or a==b: return
    adj[a][b]+=w; adj[b][a]+=w


def _ppr_scores(project_id: str, ev: dict, candidates: list[dict]) -> dict[int,float]:
    """Personalized PageRank over a local heterogeneous project graph."""
    if not candidates: return {}
    uidset={int(c["activity"]["uid"]) for c in candidates if c.get("activity",{}).get("uid") is not None}
    # One-hop schedule neighbors provide topology without walking all 10k+ nodes.
    rels=[]
    if uidset:
        ph=','.join('?' for _ in uidset)
        rels=db.q("SELECT pred_uid,succ_uid,driving FROM relationships WHERE project_id=? AND (pred_uid IN ("+ph+") OR succ_uid IN ("+ph+"))",
                  [project_id]+list(uidset)+list(uidset))
    neighbor=set(uidset)
    for r in rels:
        if r.get("pred_uid") is not None: neighbor.add(int(r["pred_uid"]))
        if r.get("succ_uid") is not None: neighbor.add(int(r["succ_uid"]))
    rows={}
    if neighbor:
        ph=','.join('?' for _ in neighbor)
        rows={int(a['uid']):a for a in db.q("SELECT uid,name,wbs,wbs_path,custom_json,asset_tags_json,location_tags_json FROM activities WHERE project_id=? AND uid IN ("+ph+")",[project_id]+list(neighbor))}
    adj=defaultdict(lambda:defaultdict(float))
    for r in rels:
        a,b=r.get("pred_uid"),r.get("succ_uid")
        if a is not None and b is not None: _add_edge(adj,f"A:{int(a)}",f"A:{int(b)}",1.15 if r.get("driving") else .85)
    for uid,a in rows.items():
        an=f"A:{uid}"
        w=_prefix(a.get("wbs") or a.get("wbs_path"),3)
        if w: _add_edge(adj,an,"W:"+w,.95)
        tags=extract_asset_tags(a.get("name"),a.get("custom_json"),a.get("asset_tags_json"))
        for al in list(asset_alias_set(tags))[:6]: _add_edge(adj,an,"AS:"+al,1.20)
        for loc in extract_location_tags(a.get("wbs_path"),a.get("name"),a.get("location_tags_json"))[:6]: _add_edge(adj,an,"L:"+loc,1.0)

    personalization=defaultdict(float)
    # Local semantic/engineering result is one seed, not the final answer.
    for c in candidates:
        uid=int(c["activity"]["uid"]); personalization[f"A:{uid}"] += .35 + .65*float(c.get("score") or 0)
    evtags=extract_asset_tags(ev.get("description"),ev.get("raw_json"))
    for al in asset_alias_set(evtags): personalization["AS:"+al]+=1.65
    for loc in extract_location_tags(ev.get("location"),ev.get("description"),ev.get("raw_json")): personalization["L:"+loc]+=1.25
    # Recent live workfront is another seed.
    day=_date(ev.get("date"))
    if day:
        start=(day-timedelta(days=21)).isoformat(); end=day.isoformat()
        for r in db.q("SELECT uid FROM activities WHERE project_id=? AND ((actual_start BETWEEN ? AND ?) OR (actual_finish BETWEEN ? AND ?)) LIMIT 500",
                      [project_id,start,end,start,end]):
            personalization[f"A:{int(r['uid'])}"] += .55

    nodes=set(adj)|set(personalization)
    for n,links in adj.items(): nodes.update(links)
    if not nodes: return {int(c['activity']['uid']):0.0 for c in candidates}
    psum=sum(personalization.values()) or 1.0
    p={n:personalization.get(n,0)/psum for n in nodes}
    rank=dict(p); d=.85
    for _ in range(24):
        nxt={n:(1-d)*p.get(n,0) for n in nodes}
        dangling=0.0
        for n,val in rank.items():
            links=adj.get(n,{})
            total=sum(links.values())
            if total<=0: dangling+=val; continue
            for m,w in links.items(): nxt[m]=nxt.get(m,0)+d*val*w/total
        if dangling:
            for n,pv in p.items(): nxt[n]=nxt.get(n,0)+d*dangling*pv
        diff=sum(abs(nxt.get(n,0)-rank.get(n,0)) for n in nodes)
        rank=nxt
        if diff<1e-8: break
    raw={int(c['activity']['uid']):rank.get(f"A:{int(c['activity']['uid'])}",0.0) for c in candidates}
    return _norm(raw)


def rerank(project_id: str, ev: dict, candidates: list[dict]) -> dict:
    """Reorder candidates by evidence relevance *and* live execution plausibility."""
    if not candidates: return {"candidates":[],"diagnostics":{}}
    ppr=_ppr_scores(project_id,ev,candidates)
    for c in candidates:
        uid=int(c["activity"]["uid"])
        prior=execution_prior(project_id,ev,c)
        base=float(c.get("score") or 0)
        graph_coherence=float(ppr.get(uid,0.0))
        f=c.setdefault("features",{})
        # Conservative cold-start fusion. The language/engineering resolver keeps
        # majority control; execution state can flip close candidates but cannot
        # rescue a semantically unrelated task from nowhere.
        frontier=float(f.get("frontier_channel",0.0))
        final=.52*base + .23*prior["score"] + .15*graph_coherence + .10*frontier
        f["pre_workfront_score"]=base
        f["execution_frontier"]=prior["score"]
        f["workfront_ppr"]=graph_coherence
        f["frontier_channel"]=frontier
        f["workfront_rank_score"]=max(0,min(1,final))
        f["workfront_detail"]=prior
        c["score"]=f["workfront_rank_score"]
    candidates.sort(key=lambda x:x.get("score",0),reverse=True)
    for i,c in enumerate(candidates):
        c["features"]["rank_position"]=1.0/(i+1)
        if i==0:
            runner=float(candidates[1].get("score") or 0) if len(candidates)>1 else 0.0
            c["features"]["rank_margin"]=max(0,float(c.get("score") or 0)-runner)
        else: c["features"]["rank_margin"]=0.0
    return {"candidates":candidates,"diagnostics":{"method":"workfrontrank_v1","ppr":"local_heterogeneous_personalized_pagerank","fusion":{"base":.52,"execution_frontier":.23,"ppr":.15,"frontier_channel":.10}}}
