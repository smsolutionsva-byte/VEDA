#!/usr/bin/env python3
from __future__ import annotations
import argparse, copy, csv, hashlib, json, math, os, statistics, sys, tempfile, time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))

def load_csv(path):
    with path.open(encoding='utf-8',newline='') as f: return list(csv.DictReader(f))

def load_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]

def iv(v):
    if v in (None,''): return None
    try:return int(v)
    except:return v

def fv(v):
    if v in (None,''): return None
    try:return float(v)
    except:return v

def setup(split, backend):
    tmp=tempfile.TemporaryDirectory(prefix=f'veda-goose-{split}-')
    os.environ['VEDA_DATA_DIR']=tmp.name
    os.environ['VEDA_EMBEDDING_BACKEND']=backend
    os.environ['VEDA_WORKFRONT_RANK']='0'
    from veda import db, config
    from veda.retrieval import engine, embeddings
    # Benchmark isolation: config is imported before setup() by retrieval modules,
    # so rebinding VEDA_DATA_DIR alone is insufficient. Force every run/shard to
    # its own temporary SQLite/runtime directories without touching resolver logic.
    from pathlib import Path as _Path
    config.DATA_DIR = _Path(tmp.name)
    config.DB_PATH = config.DATA_DIR / 'veda.db'
    config.PROJECTS_DIR = config.DATA_DIR / 'projects'
    config.OUTPUTS_DIR = config.DATA_DIR / 'outputs'
    old_conn = getattr(db._local, 'conn', None)
    if old_conn is not None:
        old_conn.close()
        delattr(db._local, 'conn')
    db.init_db()
    pid=f'goose-{split}'
    db.insert('projects',{'id':pid,'name':f'Goose benchmark {split}','client':'Synthetic OIL/SIH26122','location':'Synthetic'})
    snap=db.insert('schedule_snapshots',{'project_id':pid,'revision':2,'status_date':'2026-08-27','data_date':'2026-08-27','is_current':1,
                                         'info_json':db.jdumps({'out_of_sequence_schedule_type':'Progress Override'})})
    sd=HERE/'data'/split
    rows=load_csv(sd/'schedule.csv')
    conn=db.connect(); now=db.now()
    vals=[]
    for i,r in enumerate(rows):
        vals.append((f'act-{split}-{i}',pid,snap,iv(r['uid']),r['display_id'],r['name'],r['wbs'],r['wbs_path'],0,0,r['status'],r['start'],r['finish'],r['actual_start'] or None,r['actual_finish'] or None,
                     r['baseline_start'],r['baseline_finish'],r['custom_json'],now))
    conn.executemany("INSERT INTO activities (id,project_id,snapshot_id,uid,display_id,name,wbs,wbs_path,is_summary,is_milestone,status,start,finish,actual_start,actual_finish,baseline_start,baseline_finish,custom_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",vals)
    rels=load_csv(sd/'relationships.csv'); rv=[]
    for i,r in enumerate(rels):
        rv.append((f'rel-{split}-{i}',pid,snap,iv(r['pred_uid']),iv(r['succ_uid']),r.get('type') or 'FS',fv(r.get('lag_days')) or 0.0,iv(r.get('driving')) or 0,now))
    conn.executemany("INSERT INTO relationships (id,project_id,snapshot_id,pred_uid,succ_uid,type,lag_days,driving,created_at) VALUES (?,?,?,?,?,?,?,?,?)",rv)
    hist=load_csv(sd/'history_events.csv'); hv=[]
    for i,r in enumerate(hist):
        hv.append((f'ee-{split}-{i}',pid,f'hist|{i}',iv(r['activity_uid']),r.get('action_type'),r.get('event_state'),r.get('event_date'),1.0,'observed',1,'SYNTHETIC',now,now))
    if hv:
        conn.executemany("INSERT INTO execution_events (id,project_id,canonical_key,activity_uid,action_type,event_state,event_date,confidence,state,source_count,provenance,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",hv)
    lineage=load_csv(sd/'lineage.csv'); lv=[]
    for i,r in enumerate(lineage):
        lv.append((f'lin-{split}-{i}',pid,1,2,iv(r['from_uid']),iv(r['to_uid']),r['relation'],fv(r['score']), 'synthetic_revision_split', now))
    if lv:
        conn.executemany("INSERT INTO activity_lineage (id,project_id,from_revision,to_revision,from_uid,to_uid,relation,score,basis,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",lv)
    conn.commit()
    t=time.perf_counter(); idx=engine.index_project(pid,force=True); index_s=time.perf_counter()-t
    return tmp,pid,idx,index_s,embeddings.get_backend().name

def semantic_order(cands):
    out=copy.deepcopy(cands)
    for c in out:
        f=c.get('features') or {}
        c['_semantic']=.55*float(f.get('rerank',0))+.25*float(f.get('dense',0))+.12*float(f.get('sparse',0))+.08*float(f.get('bge_sparse',0))
    out.sort(key=lambda x:x['_semantic'],reverse=True)
    return out

def rank_of(cands, expected):
    if expected is None:return None
    for i,c in enumerate(cands,1):
        if int(c['activity']['uid'])==int(expected): return i
    return None

