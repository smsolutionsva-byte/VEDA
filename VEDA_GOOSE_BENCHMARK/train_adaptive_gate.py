#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, os, sys, time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))


def rank_of(cands, uid):
    if uid is None: return None
    for i,c in enumerate(cands,1):
        try:
            if int(c['activity']['uid'])==int(uid): return i
        except Exception: pass
    return None


def collect(split:str, output:str, offset:int=0, limit:int|None=None, backend:str='hash'):
    # Reuse the frozen benchmark setup; no labels/categories enter gate features.
    import run as bench
    from veda.retrieval import engine
    from veda.resolution import adaptive_gate
    tmp,pid,idx,index_s,backend_name=bench.setup(split,backend)
    cases=bench.load_jsonl(HERE/'data'/split/'cases.jsonl')
    cases=cases[offset:]
    if limit is not None: cases=cases[:limit]
    rows=[]
    for n,c in enumerate(cases,1):
        expected=c.get('expected_uid')
        if expected is None:
            continue
        ev=dict(c['evidence']); ev.update({'id':c['id'],'project_id':pid,'state':'new'})
        t=time.perf_counter()
        res=engine.hybrid_search(pid,ev,top_k=24,ensure_index=False,use_workfront=True,use_adaptive_gate=False)
        base=res.get('pre_workfront_candidates') or []
        wf=res.get('workfront_candidates') or res.get('candidates') or []
        frontier=(res.get('diagnostics') or {}).get('workfront_frontier') or {}
        feats=adaptive_gate.context_features(ev,base,wf,frontier)
        br=rank_of(base,expected); wr=rank_of(wf,expected)
        brr=1.0/br if br else 0.0; wrr=1.0/wr if wr else 0.0
        btop=(br==1); wtop=(wr==1)
        # Target is learned expert utility, not a category rule.
        if wtop and not btop:
            y=1; weight=2.0; reason='workfront_unique_top1'
        elif btop and not wtop:
            y=0; weight=2.0; reason='engineering_unique_top1'
        elif wrr>brr+1e-12:
            y=1; weight=0.75+abs(wrr-brr); reason='workfront_better_rr'
        elif brr>wrr+1e-12:
            y=0; weight=0.75+abs(wrr-brr); reason='engineering_better_rr'
        else:
            # Equal utility defaults to the cheaper/safer engineering expert,
            # but with low weight so ties do not dominate training.
            y=0; weight=0.20; reason='tie_prefer_default'
        rows.append({'id':c['id'],'category_for_analysis_only':c['category'],'expected_uid':expected,
                     'base_rank':br,'workfront_rank':wr,'base_top1':btop,'workfront_top1':wtop,
                     'label_workfront':y,'sample_weight':weight,'label_reason':reason,
                     'features':feats,'query_seconds':time.perf_counter()-t})
        if n%10==0: print(f'collect {split}: {n}/{len(cases)}',flush=True)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text('\n'.join(json.dumps(x) for x in rows)+'\n',encoding='utf-8')
    print(json.dumps({'split':split,'rows':len(rows),'activities':idx.get('activities'),'backend':backend_name,'index_seconds':index_s},indent=2))
    tmp.cleanup()


def load_rows(paths):
    rows=[]
    for p in paths:
        for line in Path(p).read_text(encoding='utf-8').splitlines():
            if line.strip(): rows.append(json.loads(line))
    return rows


