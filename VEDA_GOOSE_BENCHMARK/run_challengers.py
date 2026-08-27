#!/usr/bin/env python3
from __future__ import annotations
import argparse,copy,json,math,statistics,time
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent; ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
from run import setup,load_jsonl,semantic_order,rank_of,set_equal


def metrics(records,key):
    rr=[r for r in records if r['expected_uid'] is not None]
    def rec(k):return sum(1 for r in rr if r.get(key) is not None and r[key]<=k)/max(1,len(rr))
    mrr=sum(1/r[key] if r.get(key) else 0 for r in rr)/max(1,len(rr))
    return {'n':len(rr),'top1':rec(1),'r3':rec(3),'r5':rec(5),'r10':rec(10),'mrr':mrr}

def merge_candidates(*lists):
    d={}
    for ls in lists:
        for c in ls or []:
            uid=int(c['activity']['uid'])
            if uid not in d or float(c.get('score') or 0)>float(d[uid].get('score') or 0): d[uid]=copy.deepcopy(c)
    return list(d.values())

def run(split,backend,output,limit=None,offset=0):
    from veda.retrieval import engine
    from veda.resolution import reality_graph,tree_resolver,rescheduler
    tmp,pid,idx,index_s,backend_name=setup(split,backend)
    cases=load_jsonl(HERE/'data'/split/'cases.jsonl')
    if offset:cases=cases[offset:]
    if limit:cases=cases[:limit]
    recs=[];qts=[];tts=[];rts=[]
    for n,c in enumerate(cases,1):
        ev=dict(c['evidence']);ev.update({'id':c['id'],'project_id':pid,'state':'new'})
        if c['evidence'].get('historical_activity_uid') is not None:ev['historical_activity_uid']=c['evidence']['historical_activity_uid']
        t=time.perf_counter();res=engine.hybrid_search(pid,ev,top_k=24,ensure_index=False,use_workfront=True,use_adaptive_gate=True);qts.append(time.perf_counter()-t)
        base=res.get('pre_workfront_candidates') or []; wf=res.get('workfront_candidates') or []; adaptive=res.get('adaptive_candidates') or res.get('candidates') or []
        sem=semantic_order(base)
        t=time.perf_counter();tr=tree_resolver.rerank(pid,ev,base,limit=24);tts.append(time.perf_counter()-t);tree=tr['candidates']
        # Planner gets the same semantic + execution-frontier candidate universe already available to VEDA.
        plan_pool=merge_candidates(base,wf)
        t=time.perf_counter();pr=rescheduler.rerank(pid,ev,plan_pool,limit=24);rts.append(time.perf_counter()-t);planner=pr['candidates']
        expected=c.get('expected_uid')
        rel0=reality_graph.relation_hypothesis(pid,ev,adaptive)
        trel=tree_resolver.relation_hypothesis(pid,ev,tree)
        recs.append({'id':c['id'],'category':c['category'],'edge_case':c['edge_case'],'expected_uid':expected,'expected_uids':c.get('expected_uids') or [],'expected_relation':c['expected_relation'],
            'semantic_rank':rank_of(sem,expected),'engineering_rank':rank_of(base,expected),'workfront_rank':rank_of(wf,expected),'adaptive_rank':rank_of(adaptive,expected),'tree_rank':rank_of(tree,expected),'rescheduler_rank':rank_of(planner,expected),
            'semantic_top':int(sem[0]['activity']['uid']) if sem else None,'engineering_top':int(base[0]['activity']['uid']) if base else None,'workfront_top':int(wf[0]['activity']['uid']) if wf else None,'adaptive_top':int(adaptive[0]['activity']['uid']) if adaptive else None,'tree_top':int(tree[0]['activity']['uid']) if tree else None,'rescheduler_top':int(planner[0]['activity']['uid']) if planner else None,
            'base_relation':rel0.get('relation'),'base_relation_uids':rel0.get('uids') or [],'tree_relation':trel.get('relation'),'tree_relation_uids':trel.get('uids') or [],
            'base_relation_ok':rel0.get('relation')==c['expected_relation'] and (not c.get('expected_uids') or set_equal(rel0.get('uids'),c.get('expected_uids'))),
            'tree_relation_ok':trel.get('relation')==c['expected_relation'] and (not c.get('expected_uids') or set_equal(trel.get('uids'),c.get('expected_uids'))),
            'tree_diag':tr.get('diagnostics'),'rescheduler_diag':pr.get('diagnostics')})
        if n%10==0:print(f'{split}: {n}/{len(cases)}',flush=True)
    keys=['semantic_rank','engineering_rank','workfront_rank','adaptive_rank','tree_rank','rescheduler_rank']
    variants={k:metrics(recs,k) for k in keys}
    cats={}
    for cat in sorted({r['category'] for r in recs}):
        rr=[r for r in recs if r['category']==cat and r['expected_uid'] is not None]
        cats[cat]={'n':len(rr)}
        for k in keys:cats[cat][k]=sum(1 for x in rr if x.get(k)==1)/max(1,len(rr)) if rr else None
    rel=[r for r in recs if r['expected_relation']!='EXACT']
    relcats={}
    for rt in sorted({r['expected_relation'] for r in rel}):
        rr=[r for r in rel if r['expected_relation']==rt]
        relcats[rt]={'n':len(rr),'base':sum(x['base_relation_ok'] for x in rr)/len(rr),'tree':sum(x['tree_relation_ok'] for x in rr)/len(rr)}
    def lat(a):
        if not a:return {'median':0,'p95':0}
        s=sorted(a);return {'median':statistics.median(s)*1000,'p95':s[max(0,math.ceil(.95*len(s))-1)]*1000}
    summary={'split':split,'activities':idx.get('activities'),'cases':len(recs),'backend':backend_name,'variants':variants,'categories':cats,
             'relation_accuracy':{'base':sum(x['base_relation_ok'] for x in rel)/max(1,len(rel)),'tree':sum(x['tree_relation_ok'] for x in rel)/max(1,len(rel)),'n':len(rel)},'relation_categories':relcats,
             'latency_ms':{'base_query':lat(qts),'tree_extra':lat(tts),'rescheduler_extra':lat(rts)},'index_seconds':index_s}
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    (out/f'{split}_challenger_results.json').write_text(json.dumps({'summary':summary,'records':recs},indent=2),encoding='utf-8')
    names={'semantic_rank':'Semantic','engineering_rank':'EngineeringRank','workfront_rank':'WorkfrontRank','adaptive_rank':'Adaptive v0.3','tree_rank':'TreeRank','rescheduler_rank':'Rescheduler'}
    md=[f'# VEDA challenger benchmark — {split.upper()}','',f'- Activities: **{summary["activities"]:,}**',f'- Cases: **{len(recs)}**',f'- Backend: **{backend_name}**','',
        '## Exact-identity ranking','| Expert | Top-1 | R@3 | R@5 | R@10 | MRR |','|---|---:|---:|---:|---:|---:|']
    for k in keys:
        m=variants[k];md.append(f'| {names[k]} | {m["top1"]:.2%} | {m["r3"]:.2%} | {m["r5"]:.2%} | {m["r10"]:.2%} | {m["mrr"]:.4f} |')
    md+=['','## Category Top-1','| Category | N | Semantic | Engineering | Workfront | Adaptive | Tree | Rescheduler |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for cat,v in cats.items():
        if not v['n']:continue
        md.append(f'| {cat} | {v["n"]} | {v["semantic_rank"]:.1%} | {v["engineering_rank"]:.1%} | {v["workfront_rank"]:.1%} | {v["adaptive_rank"]:.1%} | {v["tree_rank"]:.1%} | {v["rescheduler_rank"]:.1%} |')
    md+=['','## Set/granularity/revision relations',f'- Existing Reality Graph: **{summary["relation_accuracy"]["base"]:.1%}**',f'- Tree relation resolver: **{summary["relation_accuracy"]["tree"]:.1%}**','',
         '| Relation | N | Existing | Tree |','|---|---:|---:|---:|']
    for rt,v in relcats.items():md.append(f'| {rt} | {v["n"]} | {v["base"]:.1%} | {v["tree"]:.1%} |')
    md+=['','## Added latency',f'- Tree median: **{summary["latency_ms"]["tree_extra"]["median"]:.1f} ms**; p95 **{summary["latency_ms"]["tree_extra"]["p95"]:.1f} ms**',f'- Rescheduler median: **{summary["latency_ms"]["rescheduler_extra"]["median"]:.1f} ms**; p95 **{summary["latency_ms"]["rescheduler_extra"]["p95"]:.1f} ms**']
    (out/f'{split}_challenger_report.md').write_text('\n'.join(md),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)
    tmp.cleanup()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--split',default='dev');ap.add_argument('--backend',default='hash');ap.add_argument('--output',default=str(HERE/'challenger_reports'));ap.add_argument('--limit',type=int);ap.add_argument('--offset',type=int,default=0)
    a=ap.parse_args();run(a.split,a.backend,a.output,a.limit,a.offset)
