"""Reality-first opportunistic rescheduler / plan-recognition expert.

v2 audit design principles
--------------------------
1. Assimilate observed execution into the hypothetical world *before* judging
   the repaired future. A factual Actual Start is allowed to violate the plan.
2. Keep STARTED and COMPLETED state separate. Starting an activity must never
   satisfy an FS predecessor as if it had finished.
3. Detect out-of-sequence (OOS) progress from schedule-state contradiction;
   do not require the report to literally contain the words "out of sequence".
4. Respect the project's Primavera OOS scheduling mode (Retained Logic,
   Progress Override, Actual Dates) when simulating the continuation.
5. Treat plan coherence as a downstream residual signal, not as a reason to
   deny an observed fact.
6. Interpret disruption/override context through a structured planning_context
   contract suitable for an LLM/agent. A conservative lexical fallback exists
   only for offline benchmarking.

This remains a local planner/recognizer, not a replacement for Primavera or
Horizun's schedule calculation. It never mutates the real schedule.
"""
from __future__ import annotations

import json, math, re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable
from .. import db
from . import events as event_model
from ..retrieval.entities import extract_location_tags, extract_asset_tags, asset_alias_set

_CACHE: dict[str, dict] = {}
_RECENT_STATE_CACHE: dict[tuple[str, str], dict] = {}


