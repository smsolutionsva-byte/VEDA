"""Hierarchical Tree Resolver for VEDA.

Treats the schedule/WBS as a taxonomy rather than a flat label list.  The tree
is virtual when a source schedule does not persist summary rows: WBS path
segments become parent nodes and activities become leaves.

The resolver answers two related questions:
  1. Which branch/leaf best contains this observation?
  2. Is the observation leaf-sized, finer than a leaf, or an aggregate over
     several sibling leaves?

This is an experimental expert.  It never writes schedule data.
"""
from __future__ import annotations

import math, re
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable

from .. import db
from ..retrieval.entities import extract_asset_tags, asset_alias_set, extract_location_tags
from . import events as event_model

_CACHE: dict[str, dict] = {}


def _checkpoint(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check:
        cancel_check()


def _date(v: Any):
    if not v: return None
    try: return datetime.strptime(str(v).split('T')[0], '%Y-%m-%d').date()
    except Exception: return None


def _norm(s: Any) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(s or '').lower()).strip()


def _path_parts(a: dict) -> tuple[str, ...]:
    p=str(a.get('wbs_path') or '').strip()
    if p:
        return tuple(x.strip() for x in re.split(r'\s*>\s*|\s*/\s*',p) if x.strip())
    w=str(a.get('wbs') or '').strip()
    return tuple(x.strip() for x in w.split('.') if x.strip())


def _phase(a: dict) -> str | None:
    text=' '.join(str(a.get(k) or '') for k in ('wbs_path','name'))
    return event_model.detect_phase(text, event_model.detect_action(a.get('name')).get('action')).get('phase')


def _discipline_from_path(a: dict) -> str:
    p=_path_parts(a)
    return p[-1].lower() if p else ''


def _signature(project_id: str) -> tuple:
    sig=db.q1('SELECT COUNT(*) c, COALESCE(MAX(created_at),0) u FROM activities WHERE project_id=?',[project_id]) or {'c':0,'u':0}
    return (int(sig.get('c') or 0),float(sig.get('u') or 0.0))


def _index(project_id: str, cancel_check: Callable[[], None] | None = None) -> dict:
    _checkpoint(cancel_check)
    # score_activity() calls this once per candidate, so the freshness probe is
    # held briefly rather than issued tens of thousands of times per analysis.
    key=db.cached_probe(('tree_index', project_id), lambda: _signature(project_id))
    old=_CACHE.get(project_id)
    if old and old.get('sig')==key: return old
    acts=db.q('SELECT * FROM activities WHERE project_id=? AND is_summary=0',[project_id])
    by_uid={int(a['uid']):a for a in acts if a.get('uid') is not None}
    nodes=defaultdict(lambda:{'children':set(),'leaves':set(),'depth':0,'label':''})
    asset_map=defaultdict(set); token_map=defaultdict(set); name_token_map=defaultdict(set); location_map=defaultdict(set); branch_map=defaultdict(set)
    info={}
    for position, a in enumerate(acts):
        if position % 128 == 0: _checkpoint(cancel_check)
        uid=int(a['uid']); parts=_path_parts(a)
        parent=()
        for d,part in enumerate(parts,1):
            cur=parts[:d]; nodes[cur]['depth']=d; nodes[cur]['label']=part; nodes[cur]['leaves'].add(uid)
            nodes[parent]['children'].add(cur); nodes[parent]['leaves'].add(uid); parent=cur
            for tok in re.findall(r'[a-z0-9]+',_norm(part)):
                if len(tok)>1: token_map[tok].add(uid)
        tags=extract_asset_tags(a.get('name'),a.get('custom_json'),a.get('wbs_path'))
        aliases=asset_alias_set(tags)
        for al in aliases: asset_map[_norm(al).replace(' ','')].add(uid)
        action=event_model.detect_action(a.get('name')).get('action')
        ph=_phase(a); disc=_discipline_from_path(a)
        locs=set(extract_location_tags(a.get('wbs_path'),a.get('name')))
        for loc in locs: location_map[str(loc).lower()].add(uid)
        name_tokens=set(re.findall(r'[a-z0-9]+',_norm(a.get('name'))))
        for tok in name_tokens:
            if len(tok)>2: name_token_map[tok].add(uid)
        info[uid]={'parts':parts,'aliases':aliases,'action':action,'phase':ph,'discipline':disc,'locations':locs,'name_tokens':name_tokens}
        # Materialized path prefixes are useful sibling/branch retrieval keys.
        for d in range(1,len(parts)+1): branch_map[parts[:d]].add(uid)
    out={'sig':key,'activities':by_uid,'nodes':nodes,'asset_map':asset_map,'token_map':token_map,'name_token_map':name_token_map,'location_map':location_map,'branch_map':branch_map,'info':info}
    _CACHE[project_id]=out; return out