def metrics(records,variant):
    eligible=[r for r in records if r['expected_uid'] is not None]
    def rec(k): return sum(1 for r in eligible if r[variant] is not None and r[variant]<=k)/max(1,len(eligible))
    mrr=sum(1/r[variant] if r[variant] else 0 for r in eligible)/max(1,len(eligible))
    return {'n':len(eligible),'top1':rec(1),'r3':rec(3),'r5':rec(5),'r10':rec(10),'mrr':mrr}

def set_equal(a,b): return set(map(int,a or []))==set(map(int,b or []))

def run(split, backend, output, limit=None, offset=0):
    from veda.retrieval import engine
    from veda.resolution import reality_graph
    from veda import db
    tmp,pid,idx,index_s,backend_name=setup(split,backend)
    cases=load_jsonl(HERE/'data'/split/'cases.jsonl')
    if offset: cases=cases[int(offset):]
    if limit: cases=cases[:int(limit)]
    streams=load_jsonl(HERE/'data'/split/'reality_streams.jsonl')
    records=[]; times={'query':[]}
    for n,c in enumerate(cases,1):
        ev=dict(c['evidence']); ev.update({'id':c['id'],'project_id':pid,'state':'new'})
        # historical UID is a first-class top-level field for lineage reasoning
        if c['evidence'].get('historical_activity_uid') is not None:
            ev['historical_activity_uid']=c['evidence']['historical_activity_uid']
        t=time.perf_counter(); wf=engine.hybrid_search(pid,ev,top_k=24,ensure_index=False,use_workfront=True,use_adaptive_gate=True); query_elapsed=time.perf_counter()-t; times['query'].append(query_elapsed)
        # The engine returns the production VEDA ranking *before* WorkfrontRank
        # from the same retrieval pass, preventing a second 10k-activity scan.
        basec=wf.get('pre_workfront_candidates') or []
        sem=semantic_order(basec)
        if query_elapsed>1.0:
            print(f'  slow {c["id"]} {c["category"]}: query={query_elapsed:.2f}s', flush=True)
        wfc=wf.get('workfront_candidates') or []
        adc=wf.get('adaptive_candidates') or wf.get('candidates') or []
        gate=((wf.get('diagnostics') or {}).get('adaptive_execution_gate') or {})
        expected=c.get('expected_uid')
        rel=reality_graph.relation_hypothesis(pid,ev,adc)
        records.append({'id':c['id'],'category':c['category'],'edge_case':c['edge_case'],'expected_uid':expected,'expected_uids':c.get('expected_uids') or [],
                        'expected_relation':c['expected_relation'],'semantic_rank':rank_of(sem,expected),'veda_rank':rank_of(basec,expected),'workfront_rank':rank_of(wfc,expected),'adaptive_rank':rank_of(adc,expected),
                        'semantic_top':int(sem[0]['activity']['uid']) if sem else None,'veda_top':int(basec[0]['activity']['uid']) if basec else None,'workfront_top':int(wfc[0]['activity']['uid']) if wfc else None,'adaptive_top':int(adc[0]['activity']['uid']) if adc else None,
                        'relation':rel.get('relation'),'relation_uids':rel.get('uids') or [],
                        'relation_ok':rel.get('relation')==c['expected_relation'] and (not c.get('expected_uids') or set_equal(rel.get('uids'),c.get('expected_uids'))),
                        'workfront_features':(wfc[0].get('features') or {}) if wfc else {},'gate_route':gate.get('route'),'gate_p_workfront':gate.get('p_workfront'),'gate_contributions':gate.get('contributions') or [],'notes':c.get('notes')})
        if n%25==0: print(f'{split}: {n}/{len(cases)}')

    stream_results=[]
    for s in streams:
        g=reality_graph.stream_events(s['observations']); exp=s['expect']; sm=g['summary']; ok=True; reasons=[]
        if 'min_corroborations' in exp and sm['corroborations']<exp['min_corroborations']:ok=False; reasons.append('corroboration')
        if 'min_supersessions' in exp and sm['supersessions']<exp['min_supersessions']:ok=False; reasons.append('supersession')
        if 'min_contradictions' in exp and sm['contradictions']<exp['min_contradictions']:ok=False; reasons.append('contradiction')
        if 'min_canonical_events' in exp and sm['canonical_events']<exp['min_canonical_events']:ok=False; reasons.append('event_count_low')
        if 'max_canonical_events' in exp and sm['canonical_events']>exp['max_canonical_events']:ok=False; reasons.append('event_count_high')
        if 'preserve_locations' in exp:
            locs={x for e in g['events'] for x in e.get('locations') or []}
            if not set(exp['preserve_locations']).issubset(locs):ok=False; reasons.append('location_history')
        if 'replacement_old' in exp:
            repl=[e.get('replacement') for e in g['events'] if e.get('replacement')]
            if not any(x and x.get('old_asset')==exp['replacement_old'] and x.get('new_asset')==exp['replacement_new'] for x in repl):ok=False; reasons.append('replacement_identity')
        stream_results.append({'id':s['id'],'kind':s['kind'],'ok':ok,'reasons':reasons,'summary':sm,'events':g['events'],'edges':g['edges']})

    variants={v:metrics(records,v) for v in ['semantic_rank','veda_rank','workfront_rank','adaptive_rank']}
    relation_cases=[r for r in records if r['expected_relation']!='EXACT']
    exact_rel=[r for r in records if r['expected_relation']=='EXACT']
    cats={}
    for cat in sorted({r['category'] for r in records}):
        rr=[r for r in records if r['category']==cat and r['expected_uid'] is not None]
        cats[cat]={'n':len(rr)}
        for v in ['semantic_rank','veda_rank','workfront_rank','adaptive_rank']:
            cats[cat][v]=sum(1 for x in rr if x[v]==1)/max(1,len(rr)) if rr else None
    summary={'split':split,'activities':idx.get('activities'),'relationships':len(load_csv(HERE/'data'/split/'relationships.csv')),
             'resolver_cases':len(records),'backend':backend_name,'index_seconds':index_s,'variants':variants,'categories':cats,
             'relation_accuracy':sum(r['relation_ok'] for r in relation_cases)/max(1,len(relation_cases)),'relation_cases':len(relation_cases),
             'reality_stream_accuracy':sum(r['ok'] for r in stream_results)/max(1,len(stream_results)),'reality_streams':len(stream_results),
             'latency_ms':{'combined_query_median':statistics.median(times['query'])*1000,'combined_query_p95':sorted(times['query'])[max(0,math.ceil(.95*len(times['query']))-1)]*1000}}
    out=Path(output); out.mkdir(parents=True,exist_ok=True)
    payload={'summary':summary,'records':records,'reality_streams':stream_results}
    (out/f'{split}_results.json').write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')
    md=[f'# VEDA Reality Graph + WorkfrontRank — {split.upper()} benchmark','',f'- Activities: **{summary["activities"]:,}**',f'- Resolver cases: **{len(records)}**',f'- Reality streams: **{len(stream_results)}**',f'- Backend: **{backend_name}**',f'- Index time: **{index_s:.2f}s**','',
        '## Resolver comparison','| Variant | Top-1 | R@3 | R@5 | R@10 | MRR |','|---|---:|---:|---:|---:|---:|']
    names={'semantic_rank':'Semantic-only','veda_rank':'VEDA engineering rank','workfront_rank':'VEDA + WorkfrontRank','adaptive_rank':'VEDA v0.3 Adaptive ExecutionRank'}
    for v,m in variants.items(): md.append(f'| {names[v]} | {m["top1"]:.1%} | {m["r3"]:.1%} | {m["r5"]:.1%} | {m["r10"]:.1%} | {m["mrr"]:.4f} |')
    md += ['','## Hard-category Top-1','| Category | N | Semantic | VEDA | + WorkfrontRank | Adaptive |','|---|---:|---:|---:|---:|---:|']
    for cat,v in cats.items():
        if not v['n']: continue
        md.append(f'| {cat} | {v["n"]} | {v["semantic_rank"]:.1%} | {v["veda_rank"]:.1%} | {v["workfront_rank"]:.1%} | {v["adaptive_rank"]:.1%} |')
    md += ['','## Reality-first behavior',f'- Set/granularity/revision relation accuracy: **{summary["relation_accuracy"]:.1%}** ({summary["relation_cases"]} cases)',f'- Longitudinal event-stream accuracy: **{summary["reality_stream_accuracy"]:.1%}** ({summary["reality_streams"]} streams)','',
           '## Latency',f'- One-pass semantic + WorkfrontRank median: **{summary["latency_ms"]["combined_query_median"]:.1f} ms**',f'- One-pass p95: **{summary["latency_ms"]["combined_query_p95"]:.1f} ms**','',
           '## First failures','| ID | Category | Expected | Semantic | VEDA | Workfront | Adaptive | Gate | Relation |','|---|---|---:|---:|---:|---:|---:|---|---|']
    bad=[r for r in records if (r['expected_uid'] is not None and r['adaptive_rank']!=1) or not r['relation_ok']]
    for r in bad[:50]: md.append(f'| {r["id"]} | {r["category"]} | {r["expected_uid"]} | {r["semantic_rank"]} | {r["veda_rank"]} | {r["workfront_rank"]} | {r["adaptive_rank"]} | {r.get("gate_route")} | {r["relation"]} |')
    sbad=[r for r in stream_results if not r['ok']]
    if sbad:
        md += ['','### Reality-stream failures']+[f'- {r["id"]}: {", ".join(r["reasons"])}' for r in sbad]
    (out/f'{split}_report.md').write_text('\n'.join(md),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    tmp.cleanup()
    return summary

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--split',default='dev'); ap.add_argument('--backend',default='hash'); ap.add_argument('--output',default=str(HERE/'reports')); ap.add_argument('--limit',type=int); ap.add_argument('--offset',type=int,default=0)
    a=ap.parse_args(); splits=['dev','test'] if a.split=='both' else [a.split]
    for s in splits: run(s,a.backend,a.output,a.limit,a.offset)
if __name__=='__main__': main()
