"""Opportunistic / continual planning expert for VEDA.

This module performs local plan recognition by counterfactual rescheduling.
For each candidate activity it asks: if the new observation were applied here,
what would the local execution state look like, and how coherent is the best
short continuation of the plan?

Hard constraints define valid transitions; a beam-search planner chooses among
valid next actions.  This avoids a giant hand-authored if/else policy while
keeping schedule truth deterministic and auditable.  It is an experimental
ranking expert and never mutates the real schedule.
"""
from __future__ import annotations

import math, re
from collections import defaultdict
from datetime import datetime,timedelta
from typing import Any
from .. import db
from . import events as event_model
from ..retrieval.entities import extract_location_tags, extract_asset_tags, asset_alias_set

_CACHE:dict[str,dict]={}

def _date(v):
    if not v:return None
    try:return datetime.strptime(str(v).split('T')[0],'%Y-%m-%d').date()
    except Exception:return None

def _index(project_id:str)->dict:
    sig=db.q1('SELECT COUNT(*) c, COALESCE(MAX(created_at),0) u FROM activities WHERE project_id=?',[project_id]) or {'c':0,'u':0}
    key=(int(sig.get('c') or 0),float(sig.get('u') or 0.0))
    old=_CACHE.get(project_id)
    if old and old.get('sig')==key:return old
    acts={int(a['uid']):a for a in db.q('SELECT * FROM activities WHERE project_id=? AND is_summary=0',[project_id]) if a.get('uid') is not None}
    prefix_map=defaultdict(set); info={}; action_map=defaultdict(set); asset_map=defaultdict(set); location_map=defaultdict(set); discipline_map=defaultdict(set)
    for uid,a in acts.items():
        pref='.'.join(str(a.get('wbs') or '').split('.')[:3])
        if pref: prefix_map[pref].add(uid)
        tags=extract_asset_tags(a.get('name'),a.get('custom_json'),a.get('wbs_path'))
        aliases=asset_alias_set(tags); action=event_model.detect_action(a.get('name')).get('action')
        locs=set(extract_location_tags(a.get('wbs_path'),a.get('name'))); disc=str((str(a.get('wbs_path') or '').split('>')[-1] if a.get('wbs_path') else '')).strip().lower()
        info[uid]={'action':action,'aliases':aliases,'locations':locs,'discipline':disc,'name_tokens':set(re.findall(r'[a-z0-9]+',str(a.get('name') or '').lower())),'start_date':_date(a.get('start') or a.get('baseline_start')),'finish_date':_date(a.get('finish') or a.get('baseline_finish'))}
        if action: action_map[action].add(uid)
        for al in aliases: asset_map[re.sub(r'[^a-z0-9]','',str(al).lower())].add(uid)
        for loc in locs: location_map[str(loc).lower()].add(uid)
        if disc: discipline_map[disc].add(uid)
    preds=defaultdict(list); succs=defaultdict(list)
    for r in db.q('SELECT * FROM relationships WHERE project_id=?',[project_id]):
        if r.get('pred_uid') is None or r.get('succ_uid') is None:continue
        p,s=int(r['pred_uid']),int(r['succ_uid']); preds[s].append(r); succs[p].append(r)
    out={'sig':key,'acts':acts,'preds':preds,'succs':succs,'prefix_map':prefix_map,'info':info,'action_map':action_map,'asset_map':asset_map,'location_map':location_map,'discipline_map':discipline_map};_CACHE[project_id]=out;return out

def _completed(a:dict,day)->bool:
    f=_date(a.get('actual_finish'))
    return bool(f and (not day or f<=day)) or str(a.get('status') or '').lower() in {'complete','completed','finished'}

def _started(a:dict,day)->bool:
    s=_date(a.get('actual_start'))
    return bool(s and (not day or s<=day)) or str(a.get('status') or '').lower() in {'in_progress','started','active'}