def _evidence(ev: dict) -> dict:
    tags=extract_asset_tags(ev.get('description'),ev.get('asset_tag'),ev.get('asset_tags'))
    aliases=asset_alias_set(tags)
    locs=set(extract_location_tags(ev.get('description'),ev.get('location'),ev.get('wbs'),ev.get('wbs_path')))
    einfo=event_model.classify_event(ev)
    text=_norm(' '.join(str(ev.get(k) or '') for k in ('description','location','wbs','wbs_path','discipline')))
    toks=set(re.findall(r'[a-z0-9]+',text))
    return {'tags':tags,'aliases':aliases,'locations':locs,'action':einfo.get('action'),'phase':einfo.get('phase'),
            'discipline':_norm(ev.get('discipline')),'tokens':toks,'date':_date(ev.get('date'))}


def candidate_uids(project_id: str, ev: dict, limit: int=160,
                   cancel_check: Callable[[], None] | None = None) -> list[int]:
    """Hierarchical candidate generation independent of semantic retrieval."""
    _checkpoint(cancel_check)
    idx=_index(project_id,cancel_check=cancel_check); q=_evidence(ev); votes=defaultdict(float)
    # Exact/safe asset identity seeds entire leaf families.
    for al in q['aliases']:
        for uid in idx['asset_map'].get(_norm(al).replace(' ',''),()): votes[uid]+=4.0
    # Hierarchy/location/discipline words seed branches.
    important={t for t in q['tokens'] if t not in {'project','work','completed','complete','started','start','final','site','unit','area'}}
    for position, t in enumerate(important):
        if position % 16 == 0: _checkpoint(cancel_check)
        us=idx['token_map'].get(t,())
        if len(us)<=2500:
            for uid in us: votes[uid]+=1.0
        # Leaf-name evidence resolves siblings after the branch is identified.
        nus=idx['name_token_map'].get(t,())
        if len(nus)<=3000:
            for uid in nus: votes[uid]+=1.35
    # Normalized branch identity (unit:5, area:a, rack:03) is stronger than token overlap.
    for loc in q['locations']:
        for uid in idx['location_map'].get(str(loc).lower(),()): votes[uid]+=3.0
        for t in re.findall(r'[a-z0-9]+',_norm(loc)):
            if len(t)>1:
                for uid in idx['token_map'].get(t,()): votes[uid]+=0.7
    if not votes:
        return []
    return [u for u,_ in sorted(votes.items(),key=lambda kv:kv[1],reverse=True)[:limit]]


def _temporal(qday, a:dict) -> float:
    if not qday: return .5
    s=_date(a.get('actual_start') or a.get('start') or a.get('baseline_start'))
    f=_date(a.get('actual_finish') or a.get('finish') or a.get('baseline_finish'))
    if s and f:
        if s <= qday <= f: return 1.0
        days=min(abs((qday-s).days),abs((qday-f).days))
        return max(.05,math.exp(-days/45.0))
    return .5


def _loc_score(q_locs:set[str], a_locs:set[str], parts:tuple[str,...], qtokens:set[str]) -> float:
    if not q_locs:
        # Weak hierarchy word overlap when no normalized location was extracted.
        pt=set(re.findall(r'[a-z0-9]+',_norm(' '.join(parts))))
        overlap=len(pt & qtokens)
        return min(1.0, overlap/3.0) if overlap else .5
    if not a_locs: return .15
    inter=q_locs & a_locs
    if inter: return min(1.0,.65+.18*len(inter))
    # Some extractors use 'area a' while paths separate words; compare normalized tokens.
    qa=set(re.findall(r'[a-z0-9]+',_norm(' '.join(q_locs))))
    aa=set(re.findall(r'[a-z0-9]+',_norm(' '.join(a_locs))))
    j=len(qa&aa)/max(1,len(qa|aa))
    return .15+.65*j


def score_activity(project_id:str, ev:dict, uid:int, q:dict|None=None,
                   cancel_check: Callable[[], None] | None = None) -> tuple[float,dict]:
    _checkpoint(cancel_check)
    idx=_index(project_id,cancel_check=cancel_check); a=idx['activities'].get(int(uid)); inf=idx['info'].get(int(uid),{})
    if not a: return 0.0,{}
    q=q or _evidence(ev)
    a_alias=set(inf.get('aliases') or []); exact=1.0 if q['aliases'] and (q['aliases'] & a_alias) else (0.5 if not q['aliases'] else 0.0)
    action=.5 if not q['action'] else (1.0 if inf.get('action')==q['action'] else .05)
    phase=.5 if not q['phase'] else (1.0 if inf.get('phase')==q['phase'] else .1)
    disc=.5 if not q['discipline'] else (1.0 if q['discipline'] in _norm(inf.get('discipline')) else .15)
    loc=_loc_score(q['locations'],set(inf.get('locations') or []),inf.get('parts') or (),q['tokens'])
    temp=_temporal(q['date'],a)
    # Branch coherence is deliberately separate from leaf identity.  It rewards
    # evidence that consistently points to the same ancestors.
    pt=set(re.findall(r'[a-z0-9]+',_norm(' '.join(inf.get('parts') or ()))))
    branch=min(1.0,len(pt&q['tokens'])/max(1,min(5,len(pt)))) if q['tokens'] else .5
    nt=set(inf.get('name_tokens') or []); qt={x for x in q['tokens'] if x not in {'completed','complete','started','start','site','unit','area','work'}}
    leaf=(len(nt&qt)/max(1,len(nt|qt))) if qt and nt else .5
    # Parent/branch context chooses the family; leaf text/action chooses the sibling.
    score=.25*exact+.20*loc+.14*action+.09*phase+.06*disc+.10*branch+.10*leaf+.06*temp
    return max(0,min(1,score)),{'tree_score':score,'tree_asset':exact,'tree_location':loc,'tree_action':action,
        'tree_phase':phase,'tree_discipline':disc,'tree_branch':branch,'tree_leaf_text':leaf,'tree_temporal':temp,'tree_path':list(inf.get('parts') or ())}