def fit(paths:list[str], model_out:str, report_out:str):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import accuracy_score, roc_auc_score, log_loss, brier_score_loss
    from veda.resolution.adaptive_gate import FEATURE_NAMES

    rows=load_rows(paths)
    X=np.asarray([[float(r['features'].get(k,0.0)) for k in FEATURE_NAMES] for r in rows],dtype=float)
    y=np.asarray([int(r['label_workfront']) for r in rows],dtype=int)
    sw=np.asarray([float(r.get('sample_weight',1.0)) for r in rows],dtype=float)
    if len(set(y.tolist()))<2: raise SystemExit('Need both gate classes')
    counts={str(k):int((y==k).sum()) for k in [0,1]}

    # Out-of-fold routing estimate on DEV.  This estimates generalisation of the
    # gate itself before fitting the final transparent model on all DEV rows.
    n_splits=min(5,int(min((y==0).sum(),(y==1).sum())))
    cv=StratifiedKFold(n_splits=max(2,n_splits),shuffle=True,random_state=26122)
    pipe=make_pipeline(StandardScaler(),LogisticRegression(C=0.7,max_iter=3000,class_weight='balanced',random_state=26122))
    # cross_val_predict cannot forward sample_weight to all sklearn versions via
    # params consistently; class balancing + low-dimensional regularisation is
    # used for the OOF estimate. Final fit below uses sample weights.
    p_oof=cross_val_predict(pipe,X,y,cv=cv,method='predict_proba')[:,1]
    route=(p_oof>0.5).astype(int)

    # Simulate query-level expert routing under OOF predictions.
    def is_top(r, which): return bool(r['workfront_top1'] if which else r['base_top1'])
    oof_top=sum(1 for r,z in zip(rows,route) if is_top(r,int(z)))/max(1,len(rows))
    base_top=sum(1 for r in rows if r['base_top1'])/max(1,len(rows))
    wf_top=sum(1 for r in rows if r['workfront_top1'])/max(1,len(rows))
    oracle_top=sum(1 for r in rows if r['base_top1'] or r['workfront_top1'])/max(1,len(rows))

    # Final fit and transparent export.
    scaler=StandardScaler().fit(X)
    Xs=scaler.transform(X)
    clf=LogisticRegression(C=0.7,max_iter=3000,class_weight='balanced',random_state=26122)
    clf.fit(Xs,y,sample_weight=sw)
    pobj={
      'version':'adaptive_execution_gate_v0.3.0',
      'model_type':'standardized_logistic_expert_gate',
      'trained_on':'VEDA_GOOSE_BENCHMARK/dev only',
      'feature_names':FEATURE_NAMES,
      'mean':scaler.mean_.tolist(),
      'scale':scaler.scale_.tolist(),
      'coef':clf.coef_[0].tolist(),
      'intercept':float(clf.intercept_[0]),
      'decision':'argmax(engineering, workfront); ties -> engineering',
      'training_rows':len(rows),
      'class_counts':counts,
      'notes':'Probability is gate propensity, not activity-link confidence. Benchmark category is never a model feature.'
    }
    Path(model_out).write_text(json.dumps(pobj,indent=2),encoding='utf-8')

    auc=roc_auc_score(y,p_oof) if len(set(y))>1 else None
    rep={
      'rows':len(rows),'class_counts':counts,'cv_folds':n_splits,
      'oof_gate_accuracy':accuracy_score(y,route),
      'oof_gate_auc':auc,'oof_log_loss':log_loss(y,p_oof),'oof_brier':brier_score_loss(y,p_oof),
      'dev_top1_engineering':base_top,'dev_top1_workfront':wf_top,
      'dev_top1_adaptive_oof':oof_top,'dev_top1_oracle_two_expert_ceiling':oracle_top,
      'model_out':model_out,
      'largest_positive_coefficients':[], 'largest_negative_coefficients':[]
    }
    pairs=sorted(zip(FEATURE_NAMES,clf.coef_[0]),key=lambda x:x[1])
    rep['largest_negative_coefficients']=[{'feature':k,'coef':float(v)} for k,v in pairs[:8]]
    rep['largest_positive_coefficients']=[{'feature':k,'coef':float(v)} for k,v in pairs[-8:][::-1]]
    Path(report_out).write_text(json.dumps(rep,indent=2),encoding='utf-8')
    print(json.dumps(rep,indent=2))


def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('collect'); c.add_argument('--split',default='dev'); c.add_argument('--output',required=True); c.add_argument('--offset',type=int,default=0); c.add_argument('--limit',type=int); c.add_argument('--backend',default='hash')
    f=sub.add_parser('fit'); f.add_argument('--inputs',nargs='+',required=True); f.add_argument('--model-out',required=True); f.add_argument('--report-out',required=True)
    a=ap.parse_args()
    if a.cmd=='collect': collect(a.split,a.output,a.offset,a.limit,a.backend)
    else: fit(a.inputs,a.model_out,a.report_out)
if __name__=='__main__': main()