def _pred_ready(idx,uid,day,completed_override:set[int])->tuple[float,int]:
    rels=idx['preds'].get(uid,[])
    if not rels:return .85,0
    vals=[]
    for r in rels:
        p=int(r['pred_uid']); a=idx['acts'].get(p,{})
        typ=str(r.get('type') or 'FS').upper()[:2]; lag=float(r.get('lag_days') or 0)
        if p in completed_override: ready=1.0
        elif typ in {'SS','SF'}: ready=.95 if _started(a,day) else .20
        else: ready=.98 if _completed(a,day) else .16
        if r.get('driving'): ready=min(1.0,ready*1.03)
        vals.append(ready)
    return sum(vals)/len(vals),len(rels)

def _temporal(a,day)->float:
    if not day:return .5
    s=_date(a.get('start') or a.get('baseline_start'));f=_date(a.get('finish') or a.get('baseline_finish'))
    if s and f:
        if s-timedelta(days=7)<=day<=f+timedelta(days=14):return 1.0
        dist=min(abs((day-s).days),abs((day-f).days));return max(.05,math.exp(-dist/50.0))
    return .5

def _temporal_uid(idx,uid,day)->float:
    if not day:return .5
    inf=idx['info'].get(uid,{})
    s=inf.get('start_date');f=inf.get('finish_date')
    if s and f:
        if s-timedelta(days=7)<=day<=f+timedelta(days=14):return 1.0
        dist=min(abs((day-s).days),abs((day-f).days));return max(.05,math.exp(-dist/50.0))
    return .5

def _continuity(a,b)->float:
    if not a or not b:return .5
    la=set(extract_location_tags(a.get('wbs_path'),a.get('name')));lb=set(extract_location_tags(b.get('wbs_path'),b.get('name')))
    loc=1.0 if la and lb and la&lb else .35
    wa=str(a.get('wbs') or '').split('.')[:3];wb=str(b.get('wbs') or '').split('.')[:3]
    wbs=1.0 if wa and wb and wa==wb else .35
    return .55*loc+.45*wbs

def _local_pool(idx,uid,day)->set[int]:
    pool={uid};front={uid}
    for _ in range(2):
        nxt=set()
        for x in front:
            nxt|={int(r['pred_uid']) for r in idx['preds'].get(x,[]) if r.get('pred_uid') is not None}
            nxt|={int(r['succ_uid']) for r in idx['succs'].get(x,[]) if r.get('succ_uid') is not None}
        pool|=nxt;front=nxt
    a=idx['acts'].get(uid,{})
    pref='.'.join(str(a.get('wbs') or '').split('.')[:3])
    if pref:
        for x in list(idx['prefix_map'].get(pref,()))[:160]:
            b=idx['acts'].get(x,{})
            if _temporal_uid(idx,x,day)>.25: pool.add(x)
            if len(pool)>36: break
    return pool

def _beam_future(idx,anchor_uid,day,completed_override:set[int],depth=3,width=8)->tuple[float,list[int]]:
    """Search a short rolling horizon; higher utility = coherent continuation."""
    pool=_local_pool(idx,anchor_uid,day)
    anchor=idx['acts'].get(anchor_uid,{})
    states=[(0.0,[],set(completed_override),anchor_uid)]
    for step in range(depth):
        new=[]
        for util,path,done,last in states:
            actions=[]
            for uid in pool:
                if uid in done:continue
                a=idx['acts'].get(uid,{})
                if _completed(a,day):continue
                ready,_=_pred_ready(idx,uid,day,done)
                # Valid Action Sampling style: very low-readiness nodes are not
                # expanded, but nonzero OOS possibility remains via threshold .12.
                if ready<.12:continue
                temp=_temporal_uid(idx,uid,day);cont=_continuity(idx['acts'].get(last),a)
                critical=1.0 if a.get('critical') else .5
                score=.42*ready+.28*temp+.20*cont+.10*critical
                actions.append((score,uid))
            if not actions:
                new.append((util,path,done,last));continue
            for sc,uid in sorted(actions,reverse=True)[:width]:
                nd=set(done);nd.add(uid)
                new.append((util+(0.88**step)*sc,path+[uid],nd,uid))
        states=sorted(new,key=lambda x:x[0],reverse=True)[:width] or states
    best=max(states,key=lambda x:x[0])
    maxu=sum(0.88**s for s in range(depth))
    return min(1.0,best[0]/max(1e-6,maxu)),best[1]