def _checkpoint(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check:
        cancel_check()


def _date(v):
    if not v: return None
    try: return datetime.strptime(str(v).split('T')[0], '%Y-%m-%d').date()
    except Exception: return None


def _prefix(v: Any, levels: int = 3) -> str:
    raw = str(v or '').strip()
    if not raw: return ''
    parts = [p for p in raw.replace('>', '.').replace('/', '.').split('.') if p]
    return '.'.join(parts[:levels])


def _index(project_id: str, cancel_check: Callable[[], None] | None = None) -> dict:
    _checkpoint(cancel_check)
    sig = db.q1('SELECT COUNT(*) c, COALESCE(MAX(created_at),0) u FROM activities WHERE project_id=?', [project_id]) or {'c':0,'u':0}
    key = (int(sig.get('c') or 0), float(sig.get('u') or 0.0))
    old = _CACHE.get(project_id)
    if old and old.get('sig') == key: return old
    acts = {int(a['uid']): a for a in db.q('SELECT * FROM activities WHERE project_id=? AND is_summary=0', [project_id]) if a.get('uid') is not None}
    prefix_map=defaultdict(set); info={}; action_map=defaultdict(set); asset_map=defaultdict(set); location_map=defaultdict(set); discipline_map=defaultdict(set)
    for position, (uid,a) in enumerate(acts.items()):
        if position % 128 == 0: _checkpoint(cancel_check)
        pref=_prefix(a.get('wbs') or a.get('wbs_path'),3)
        if pref: prefix_map[pref].add(uid)
        tags=extract_asset_tags(a.get('name'),a.get('custom_json'),a.get('wbs_path'))
        aliases=asset_alias_set(tags); action=event_model.detect_action(a.get('name')).get('action')
        locs=set(extract_location_tags(a.get('wbs_path'),a.get('name')))
        disc=str((str(a.get('wbs_path') or '').split('>')[-1] if a.get('wbs_path') else '')).strip().lower()
        info[uid]={'action':action,'aliases':aliases,'locations':locs,'discipline':disc,
                   'name_tokens':set(re.findall(r'[a-z0-9]+',str(a.get('name') or '').lower())),
                   'start_date':_date(a.get('start') or a.get('baseline_start')),
                   'finish_date':_date(a.get('finish') or a.get('baseline_finish')),
                   'prefix':pref}
        if action: action_map[action].add(uid)
        for al in aliases: asset_map[re.sub(r'[^a-z0-9]','',str(al).lower())].add(uid)
        for loc in locs: location_map[str(loc).lower()].add(uid)
        if disc: discipline_map[disc].add(uid)
    preds=defaultdict(list); succs=defaultdict(list)
    for position, r in enumerate(db.q('SELECT * FROM relationships WHERE project_id=?', [project_id])):
        if position % 256 == 0: _checkpoint(cancel_check)
        if r.get('pred_uid') is None or r.get('succ_uid') is None: continue
        p,s=int(r['pred_uid']),int(r['succ_uid']); preds[s].append(r); succs[p].append(r)
    out={'sig':key,'acts':acts,'preds':preds,'succs':succs,'prefix_map':prefix_map,'info':info,
         'action_map':action_map,'asset_map':asset_map,'location_map':location_map,'discipline_map':discipline_map}
    _CACHE[project_id]=out
    return out


def _schedule_mode(project_id: str) -> str:
    row = db.q1('SELECT info_json FROM schedule_snapshots WHERE project_id=? AND is_current=1 ORDER BY id DESC LIMIT 1', [project_id])
    try: info=json.loads((row or {}).get('info_json') or '{}')
    except Exception: info={}
    raw=str(info.get('out_of_sequence_schedule_type') or info.get('OutOfSequenceScheduleType') or 'Retained Logic').strip().lower()
    if 'progress' in raw and 'override' in raw: return 'Progress Override'
    if 'actual' in raw and 'date' in raw: return 'Actual Dates'
    return 'Retained Logic'


def _completed(a: dict, day) -> bool:
    f=_date(a.get('actual_finish'))
    return bool(f and (not day or f<=day)) or str(a.get('status') or '').lower() in {'complete','completed','finished'}


def _started(a: dict, day) -> bool:
    s=_date(a.get('actual_start'))
    return bool(s and (not day or s<=day)) or str(a.get('status') or '').lower() in {'in_progress','started','active'} or _completed(a,day)


def _pred_readiness(idx, uid, day, started_override:set[int], completed_override:set[int], target_state:str='start') -> tuple[float,int,list[dict]]:
    """Soft relationship satisfaction for the hypothesized event state.

    FS/SS constrain starts; FF/SF primarily constrain finishes. Lag is honored
    against actual anchors when available and planned anchors only as a weak prior.
    """
    rels=idx['preds'].get(uid,[])
    if not rels: return 1.0,0,[]
    vals=[]; detail=[]
    for r in rels:
        p=int(r['pred_uid']); a=idx['acts'].get(p,{})
        typ=str(r.get('type') or 'FS').upper()[:2]; lag=float(r.get('lag_days') or 0.0)
        pred_started = p in started_override or _started(a,day)
        pred_completed = p in completed_override or _completed(a,day)
        # For a START/PROGRESS observation, FF/SF do not make the activity start impossible.
        if target_state in {'start','progress','mixed'} and typ in {'FF','SF'}:
            ready=.85
        else:
            need_start = typ in {'SS','SF'}
            state_ok = pred_started if need_start else pred_completed
            anchor = _date(a.get('actual_start') if need_start else a.get('actual_finish'))
            planned = _date(a.get('start') if need_start else a.get('finish'))
            if state_ok and day and anchor:
                ready = 1.0 if anchor + timedelta(days=lag) <= day else .12
            elif state_ok:
                ready = .98
            elif day and planned and planned + timedelta(days=lag) <= day:
                # Planned dates cannot overrule missing actuals; weak plausibility only.
                ready = .42
            else:
                ready = .10
        if r.get('driving'): ready=min(1.0,ready*1.02)
        vals.append(ready); detail.append({'pred_uid':p,'type':typ,'lag_days':lag,'ready':ready})
    return sum(vals)/len(vals),len(rels),detail


def _temporal_uid(idx,uid,day)->float:
    if not day:return .5
    inf=idx['info'].get(uid,{})
    s=inf.get('start_date');f=inf.get('finish_date')
    if s and f:
        if s-timedelta(days=7)<=day<=f+timedelta(days=14):return 1.0
        dist=min(abs((day-s).days),abs((day-f).days));return max(.05,math.exp(-dist/50.0))
    return .5


def _continuity(idx, a_uid:int|None, b_uid:int|None)->float:
    """Cached workface continuity for the rolling-horizon inner loop.

    Location and WBS features are materialized by `_index`. Re-extracting them
    thousands of times per evidence row made Rescheduler dominate runtime.
    """
    if a_uid is None or b_uid is None:return .5
    ai=idx['info'].get(int(a_uid),{});bi=idx['info'].get(int(b_uid),{})
    if not ai or not bi:return .5
    la=set(ai.get('locations') or ());lb=set(bi.get('locations') or ())
    loc=1.0 if la and lb and la&lb else .35
    wa=str(ai.get('prefix') or '');wb=str(bi.get('prefix') or '')
    wbs=1.0 if wa and wb and wa==wb else .30
    return .58*loc+.42*wbs


def _recent_state(project_id:str, day) -> dict:
    if not day: return {'prefix_events':{},'prefix_actuals':{}}
    key=(project_id,day.isoformat())
    if key in _RECENT_STATE_CACHE:return _RECENT_STATE_CACHE[key]
    lo=(day-timedelta(days=28)).isoformat(); hi=day.isoformat()
    pe=defaultdict(float); pa=defaultdict(float)
    for r in db.q('SELECT ee.event_date,a.wbs,a.wbs_path FROM execution_events ee LEFT JOIN activities a ON a.project_id=ee.project_id AND a.uid=ee.activity_uid WHERE ee.project_id=? AND ee.event_date BETWEEN ? AND ?', [project_id,lo,hi]):
        p=_prefix(r.get('wbs') or r.get('wbs_path'),3)
        if p:
            d=_date(r.get('event_date')); rec=math.exp(-abs((day-d).days)/10.0) if d else .5; pe[p]+=rec
    for r in db.q('SELECT wbs,wbs_path,actual_start,actual_finish FROM activities WHERE project_id=? AND ((actual_start BETWEEN ? AND ?) OR (actual_finish BETWEEN ? AND ?))', [project_id,lo,hi,lo,hi]):
        p=_prefix(r.get('wbs') or r.get('wbs_path'),3)
        if p:
            d=_date(r.get('actual_finish') or r.get('actual_start')); rec=math.exp(-abs((day-d).days)/10.0) if d else .5; pa[p]+=rec
    out={'prefix_events':dict(pe),'prefix_actuals':dict(pa)};_RECENT_STATE_CACHE[key]=out;return out


def _recent_context(idx,project_id,uid,day)->float:
    if not day:return .5
    p=idx['info'].get(uid,{}).get('prefix') or ''
    if not p:return .35
    rs=_recent_state(project_id,day); ev=float(rs['prefix_events'].get(p,0)); ac=float(rs['prefix_actuals'].get(p,0))
    return min(1.0,.72*(1-math.exp(-ev/1.5))+.28*(1-math.exp(-ac/2.0)))


def _planning_context(ev:dict)->dict:
    """Structured contract for the agent/brain, with conservative offline fallback."""
    supplied=ev.get('planning_context')
    if isinstance(supplied,dict):
        return {'precedence_override_confidence':max(0.0,min(1.0,float(supplied.get('precedence_override_confidence',0) or 0))),
                'reason':supplied.get('reason'),'source':'agent'}
    text=' '+str(ev.get('description') or '').lower()+' '
    strong=('out-of-sequence','out of sequence','approved deviation','precedence waived','sequence waived','ahead of sequence','proceed before','despite predecessor','before predecessor')
    medium=('emergency workfront','emergency','waiver','waived','field instruction','supervisor instruction','although','despite')
    conf=.92 if any(x in text for x in strong) else (.78 if any(x in text for x in medium) else 0.0)
    return {'precedence_override_confidence':conf,'reason':'lexical_fallback' if conf else None,'source':'fallback'}


def _local_pool(idx,uid,day)->set[int]:
    pool={uid};front={uid}
    for _ in range(2):
        nxt=set()
        for x in front:
            nxt|={int(r['pred_uid']) for r in idx['preds'].get(x,[]) if r.get('pred_uid') is not None}
            nxt|={int(r['succ_uid']) for r in idx['succs'].get(x,[]) if r.get('succ_uid') is not None}
        pool|=nxt;front=nxt
    pref=idx['info'].get(uid,{}).get('prefix') or ''
    if pref:
        for x in list(idx['prefix_map'].get(pref,()))[:160]:
            if _temporal_uid(idx,x,day)>.25:pool.add(x)
            if len(pool)>42:break
    return pool


def _beam_future(idx,anchor_uid,day,started_override:set[int],completed_override:set[int],oos_active:set[int],mode:str,depth=3,width=8,cancel_check: Callable[[], None] | None = None)->tuple[float,list[int]]:
    """Repair a short rolling horizon after the observation has changed the world."""
    pool=_local_pool(idx,anchor_uid,day)
    states=[(0.0,[],set(started_override),set(completed_override),set(oos_active),anchor_uid)]
    for step in range(depth):
        _checkpoint(cancel_check)
        new=[]
        for state_position, (util,path,started,done,oos,last) in enumerate(states):
            if state_position % 4 == 0: _checkpoint(cancel_check)
            actions=[]
            # Continuing/finishing already-started work is a valid opportunistic action.
            for uid in started-done:
                if uid not in pool:continue
                a=idx['acts'].get(uid,{})
                ready,_,_=_pred_readiness(idx,uid,day,started,done,'finish')
                if uid in oos and mode=='Progress Override': ready=max(ready,.96)
                elif uid in oos and mode=='Actual Dates': ready=max(ready,.84)
                if ready>=.10:
                    sc=.42*ready+.33*_temporal_uid(idx,uid,day)+.25*_continuity(idx,last,uid)
                    actions.append((sc,uid,'finish'))
            for uid in pool:
                if uid in started or uid in done:continue
                a=idx['acts'].get(uid,{})
                if _completed(a,day):continue
                ready,_,_=_pred_readiness(idx,uid,day,started,done,'start')
                if ready<.10:continue
                temp=_temporal_uid(idx,uid,day);cont=_continuity(idx,last,uid);critical=1.0 if a.get('critical') else .5
                sc=.42*ready+.28*temp+.20*cont+.10*critical
                actions.append((sc,uid,'startfinish'))
            if not actions:
                new.append((util,path,started,done,oos,last));continue
            for sc,uid,kind in sorted(actions,reverse=True)[:width]:
                ns=set(started);nd=set(done);no=set(oos)
                ns.add(uid);nd.add(uid)
                new.append((util+(0.88**step)*sc,path+[uid],ns,nd,no,uid))
        states=sorted(new,key=lambda x:x[0],reverse=True)[:width] or states
    best=max(states,key=lambda x:x[0]);maxu=sum(0.88**s for s in range(depth))
    return min(1.0,best[0]/max(1e-6,maxu)),best[1]


def score_candidate(project_id:str,ev:dict,cand:dict,
                    cancel_check: Callable[[], None] | None = None)->tuple[float,dict]:
    _checkpoint(cancel_check)
    idx=_index(project_id,cancel_check=cancel_check);a=cand.get('activity') or {};uid=int(a.get('uid'));day=_date(ev.get('date'))
    info=event_model.classify_event(ev);state=info.get('state');positive=state in {'finish','progress','start','mixed'}
    started=set();done=set()
    if state in {'start','progress','mixed'}:started.add(uid)
    elif state=='finish':started.add(uid);done.add(uid)
    pre_ready,pn,pdetail=_pred_readiness(idx,uid,day,set(),set(),state if positive else 'start')
    oos=bool(positive and pn and pre_ready<.50)
    mode=_schedule_mode(project_id);ctx=_planning_context(ev);override_conf=float(ctx['precedence_override_confidence'])
    oos_active={uid} if oos else set()
    temp=_temporal_uid(idx,uid,day);recent=_recent_context(idx,project_id,uid,day)
    future,path=_beam_future(idx,uid,day,started,done,oos_active,mode,depth=3,width=7,
                             cancel_check=cancel_check)
    unlock=0.0
    if uid in done:
        for r in idx['succs'].get(uid,[]):
            su=int(r['succ_uid']);rr,_,_=_pred_readiness(idx,su,day,started,done,'start');unlock=max(unlock,rr)
    # Once a positive execution observation is hypothesized, OOS is a *diagnostic*,
    # not evidence that the observation is false. Explicit override context can
    # positively explain the surprise instead of punishing it.
    readiness_credit=.50 if oos and positive else pre_ready
    state_accept=1.0 if positive else .55
    exception_explain=(1.0-pre_ready)*override_conf if oos else 0.0
    coherence=(.12*readiness_credit+.14*temp+.20*recent+.26*future+.08*unlock+.12*state_accept+.08*exception_explain)
    return max(0,min(1,coherence)),{
        'rescheduler_score':coherence,'replan_pre_observation_readiness':pre_ready,'replan_temporal':temp,
        'replan_recent_state':recent,'replan_future_utility':future,'replan_unlock':unlock,
        'replan_oos_detected':oos,'replan_oos_mode':mode,'replan_override_context':override_conf,
        'replan_exception_explained':exception_explain,'replan_path':path,'replan_pred_count':pn,
        'replan_pred_detail':pdetail,'replan_state_assimilated':state,'planning_context_source':ctx.get('source')}


def _recent_prefix_candidates(idx,project_id,day)->dict[int,float]:
    rs=_recent_state(project_id,day) if day else {'prefix_events':{},'prefix_actuals':{}}
    prefixes=set(rs['prefix_events'])|set(rs['prefix_actuals']);out={}
    for p in prefixes:
        strength=min(1.0,.72*(1-math.exp(-float(rs['prefix_events'].get(p,0))/1.5))+.28*(1-math.exp(-float(rs['prefix_actuals'].get(p,0))/2.0)))
        for uid in idx['prefix_map'].get(p,()):out[uid]=max(out.get(uid,0.0),strength)
    return out


def seed_candidates(project_id:str,ev:dict,limit:int=40,
                    cancel_check: Callable[[], None] | None = None)->list[dict]:
    """Independent changed-world attention screen; no WorkfrontRank dependency."""
    _checkpoint(cancel_check)
    idx=_index(project_id,cancel_check=cancel_check);day=_date(ev.get('date'));einfo=event_model.classify_event(ev);action=einfo.get('action');disc=str(ev.get('discipline') or '').lower()
    qaliases=asset_alias_set(extract_asset_tags(ev.get('description'),ev.get('asset_tag'),ev.get('asset_tags')))
    qloc=set(extract_location_tags(ev.get('description'),ev.get('location')))
    qtokens={x for x in re.findall(r'[a-z0-9]+',str(ev.get('description') or '').lower()) if x not in {'completed','complete','started','start','site','unit','area','work','the','and'}}
    recent=_recent_prefix_candidates(idx,project_id,day)
    asset_u=set()
    for al in qaliases:asset_u|=set(idx['asset_map'].get(re.sub(r'[^a-z0-9]','',str(al).lower()),()))
    action_u=set(idx['action_map'].get(action,())) if action else set();loc_u=set()
    for loc in qloc:loc_u|=set(idx['location_map'].get(str(loc).lower(),()))
    disc_u=set()
    if disc:
        for k,v in idx['discipline_map'].items():
            if disc in k or k in disc:disc_u|=set(v)
    pool=set(recent)
    if asset_u:pool|=asset_u
    if action_u and loc_u:pool|=(action_u&loc_u)
    elif action_u and disc_u:pool|=(action_u&disc_u)
    elif action_u:pool|=action_u
    elif loc_u:pool|=loc_u
    elif disc_u:pool|=set(list(disc_u)[:3000])
    if not pool:pool=set(idx['acts'])
    scored=[]
    for position, uid in enumerate(pool):
        if position % 64 == 0: _checkpoint(cancel_check)
        a=idx['acts'].get(uid);inf=idx['info'].get(uid,{})
        if not a:continue
        asset=1.0 if qaliases and qaliases&set(inf.get('aliases') or []) else (.5 if not qaliases else 0.0)
        act=1.0 if action and action==inf.get('action') else (.5 if not action else .05)
        al=set(inf.get('locations') or []);loc=1.0 if qloc and al and qloc&al else (.5 if not qloc else .12)
        ds=1.0 if disc and disc in str(inf.get('discipline') or '') else (.5 if not disc else .2)
        temp=_temporal_uid(idx,uid,day);rc=recent.get(uid,0.0);nt=set(inf.get('name_tokens') or []);lex=len(nt&qtokens)/max(1,len(nt|qtokens)) if qtokens and nt else .5
        score=.26*asset+.18*act+.12*loc+.06*ds+.08*temp+.18*rc+.12*lex
        scored.append((score,uid,rc))
    scored.sort(reverse=True)
    return [{'activity':idx['acts'][uid],'score':score,'features':{'engineering_rank_score':score,'rescheduler_recent_seed':rc},'supporting':['reality-first planner seed'],'conflicting':[],'from_agent':False} for score,uid,rc in scored[:limit]]


def standalone_rank(project_id:str,ev:dict,limit:int=24,
                    cancel_check: Callable[[], None] | None = None)->dict:
    return rerank(project_id,ev,seed_candidates(project_id,ev,limit=40,
                  cancel_check=cancel_check),limit=limit,
                  cancel_check=cancel_check)


def rerank(project_id:str,ev:dict,candidates:list[dict],limit=24,
           cancel_check: Callable[[], None] | None = None)->dict:
    _checkpoint(cancel_check)
    prepared=[]
    for c0 in candidates:
        c={**c0,'features':dict(c0.get('features') or {})};f=c['features'];eng=float(f.get('engineering_rank_score',c.get('score') or 0.0));prepared.append((eng,c))
    prepared.sort(key=lambda x:x[0],reverse=True);ordered=[x[0] for x in prepared]
    margin=(ordered[0]-ordered[1]) if len(ordered)>1 else 1.0;ambiguity=max(0.0,min(1.0,1.0-margin/0.22));alpha=.08+.30*ambiguity
    deep_uids={int(c['activity']['uid']) for _,c in prepared[:12]};out=[]
    for position, (eng,c) in enumerate(prepared):
        if position % 4 == 0: _checkpoint(cancel_check)
        uid=int(c['activity']['uid'])
        if uid in deep_uids:rs,rf=score_candidate(project_id,ev,c,cancel_check=cancel_check)
        else:rs=.5;rf={'rescheduler_score':.5,'replan_skipped':True}
        score=(1.0-alpha)*eng+alpha*rs;c['features'].update(rf);c['features']['rescheduler_authority']=alpha;c['score']=score;out.append(c)
    out.sort(key=lambda c:c['score'],reverse=True)
    return {'candidates':out[:limit],'diagnostics':{'evaluated':len(deep_uids),'planner':'reality-first counterfactual rolling-horizon repair','depth':3,'beam_width':7,'engineering_margin':margin,'planner_authority':alpha,'schedule_mode':_schedule_mode(project_id)}}
