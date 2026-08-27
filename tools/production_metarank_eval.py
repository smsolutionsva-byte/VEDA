#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BENCH=ROOT/'VEDA_GOOSE_BENCHMARK'
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(BENCH))
import run as bench

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--offset',type=int,default=0);ap.add_argument('--limit',type=int,default=9999);ap.add_argument('--out',required=True);a=ap.parse_args()
 from veda.retrieval import engine
 tmp,pid,idx,index_s,bname=bench.setup('holdout_v032','hash');os.environ['VEDA_METARANK']='1'
 cases=[c for c in bench.load_jsonl(BENCH/'data'/'holdout_v032'/'cases.jsonl') if c.get('expected_uid') is not None][a.offset:a.offset+a.limit]
 rec=[]
 for i,c in enumerate(cases,1):
  ev=dict(c['evidence']);ev.update({'id':c['id'],'project_id':pid,'state':'new'})
  if c['evidence'].get('historical_activity_uid') is not None:ev['historical_activity_uid']=c['evidence']['historical_activity_uid']
  t=time.perf_counter();r=engine.hybrid_search(pid,ev,top_k=24,ensure_index=False);dt=time.perf_counter()-t
  rank=bench.rank_of(r['candidates'],c['expected_uid']);d=r.get('diagnostics') or {};md=d.get('metarank') or {}
  rec.append({'id':c['id'],'edge_case':c.get('edge_case'),'expected_uid':c['expected_uid'],'rank':rank,'top':int(r['candidates'][0]['activity']['uid']) if r['candidates'] else None,'mode':md.get('mode'),'expert_errors':d.get('expert_errors') or {},'seconds':dt})
  if i%10==0:print(a.offset,i,'/',len(cases),flush=True)
 Path(a.out).write_text(json.dumps({'offset':a.offset,'records':rec},indent=2));tmp.cleanup()
if __name__=='__main__':main()