def score_candidate(project_id:str,ev:dict,cand:dict)->tuple[float,dict]:
    idx=_index(project_id);a=cand.get('activity') or {};uid=int(a.get('uid'))
    day=_date(ev.get('date'));info=event_model.classify_event(ev);state=info.get('state')
    override=set()
    # Counterfactual: start/progress/finish evidence means this node has advanced.
    if state in {'finish','progress','start','mixed'}:override.add(uid)
    ready,pn=_pred_ready(idx,uid,day,override-set([uid]))
    temp=_temporal_uid(idx,uid,day)
    # Observation-state compatibility / contradiction cost.
    contradiction=0.0
    af=_date(a.get('actual_finish')); ast=_date(a.get('actual_start'))
    if day and af and af<day-timedelta(days=45) and state in {'start','progress'}:contradiction+=.8
    if day and ast and ast>day+timedelta(days=2):contradiction+=.7
    # Explicit emergency/OOS language tells the planner that precedence may be
    # violated intentionally rather than declaring the candidate impossible.
    text=str(ev.get('description') or '').lower()
    emergency=1.0 if any(x in text for x in ('emergency','out-of-sequence','out of sequence','approved deviation','bypass')) else 0.0
    oos_pen=max(0.0,.45-ready)*(1.0-.75*emergency)
    future,path=_beam_future(idx,uid,day,override,depth=3,width=7)
    # Unlock value: completed candidate that enables successors is opportunistic.
    unlock=0.0
    for r in idx['succs'].get(uid,[]):
        su=int(r['succ_uid']); rr,_=_pred_ready(idx,su,day,override)
        unlock=max(unlock,rr)
    coherence=.28*ready+.20*temp+.30*future+.12*unlock+.10*(1.0-min(1.0,contradiction+oos_pen))
    return max(0,min(1,coherence)),{'rescheduler_score':coherence,'replan_readiness':ready,'replan_temporal':temp,
        'replan_future_utility':future,'replan_unlock':unlock,'replan_contradiction':min(1.0,contradiction+oos_pen),
        'replan_emergency_context':emergency,'replan_path':path,'replan_pred_count':pn}

