#!/usr/bin/env python3
"""Adversarial OIL/SIH26122 benchmark for VEDA.

Safe by default:
- uses a temporary VEDA_DATA_DIR
- never opens/mutates a real schedule
- runs current VEDA hybrid retrieval AND current production linking pipeline
- produces machine-readable JSON and a Markdown report
"""
from __future__ import annotations
import argparse, json, os, sys, tempfile, time, math, statistics, hashlib
from pathlib import Path

HERE=Path(__file__).resolve().parent

def find_repo_root(start: Path) -> Path:
    for p in [start,*start.parents]:
        if (p/'veda').is_dir() and (p/'veda'/'db.py').exists(): return p
    # Benchmark folder is commonly copied directly into repo root.
    p=start.parent
    if (p/'veda'/'db.py').exists(): return p
    raise SystemExit('Could not find VEDA repo root. Put VEDA_HARD_BENCHMARK inside the VEDA project root.')

def load_cases(mode: str):
    rows=[json.loads(x) for x in (HERE/'cases'/'oil_hard_cases.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    if mode=='quick':
        # stratified first ~60 cases
        keep=[]; counts={}
        for r in rows:
            cat=r['category']; counts[cat]=counts.get(cat,0)
            if counts[cat]<6: keep.append(r); counts[cat]+=1
        return keep
    return rows

def rr(rank): return 0.0 if rank is None else 1.0/rank

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--mode',choices=['quick','full'],default='full')
    ap.add_argument('--backend',choices=['current','hash','bge-m3'],default='current')
    ap.add_argument('--allow-model-download',action='store_true')
    ap.add_argument('--top-k',type=int,default=10)
    ap.add_argument('--output',default=str(HERE/'reports'))
    args=ap.parse_args()

    repo=find_repo_root(HERE)
    sys.path.insert(0,str(repo))
    tmp=tempfile.TemporaryDirectory(prefix='veda-hard-benchmark-')
    os.environ['VEDA_DATA_DIR']=tmp.name
    if args.backend=='hash': os.environ['VEDA_EMBEDDING_BACKEND']='hash'
    elif args.backend=='bge-m3': os.environ['VEDA_EMBEDDING_BACKEND']='bge-m3'
    if args.allow_model_download: os.environ['VEDA_ALLOW_MODEL_DOWNLOAD']='1'

    from veda import db
    from veda.retrieval import engine, embeddings, calibration
    from veda.pipeline import validators, linking
    db.init_db()
    cases=load_cases(args.mode)
    meta=json.loads((HERE/'cases'/'benchmark_meta.json').read_text(encoding='utf-8'))
    dataset_path=HERE/'cases'/'oil_hard_cases.jsonl'
    dataset_sha256=hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if args.mode=='full' and len(cases) != int(meta.get('case_count') or 0):
        raise SystemExit(f"INCOMPLETE BENCHMARK: loaded {len(cases)} cases, expected {meta.get('case_count')}")
    outdir=Path(args.output); outdir.mkdir(parents=True,exist_ok=True)
    results=[]; retrieval_times=[]; pipeline_times=[]; index_times=[]

    print(f'VEDA repo: {repo}')
    print(f'Temporary data: {tmp.name}')
    print(f'Cases: {len(cases)} ({args.mode})')
    try:
        backend=embeddings.get_backend()
        print(f'Embedding backend: {backend.name} ({type(backend).__name__})')
    except Exception as e:
        print('Embedding backend failed to initialize:',repr(e)); raise

    for n,c in enumerate(cases,1):
        pid='bench-'+c['id'].lower()
        db.insert('projects',{'id':pid,'name':c['id'],'client':'Synthetic OIL Benchmark','location':'Synthetic'})
        snap=db.insert('schedule_snapshots',{'project_id':pid,'revision':1,'status_date':'2025-06-30','data_date':'2025-06-30','is_current':1,'info_json':db.jdumps({'out_of_sequence_schedule_type':'Retained Logic'})})
        for a in c['activities']:
            row=dict(a); row.update({'project_id':pid,'snapshot_id':snap})
            if isinstance(row.get('custom_json'),dict): row['custom_json']=db.jdumps(row['custom_json'])
            db.insert('activities',row)
        for r in c.get('relationships') or []:
            row=dict(r); row.update({'project_id':pid,'snapshot_id':snap})
            db.insert('relationships',row)
        # Supporting records come first for duplicates/date corroboration.
        for j,se in enumerate(c.get('supporting_evidence') or []):
            row=dict(se); row.update({'id':f'{pid}-support-{j}','project_id':pid,'state':'linked','source_file':se.get('source_file') or f'SUPPORT_{j}.xlsx','locator':se.get('locator') or f'R{j+1}'})
            if isinstance(row.get('raw_json'),dict): row['raw_json']=db.jdumps(row['raw_json'])
            db.insert('evidence',row)
        erow=dict(c['evidence']); erow.update({'id':f'{pid}-evidence','project_id':pid,'state':'new'})
        if isinstance(erow.get('raw_json'),dict): erow['raw_json']=db.jdumps(erow['raw_json'])
        db.insert('evidence',erow)
        evidence=db.q1('SELECT * FROM evidence WHERE id=?',[erow['id']])

        # Separate one-time schedule index construction from steady-state query
        # latency. Production DPR rows reuse the same revision index.
        ti=time.perf_counter(); idx_info=engine.index_project(pid); index_times.append(time.perf_counter()-ti)
        t=time.perf_counter(); hs=engine.hybrid_search(pid,evidence,top_k=args.top_k,ensure_index=False); retrieval_times.append(time.perf_counter()-t)
        cands=hs.get('candidates') or []
        expected=c.get('expected_uid')
        rank=None
        if expected is not None:
            for i,x in enumerate(cands,1):
                if int(x['activity']['uid'])==int(expected): rank=i; break
        top=cands[0] if cands else None
        top_uid=int(top['activity']['uid']) if top else None
        top_score=float(top['score']) if top else 0.0
        runner_score=float(cands[1]['score']) if len(cands)>1 else 0.0
        margin=max(0.0,top_score-runner_score) if top else 0.0
        validator=None; cal=None
        if top:
            validator=validators.validate_link(evidence,top['activity'],project_id=pid,status_date='2025-06-30')
            cal=calibration.calibrated_probability(top_score,pid,features=top.get('features') or {})

        # Run the real production pipeline too. This intentionally detects if
        # hybrid_search exists but link_evidence() is still wired to a legacy matcher.
        t=time.perf_counter();
        try:
            pipe_stats=linking.link_evidence(pid,evidence_rows=[evidence],status_date='2025-06-30',raise_reviews=False)
            pipe_error=None
        except Exception as e:
            pipe_stats={}; pipe_error=repr(e)
        pipeline_times.append(time.perf_counter()-t)
        post=db.q1('SELECT * FROM evidence WHERE id=?',[erow['id']]) or {}
        links=db.q('SELECT * FROM evidence_links WHERE evidence_id=? ORDER BY is_candidate ASC, rank_score DESC, created_at ASC',[erow['id']])
        primary=links[0] if links else {}
        recommended_uid=int(primary['recommended_uid']) if primary.get('recommended_uid') is not None else (int(primary['activity_uid']) if primary.get('activity_uid') is not None else None)
        pipe_uid=int(primary['committed_uid']) if primary.get('committed_uid') is not None else (int(primary['activity_uid']) if post.get('state')=='linked' and primary.get('activity_uid') is not None else None)
        pipe_state=post.get('state')

        exp=c['expected_outcome']
        retrieval_ok=(rank==1) if expected is not None else True
        if exp=='match':
            pipeline_ok=(pipe_uid==expected and pipe_state=='linked')
            unsafe=False
        elif exp=='duplicate':
            pipeline_ok=(pipe_state=='duplicate')
            unsafe=(pipe_state=='linked')
        elif exp=='historical':
            pipeline_ok=(pipe_state=='historical')
            unsafe=(pipe_state=='linked')
        else: # review/abstain
            pipeline_ok=(pipe_state in ('needs_review','unresolved','conflicting','quarantined'))
            unsafe=(pipe_state=='linked')

        results.append({
            'id':c['id'],'category':c['category'],'edge_case_type':c['edge_case_type'],'difficulty':c['difficulty'],
            'expected_outcome':exp,'expected_uid':expected,'retrieval_rank':rank,'retrieval_top_uid':top_uid,
            'retrieval_top_score':round(top_score,6),'retrieval_margin':round(margin,6),'retrieval_top1_ok':retrieval_ok,
            'calibrated_probability':round(float((cal or {}).get('probability') or 0),6) if cal else None,
            'calibration_mode':(cal or {}).get('mode') if cal else None,'validator_result':(validator or {}).get('result') if validator else None,
            'pipeline_state':pipe_state,'pipeline_uid':pipe_uid,'pipeline_recommended_uid':recommended_uid,'pipeline_ok':pipeline_ok,'unsafe_autolink':unsafe,
            'pipeline_error':pipe_error,'hybrid_diagnostics':hs.get('diagnostics'),
            'top_conflicts':(top or {}).get('conflicting',[]) if top else [],'top_supporting':(top or {}).get('supporting',[]) if top else [],
            'notes':c.get('notes','')
        })
        if n%20==0 or n==len(cases): print(f'  {n}/{len(cases)}')

    # Metrics
    match=[r for r in results if r['expected_uid'] is not None]
    def recall(k): return sum(1 for r in match if r['retrieval_rank'] is not None and r['retrieval_rank']<=k)/max(1,len(match))
    mrr=sum(rr(r['retrieval_rank']) for r in match)/max(1,len(match))
    top1=sum(r['retrieval_top1_ok'] for r in match)/max(1,len(match))
    pipe=sum(r['pipeline_ok'] for r in results)/max(1,len(results))
    unsafe=sum(r['unsafe_autolink'] for r in results)
    # Auto-link precision/coverage from actual pipeline linked state.
    auto=[r for r in results if r['pipeline_state']=='linked']
    auto_correct=[r for r in auto if r['expected_outcome']=='match' and r['pipeline_uid']==r['expected_uid']]
    auto_precision=(len(auto_correct)/len(auto)) if auto else None; coverage=len(auto)/max(1,len(results))

    cats={}
    for r in results:
        x=cats.setdefault(r['category'],{'n':0,'retrieval_eligible':0,'retrieval_top1':0,'pipeline_ok':0,'unsafe':0})
        x['n']+=1
        if r['expected_uid'] is not None:
            x['retrieval_eligible']+=1; x['retrieval_top1']+=1 if r['retrieval_top1_ok'] else 0
        x['pipeline_ok']+=1 if r['pipeline_ok'] else 0; x['unsafe']+=1 if r['unsafe_autolink'] else 0
    for x in cats.values():
        x['retrieval_top1_rate']=round(x['retrieval_top1']/x['retrieval_eligible'],4) if x['retrieval_eligible'] else None
        x['pipeline_ok_rate']=round(x['pipeline_ok']/x['n'],4)

    summary={
        'case_count':len(results),'expected_case_count':int(meta.get('case_count') or 0),'dataset_sha256':dataset_sha256,
        'match_cases':len(match),'embedding_backend':backend.name,
        'retrieval':{'recall_at_1':round(recall(1),4),'recall_at_3':round(recall(3),4),'recall_at_5':round(recall(5),4),'recall_at_10':round(recall(10),4),'mrr':round(mrr,4),'top1_accuracy':round(top1,4)},
        'production_pipeline':{'outcome_accuracy':round(pipe,4),'auto_link_precision':round(auto_precision,4) if auto_precision is not None else None,'auto_link_coverage':round(coverage,4),'unsafe_autolinks':unsafe,'linked_count':len(auto)},
        'latency_seconds':{'index_build_median':round(statistics.median(index_times),4) if index_times else 0,
                           'retrieval_warm_median':round(statistics.median(retrieval_times),4) if retrieval_times else 0,
                           'retrieval_warm_p95':round(sorted(retrieval_times)[max(0,math.ceil(.95*len(retrieval_times))-1)],4) if retrieval_times else 0,
                           'pipeline_median':round(statistics.median(pipeline_times),4) if pipeline_times else 0},
        'categories':cats,
    }
    payload={'summary':summary,'results':results}
    (outdir/'hard_benchmark_results.json').write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')

    failures=[r for r in results if not r['pipeline_ok'] or (r['expected_uid'] is not None and not r['retrieval_top1_ok'])]
    unsafe_rows=[r for r in results if r['unsafe_autolink']]
    md=['# VEDA OIL/SIH26122 Hard Benchmark','',f"- Cases: **{len(results)}**",f"- Backend: **{backend.name}**", f"- Dataset SHA-256: `{dataset_sha256}`",'',
        '## Retrieval',f"- Recall@1: **{summary['retrieval']['recall_at_1']:.2%}**",f"- Recall@3: **{summary['retrieval']['recall_at_3']:.2%}**",f"- Recall@5: **{summary['retrieval']['recall_at_5']:.2%}**",f"- MRR: **{summary['retrieval']['mrr']:.4f}**",'',
        '## Actual production linking pipeline',f"- Expected-outcome accuracy: **{summary['production_pipeline']['outcome_accuracy']:.2%}**",f"- Auto-link precision: **{summary['production_pipeline']['auto_link_precision']:.2%}**" if summary['production_pipeline']['auto_link_precision'] is not None else "- Auto-link precision: **N/A (no auto-links)**",f"- Auto-link coverage: **{summary['production_pipeline']['auto_link_coverage']:.2%}**",f"- UNSAFE auto-links on review/negative cases: **{unsafe}**",'',
        '## Category matrix','| Category | N | Retrieval Top1* | Pipeline outcome | Unsafe auto-links |','|---|---:|---:|---:|---:|']
    for k,v in sorted(cats.items()): md.append(f"| {k} | {v['n']} | {v['retrieval_top1_rate']:.1%} | {v['pipeline_ok_rate']:.1%} | {v['unsafe']} |" if v['retrieval_top1_rate'] is not None else f"| {k} | {v['n']} | N/A | {v['pipeline_ok_rate']:.1%} | {v['unsafe']} |")
    md += ['', '*For expected-review cases without a single correct UID, retrieval Top1 is not treated as a failure; pipeline abstention is what matters.','',
           '## First 40 failures','| ID | Category | Edge | Expected | Retrieval rank | Pipeline state | Pipeline UID | Unsafe |','|---|---|---|---|---:|---|---:|---|']
    for r in failures[:40]: md.append(f"| {r['id']} | {r['category']} | {r['edge_case_type']} | {r['expected_outcome']} / {r['expected_uid']} | {r['retrieval_rank']} | {r['pipeline_state']} | {r['pipeline_uid']} | {r['unsafe_autolink']} |")
    if unsafe_rows:
        md += ['', '## Unsafe auto-links (must investigate)']
        for r in unsafe_rows[:50]: md.append(f"- **{r['id']}** `{r['edge_case_type']}` → pipeline linked UID {r['pipeline_uid']} although expected `{r['expected_outcome']}`")
    md += ['', '## Interpretation','A high retrieval score with poor pipeline outcome means the semantic engine may be working while the production linker is not using it correctly. Unsafe auto-links matter more than raw accuracy. Do not tune against this synthetic set alone; hold out real projects when NDA/sample OIL data becomes available.']
    (outdir/'hard_benchmark_report.md').write_text('\n'.join(md),encoding='utf-8')

    print('\n=== SUMMARY ===')
    print(json.dumps(summary,indent=2))
    print(f"\nReport: {outdir/'hard_benchmark_report.md'}")
    print(f"JSON:   {outdir/'hard_benchmark_results.json'}")
    # Deliberately nonzero only for runtime crashes, not metric failures. The
    # point is to collect failures for the agent to fix, not hide the report.
    tmp.cleanup()

if __name__=='__main__': main()