def rerank(project_id:str, ev:dict, engineering_candidates:list[dict], limit:int=24,
           cancel_check: Callable[[], None] | None = None) -> dict:
    _checkpoint(cancel_check)
    idx=_index(project_id,cancel_check=cancel_check); q=_evidence(ev); by_uid={int(c['activity']['uid']):c for c in engineering_candidates if (c.get('activity') or {}).get('uid') is not None}
    uids=list(by_uid)
    for uid in candidate_uids(project_id,ev,160,cancel_check=cancel_check):
        if uid not in by_uid: uids.append(uid)
    out=[]
    for position, uid in enumerate(uids):
        if position % 16 == 0: _checkpoint(cancel_check)
        ts,tf=score_activity(project_id,ev,uid,q=q,cancel_check=cancel_check)
        if uid in by_uid:
            c={**by_uid[uid], 'features':dict(by_uid[uid].get('features') or {})}
            eng=float(c.get('score') or 0.0)
            # Tree is a challenger expert, not a replacement for strong leaf
            # identity.  This blend is tuned on DEV only in the benchmark.
            score=.52*eng+.48*ts
        else:
            a=idx['activities'][uid]
            c={'activity':a,'features':{},'supporting':['hierarchical tree candidate'],'conflicting':[],'from_agent':False}
            score=.72*ts
        c['features'].update(tf); c['score']=score; out.append(c)
    out.sort(key=lambda c:c['score'],reverse=True)
    return {'candidates':out[:limit],'diagnostics':{'generated':len(uids),'virtual_nodes':len(idx['nodes'])}}


def relation_hypothesis(project_id:str, ev:dict, tree_candidates:list[dict]) -> dict:
    """Tree-native granularity/aggregate relation inference."""
    from . import reality_graph
    idx=_index(project_id); q=_evidence(ev)
    old=ev.get('source_activity_uid') or ev.get('historical_activity_uid')
    if old is not None:
        rows=db.q('SELECT to_uid,relation,score FROM activity_lineage WHERE project_id=? AND from_uid=? ORDER BY score DESC',[project_id,old])
        split=[int(r['to_uid']) for r in rows if r.get('relation')=='split_candidate' and r.get('to_uid') is not None]
        if len(split)>=2:return {'relation':reality_graph.REL_SPLIT_ACROSS,'uids':split,'reason':'tree lineage split'}
    aliases=q['aliases']
    if aliases:
        per_asset=[]; all_hits=[]
        for tag in q['tags']:
            aa=asset_alias_set([tag]); hits=[]
            for al in aa: hits.extend(idx['asset_map'].get(_norm(al).replace(' ',''),()))
            hits=list(dict.fromkeys(map(int,hits)))
            # Prefer same action and branch context for each physical asset.
            if hits:
                scored=sorted(((score_activity(project_id,ev,u,q=q)[0],u) for u in hits),reverse=True)
                per_asset.append(scored[0][1]); all_hits.extend(hits)
        unique=list(dict.fromkeys(per_asset))
        if len(q['tags'])>1 and len(unique)>=2:
            return {'relation':reality_graph.REL_AGGREGATES,'uids':unique,'reason':'multiple explicit field assets resolve to sibling/related leaves'}
        # Explicit asset entirely absent from the tree = new scope.
        if not all_hits:
            return {'relation':reality_graph.REL_NEW_SCOPE,'uids':[],'reason':'explicit asset absent from schedule tree'}
    if tree_candidates:
        top=tree_candidates[0]; uid=int(top['activity']['uid']); inf=idx['info'].get(uid,{})
        # Fine physical event mapped to a coarse activity: schedule leaf has no
        # physical asset identity even though field event does.
        if aliases and not inf.get('aliases'):
            return {'relation':reality_graph.REL_PART_OF,'uids':[uid],'reason':'field event is finer than selected schedule leaf'}
    return reality_graph.relation_hypothesis(project_id,ev,tree_candidates)