def seed_candidates(project_id:str,ev:dict,limit:int=40)->list[dict]:
    """Indexed flat evidence screen + live frontier, hierarchy-agnostic."""
    idx=_index(project_id); day=_date(ev.get('date')); einfo=event_model.classify_event(ev)
    action=einfo.get('action'); disc=str(ev.get('discipline') or '').lower()
    qaliases=asset_alias_set(extract_asset_tags(ev.get('description'),ev.get('asset_tag'),ev.get('asset_tags')))
    qloc=set(extract_location_tags(ev.get('description'),ev.get('location')))
    qtokens={x for x in re.findall(r'[a-z0-9]+',str(ev.get('description') or '').lower()) if x not in {'completed','complete','started','start','site','unit','area','work','the','and'}}
    frontier={}
    try:
        from . import workfront
        frontier=workfront.frontier_uids(project_id,ev,limit=72).get('scores') or {}
        frontier={int(k):float(v) for k,v in frontier.items()}
    except Exception: frontier={}
    asset_u=set()
    for al in qaliases: asset_u |= set(idx['asset_map'].get(re.sub(r'[^a-z0-9]','',str(al).lower()),()))
    action_u=set(idx['action_map'].get(action,())) if action else set()
    loc_u=set()
    for loc in qloc: loc_u |= set(idx['location_map'].get(str(loc).lower(),()))
    disc_u=set()
    if disc:
        for k,v in idx['discipline_map'].items():
            if disc in k or k in disc: disc_u |= set(v)
    # Evidence-directed attention: do not scan the whole project when a strong
    # physical identity exists. This is candidate generation only; it does not
    # decide the schedule action.
    pool=set(frontier)
    if asset_u:
        pool |= asset_u
    elif action_u and loc_u:
        narrowed=action_u & loc_u
        if disc_u: narrowed = narrowed & disc_u or narrowed
        pool |= narrowed
    elif action_u and disc_u:
        pool |= (action_u & disc_u)
    elif action_u:
        pool |= action_u
    elif loc_u:
        pool |= loc_u
    elif disc_u:
        pool |= set(list(disc_u)[:3000])
    if not pool: pool=set(idx['acts'])
    scored=[]
    for uid in pool:
        a=idx['acts'].get(uid); inf=idx['info'].get(uid,{})
        if not a: continue
        asset=(1.0 if qaliases and qaliases & set(inf.get('aliases') or []) else (.5 if not qaliases else 0.0))
        act=(1.0 if action and action==inf.get('action') else (.5 if not action else .05))
        al=set(inf.get('locations') or []); loc=(1.0 if qloc and al and qloc&al else (.5 if not qloc else .12))
        ds=1.0 if disc and disc in str(inf.get('discipline') or '') else (.5 if not disc else .2)
        temp=_temporal_uid(idx,uid,day); fr=frontier.get(uid,0.0)
        nt=set(inf.get('name_tokens') or []); lex=len(nt&qtokens)/max(1,len(nt|qtokens)) if qtokens and nt else .5
        score=.28*asset+.21*act+.13*loc+.07*ds+.09*temp+.10*fr+.12*lex
        scored.append((score,uid))
    scored.sort(reverse=True)
    return [{'activity':idx['acts'][uid],'score':score,'features':{'engineering_rank_score':score,'seed_frontier':frontier.get(uid,0.0)},'supporting':['opportunistic planner seed'],'conflicting':[],'from_agent':False} for score,uid in scored[:limit]]


def standalone_rank(project_id:str,ev:dict,limit:int=24)->dict:
    return rerank(project_id,ev,seed_candidates(project_id,ev,limit=40),limit=limit)


def rerank(project_id:str,ev:dict,candidates:list[dict],limit=24)->dict:
    # Cheap screen first; deep counterfactual planning only on the disputed
    # shortlist. This mirrors an agent that escalates reasoning cost with ambiguity.
    prepared=[]
    for c0 in candidates:
        c={**c0,'features':dict(c0.get('features') or {})}
        f=c['features']; eng=float(f.get('engineering_rank_score',c.get('score') or 0.0))
        prepared.append((eng,c))
    prepared.sort(key=lambda x:x[0],reverse=True)
    ordered=[x[0] for x in prepared]
    margin=(ordered[0]-ordered[1]) if len(ordered)>1 else 1.0
    ambiguity=max(0.0,min(1.0,1.0-margin/0.22))
    alpha=.06+.24*ambiguity
    # Evaluate at most 12 plausible identities. Lower-ranked candidates retain
    # EngineeringRank and cannot burn CPU on speculative futures.
    deep_uids={int(c['activity']['uid']) for _,c in prepared[:12]}
    out=[]
    for eng,c in prepared:
        uid=int(c['activity']['uid'])
        if uid in deep_uids:
            rs,rf=score_candidate(project_id,ev,c)
        else:
            rs=.5;rf={'rescheduler_score':.5,'replan_skipped':True}
        score=(1.0-alpha)*eng+alpha*rs
        c['features'].update(rf);c['features']['rescheduler_authority']=alpha;c['score']=score;out.append(c)
    out.sort(key=lambda c:c['score'],reverse=True)
    return {'candidates':out[:limit],'diagnostics':{'evaluated':len(deep_uids),'planner':'counterfactual rolling-horizon beam search','depth':3,'beam_width':7,'engineering_margin':margin,'planner_authority':alpha}}
