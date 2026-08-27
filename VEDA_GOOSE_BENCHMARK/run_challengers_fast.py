#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,math,os,statistics,sys,tempfile,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
sys.path.insert(0,str(ROOT))

def csvrows(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def jsonl(p):return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
def iv(v):
    if v in (None,''):return None
    try:return int(v)
    except:return v
def fv(v):
    if v in (None,''):return None
    try:return float(v)
    except:return v

def setup(split):
    tmp=tempfile.TemporaryDirectory(prefix=f'veda-chal-fast-{split}-');os.environ['VEDA_DATA_DIR']=tmp.name
    from veda import db,config
    config.DATA_DIR=Path(tmp.name);config.DB_PATH=config.DATA_DIR/'veda.db';config.PROJECTS_DIR=config.DATA_DIR/'projects';config.OUTPUTS_DIR=config.DATA_DIR/'outputs'
    old=getattr(db._local,'conn',None)
    if old is not None:old.close();delattr(db._local,'conn')
    db.init_db();pid=f'chal-{split}';db.insert('projects',{'id':pid,'name':split})
    snap=db.insert('schedule_snapshots',{'project_id':pid,'revision':2,'status_date':'2026-08-27','data_date':'2026-08-27','is_current':1,'info_json':db.jdumps({'out_of_sequence_schedule_type':'Progress Override'})})
    sd=HERE/'data'/split;rows=csvrows(sd/'schedule.csv');rels=csvrows(sd/'relationships.csv');now=db.now();conn=db.connect()
    vals=[(f'a-{i}',pid,snap,iv(r['uid']),r['display_id'],r['name'],r['wbs'],r['wbs_path'],0,0,r['status'],r['start'],r['finish'],r['actual_start'] or None,r['actual_finish'] or None,r['baseline_start'],r['baseline_finish'],r['custom_json'],now) for i,r in enumerate(rows)]
    conn.executemany('INSERT INTO activities (id,project_id,snapshot_id,uid,display_id,name,wbs,wbs_path,is_summary,is_milestone,status,start,finish,actual_start,actual_finish,baseline_start,baseline_finish,custom_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals)
    rv=[(f'r-{i}',pid,snap,iv(r['pred_uid']),iv(r['succ_uid']),r.get('type') or 'FS',fv(r.get('lag_days')) or 0.0,iv(r.get('driving')) or 0,now) for i,r in enumerate(rels)]
    conn.executemany('INSERT INTO relationships (id,project_id,snapshot_id,pred_uid,succ_uid,type,lag_days,driving,created_at) VALUES (?,?,?,?,?,?,?,?,?)',rv)
    hp=sd/'history_events.csv'
    if hp.exists():
      hist=csvrows(hp);hv=[(f'e-{i}',pid,f'h|{i}',iv(r['activity_uid']),r.get('action_type'),r.get('event_state'),r.get('event_date'),1.0,'observed',1,'SYNTHETIC',now,now) for i,r in enumerate(hist)]
      if hv:conn.executemany('INSERT INTO execution_events (id,project_id,canonical_key,activity_uid,action_type,event_state,event_date,confidence,state,source_count,provenance,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',hv)
    lp=sd/'lineage.csv'
    if lp.exists():
      lin=csvrows(lp);lv=[(f'l-{i}',pid,1,2,iv(r['from_uid']),iv(r['to_uid']),r['relation'],fv(r['score']),'synthetic',now) for i,r in enumerate(lin)]
      if lv:conn.executemany('INSERT INTO activity_lineage (id,project_id,from_revision,to_revision,from_uid,to_uid,relation,score,basis,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',lv)
    conn.commit();return tmp,pid,len(rows),len(rels)

def rank(cands,uid,eps=1e-10):
    # Conservative tie-aware rank: if the expected leaf is tied with N equally
    # supported siblings, assign the worst position in that tie group. This
    # prevents deterministic UID/insertion order from masquerading as evidence.
    if uid is None:return None
    target=None
    for c in cands:
      if int(c['activity']['uid'])==int(uid): target=float(c.get('score') or 0.0); break
    if target is None:return None
    greater=sum(1 for c in cands if float(c.get('score') or 0.0)>target+eps)
    tied=sum(1 for c in cands if abs(float(c.get('score') or 0.0)-target)<=eps)
    return greater+tied

def metric(rr,key):
    x=[r for r in rr if r['expected_uid'] is not None]
    def rec(k):return sum(1 for r in x if r.get(key) and r[key]<=k)/max(1,len(x))
    return {'n':len(x),'top1':rec(1),'r3':rec(3),'r5':rec(5),'r10':rec(10),'mrr':sum(1/r[key] if r.get(key) else 0 for r in x)/max(1,len(x))}
def eq(a,b):return set(map(int,a or []))==set(map(int,b or []))

def existing(split):
    if split in {'dev','test'}:
      p=HERE/'reports_full'/f'{split}_results_merged.json';o=json.loads(p.read_text())
      s=o['summary'];v=s['variants'];return {
        'semantic_rank':v['semantic_rank'],'engineering_rank':v['veda_rank'],'workfront_rank':v['workfront_rank'],
        'categories':s['categories'],'relation_accuracy':s['relation_accuracy']}
    p=HERE/'adaptive_holdout_shards'/'FULL_ADAPTIVE_HOLDOUT_RESULTS.json';o=json.loads(p.read_text())['summary']
    return {'semantic_rank':o['metrics_uid_labeled']['semantic_rank'],'engineering_rank':o['metrics_uid_labeled']['veda_rank'],'workfront_rank':o['metrics_uid_labeled']['workfront_rank'],'adaptive_rank':o['metrics_uid_labeled']['adaptive_rank'],'categories':o['categories_uid_labeled'],'relation_accuracy':o['relation_accuracy']}

def run(split,outdir,offset=0,limit=None):
    from veda.resolution import tree_resolver,rescheduler,reality_graph
    tmp,pid,nact,nrel=setup(split);cases=jsonl(HERE/'data'/split/'cases.jsonl');
    if offset: cases=cases[offset:]
    if limit is not None: cases=cases[:limit]
    records=[];tt=[];rt=[]
    for i,c in enumerate(cases,1):
      ev=dict(c['evidence']);ev.update({'id':c['id'],'project_id':pid,'state':'new'})
      if c['evidence'].get('historical_activity_uid') is not None:ev['historical_activity_uid']=c['evidence']['historical_activity_uid']
      t=time.perf_counter();tr=tree_resolver.rerank(pid,ev,[],limit=24);tt.append(time.perf_counter()-t);tc=tr['candidates']
      t=time.perf_counter();rr=rescheduler.standalone_rank(pid,ev,limit=24);rt.append(time.perf_counter()-t);rc=rr['candidates']
      trel=tree_resolver.relation_hypothesis(pid,ev,tc);expected=c.get('expected_uid')
      records.append({'id':c['id'],'category':c['category'],'edge_case':c['edge_case'],'expected_uid':expected,'expected_uids':c.get('expected_uids') or [],'expected_relation':c['expected_relation'],'tree_rank':rank(tc,expected),'rescheduler_rank':rank(rc,expected),'tree_top':int(tc[0]['activity']['uid']) if tc else None,'rescheduler_top':int(rc[0]['activity']['uid']) if rc else None,'tree_relation':trel.get('relation'),'tree_relation_uids':trel.get('uids') or [],'tree_relation_ok':trel.get('relation')==c['expected_relation'] and (not c.get('expected_uids') or eq(trel.get('uids'),c.get('expected_uids')) )})
      if i%20==0:print(split,i,'/',len(cases),flush=True)
    ex=existing(split);vars={'semantic_rank':ex['semantic_rank'],'engineering_rank':ex['engineering_rank'],'workfront_rank':ex['workfront_rank'],'tree_rank':metric(records,'tree_rank'),'rescheduler_rank':metric(records,'rescheduler_rank')}
    if ex.get('adaptive_rank'):vars['adaptive_rank']=ex['adaptive_rank']
    cats={}
    for cat in sorted({r['category'] for r in records}):
      x=[r for r in records if r['category']==cat and r['expected_uid'] is not None];cats[cat]={'n':len(x),'tree':sum(r['tree_rank']==1 for r in x)/max(1,len(x)) if x else None,'rescheduler':sum(r['rescheduler_rank']==1 for r in x)/max(1,len(x)) if x else None}
      old=ex['categories'].get(cat,{})
      cats[cat]['semantic']=old.get('semantic_rank');cats[cat]['engineering']=old.get('veda_rank');cats[cat]['workfront']=old.get('workfront_rank');cats[cat]['adaptive']=old.get('adaptive_rank')
    rel=[r for r in records if r['expected_relation']!='EXACT'];relacc=sum(r['tree_relation_ok'] for r in rel)/max(1,len(rel));byrel={}
    for typ in sorted({r['expected_relation'] for r in rel}):
      x=[r for r in rel if r['expected_relation']==typ];byrel[typ]={'n':len(x),'tree':sum(r['tree_relation_ok'] for r in x)/len(x)}
    def lat(x):
      s=sorted(x);return {'median_ms':statistics.median(s)*1000,'p95_ms':s[max(0,math.ceil(.95*len(s))-1)]*1000}
    summary={'split':split,'activities':nact,'relationships':nrel,'cases':len(cases),'variants':vars,'categories':cats,'relations':{'existing':ex['relation_accuracy'],'tree':relacc,'by_type':byrel,'n':len(rel)},'latency':{'tree':lat(tt),'rescheduler':lat(rt)}}
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True);suffix=f'_o{offset}_n{len(cases)}' if offset or limit is not None else ''
    (out/f'{split}{suffix}_fast_results.json').write_text(json.dumps({'summary':summary,'records':records},indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True);tmp.cleanup();return summary

if __name__=='__main__':
  ap=argparse.ArgumentParser();ap.add_argument('--split',default='dev');ap.add_argument('--output',default=str(HERE/'challenger_fast_reports'));ap.add_argument('--offset',type=int,default=0);ap.add_argument('--limit',type=int);a=ap.parse_args();run(a.split,a.output,a.offset,a.limit)
