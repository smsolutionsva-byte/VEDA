#!/usr/bin/env python3
from __future__ import annotations
import csv, json, random, hashlib
from datetime import date, timedelta
from pathlib import Path
import generate as g

HERE=Path(__file__).resolve().parent
SPLIT='holdout_v030'
SEED=104729


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:
        path.write_text('',encoding='utf-8'); return
    fields=fields or sorted({k for r in rows for k in r})
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def main():
    rows,rels,cases,history,lineage,streams=g.build(SPLIT,SEED)
    uid=max(int(r['uid']) for r in rows)+1
    rng=random.Random(SEED+13)

    def add(name,unit,area,phase,disc,st,fn,tag=None,status='not_started',actual_start='',actual_finish=''):
        nonlocal uid
        cur=uid; uid+=1
        g.add_activity(rows,cur,name,unit,area,phase,disc,st,fn,tag,status,actual_start,actual_finish)
        return cur

    def case(family,evidence,expected,notes):
        cases.append({'id':f'HOLD-{len(cases)+1:04d}','category':'adaptive_mixed','edge_case':family,
                      'evidence':evidence,'expected_uid':expected,'expected_uids':[expected],
                      'expected_relation':'EXACT','should_abstain':False,'notes':notes})

    def hot(unit,area,d,disc='Mechanical',prefix='recent work'):
        helpers=[]
        for z in range(4):
            st=d-timedelta(days=4-z); fn=d-timedelta(days=3-z)
            helpers.append(add(f'{prefix} {unit}{area}-{z}',unit,area,'Construction',disc,st.isoformat(),fn.isoformat(),None,'complete',st.isoformat(),fn.isoformat()))
        return helpers

    # A) Strong asset/location identity must resist a misleading hot frontier.
    for k in range(8):
        d=date(2026,2,10)+timedelta(days=k*9); tag=f'P-{910+k}A'; wrong=f'P-{950+k}B'
        target=add(f'Final alignment {tag}',7,'A','Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat(),tag)
        other=add(f'Final alignment {wrong}',7,'B','Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat(),wrong)
        hot(7,'B',d,prefix='hot mechanical branch')
        case('strong_identity_vs_misleading_frontier',{'description':f'{tag} final alignment completed in Unit 7 Area A','date':d.isoformat(),'discipline':'Mechanical','location':'Unit 7 Area A','source_file':'FIELD_DPR.xlsx'},target,'Explicit asset/location should keep EngineeringRank authoritative even though another branch is much hotter.')

    # B) Location-only identity must also resist a misleading workfront.
    for k in range(8):
        d=date(2026,3,1)+timedelta(days=k*8)
        target=add('Final equipment alignment',6,'D','Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat())
        other=add('Final equipment alignment',6,'E','Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat())
        hot(6,'E',d,prefix='hot wrong-area mechanical')
        case('location_identity_vs_misleading_frontier',{'description':'Unit 6 Area D final equipment alignment completed','date':d.isoformat(),'discipline':'Mechanical','location':'Unit 6 Area D','source_file':'SHIFT_REPORT.txt'},target,'No asset tag; explicit location/WBS context should dominate a hotter wrong-area frontier.')

    # C) No physical identity: predecessor + active branch should rescue the correct activity.
    for k in range(8):
        d=date(2026,4,5)+timedelta(days=k*11); choices=[]
        for area in ['A','B','C']:
            pred=add('Mechanical placement complete',2,area,'Construction','Mechanical',(d-timedelta(days=5)).isoformat(),(d-timedelta(days=3)).isoformat(),None,'complete',(d-timedelta(days=5)).isoformat(),(d-timedelta(days=3)).isoformat())
            cand=add('Final alignment',2,area,'Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat())
            rels.append({'pred_uid':pred,'succ_uid':cand,'type':'FS','lag_days':0,'driving':1}); choices.append(cand)
        hot(2,'C',d,prefix='dense target workfront')
        case('missing_identity_unique_execution_frontier',{'description':'Final alignment completed on the current mechanical workfront','date':d.isoformat(),'discipline':'Mechanical','source_file':'SUPERVISOR_VOICE.txt'},choices[2],'Text is intentionally under-specified; recent execution topology should be the only strong discriminator.')

    # D) Multiple hot workfronts: action evidence, not graph heat, must decide.
    for k in range(8):
        d=date(2026,5,2)+timedelta(days=k*7)
        target=add('Hydrotest process line',3,'A','Construction','Piping',d.isoformat(),(d+timedelta(days=2)).isoformat())
        other=add('Inspect process line',3,'B','Construction','Piping',d.isoformat(),(d+timedelta(days=2)).isoformat())
        hot(3,'A',d,'Piping','hot piping A'); hot(3,'B',d,'Piping','hot piping B')
        case('multiple_hot_frontiers_action_decides',{'description':'Process line hydrotest completed on current piping work','date':d.isoformat(),'discipline':'Piping','source_file':'DPR.txt'},target,'Both branches are active; execution-frontier discrimination is weak, while canonical action discriminates.')

    # E) OOS execution with explicit identity: graph readiness is deliberately misleading.
    for k in range(8):
        d=date(2026,6,1)+timedelta(days=k*6); tag=f'SP-{9200+k}'
        pred=add(f'Release materials {tag}',4,'D','Construction','Piping',(d-timedelta(days=4)).isoformat(),(d-timedelta(days=2)).isoformat(),tag,'not_started')
        target=add(f'Erect {tag}',4,'D','Construction','Piping',d.isoformat(),(d+timedelta(days=2)).isoformat(),tag)
        rels.append({'pred_uid':pred,'succ_uid':target,'type':'FS','lag_days':0,'driving':1})
        wrongtag=f'SP-{9300+k}'
        wpred=add(f'Release materials {wrongtag}',4,'E','Construction','Piping',(d-timedelta(days=4)).isoformat(),(d-timedelta(days=2)).isoformat(),wrongtag,'complete',(d-timedelta(days=4)).isoformat(),(d-timedelta(days=2)).isoformat())
        wrong=add(f'Erect {wrongtag}',4,'E','Construction','Piping',d.isoformat(),(d+timedelta(days=2)).isoformat(),wrongtag)
        rels.append({'pred_uid':wpred,'succ_uid':wrong,'type':'FS','lag_days':0,'driving':1}); hot(4,'E',d,'Piping','ready wrong workfront')
        case('oos_explicit_identity_vs_ready_wrong_graph',{'description':f'{tag} erected in Unit 4 Area D under approved out-of-sequence emergency execution','date':d.isoformat(),'discipline':'Piping','location':'Unit 4 Area D','source_file':'CALL_LOG.txt'},target,'Correct physical event violates predecessor readiness; explicit identity must beat graph plausibility.')

    # F) Weak broad location + otherwise missing identity: graph should still rescue.
    for k in range(8):
        d=date(2026,7,1)+timedelta(days=k*5); choices=[]
        # Same broad area but different units, so "Area A" is insufficient.
        for unit in [1,2,3]:
            pred=add('Equipment setting',unit,'A','Construction','Mechanical',(d-timedelta(days=5)).isoformat(),(d-timedelta(days=3)).isoformat(),None,'complete',(d-timedelta(days=5)).isoformat(),(d-timedelta(days=3)).isoformat())
            cand=add('Final alignment',unit,'A','Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat())
            rels.append({'pred_uid':pred,'succ_uid':cand,'type':'FS','lag_days':0,'driving':1}); choices.append(cand)
        hot(3,'A',d,prefix='unit-three active workfront')
        case('weak_location_graph_breaks_tie',{'description':'Area A final alignment completed on active mechanical workfront','date':d.isoformat(),'discipline':'Mechanical','location':'Area A','source_file':'VOICE_NOTE.txt'},choices[2],'Location exists but is non-discriminative across candidates; execution context should carry more authority.')

    # G) Same asset/action and location, different execution windows. A hot but stale-looking
    # sibling should not override the event date.
    for k in range(8):
        tag=f'P-{980+k}C'; oldd=date(2026,1,10)+timedelta(days=k); newd=date(2026,8,1)+timedelta(days=k)
        old=add(f'Reinstall {tag}',8,'C','Construction','Mechanical',oldd.isoformat(),(oldd+timedelta(days=2)).isoformat(),tag,'complete',oldd.isoformat(),(oldd+timedelta(days=1)).isoformat())
        target=add(f'Reinstall {tag}',8,'C','Construction','Mechanical',newd.isoformat(),(newd+timedelta(days=2)).isoformat(),tag)
        # Nearby activity heat is intentionally non-discriminative because both are same WBS.
        hot(8,'C',newd,prefix='same-branch turnaround work')
        case('temporal_identity_when_graph_non_discriminative',{'description':f'{tag} reinstalled again in Unit 8 Area C after overhaul','date':newd.isoformat(),'discipline':'Mechanical','location':'Unit 8 Area C','source_file':'TURNAROUND_DPR.xlsx'},target,'Same asset/action/location repeated months apart; current date should resolve identity while workfront contributes little.')

    # H) Phase-specific wording with a hot wrong-phase construction branch.
    for k in range(8):
        tag=f'PT-{1900+k}'; d=date(2026,8,12)+timedelta(days=k)
        target=add(f'Calibrate {tag}',5,'F','Commissioning','Instrumentation',d.isoformat(),(d+timedelta(days=1)).isoformat(),tag)
        wrong=add(f'Calibrate {tag}',5,'F','Construction','Instrumentation',d.isoformat(),(d+timedelta(days=1)).isoformat(),tag)
        hot(5,'F',d,'Instrumentation','construction branch work')
        case('phase_identity_vs_hot_wrong_phase',{'description':f'Commissioning calibration of {tag} completed in Unit 5 Area F','date':d.isoformat(),'discipline':'Instrumentation','location':'Unit 5 Area F','source_file':'COMMISSIONING_LOG.xlsx'},target,'Phase is explicit and should retain engineering authority despite local execution heat.')

    # Shuffle only the appended mixed cases to avoid family-order shortcuts in any
    # downstream sequential evaluation. The original 116 remain frozen first.
    original=cases[:-64]; mixed=cases[-64:]; rng.shuffle(mixed); cases=original+mixed

    sd=HERE/'data'/SPLIT; sd.mkdir(parents=True,exist_ok=True)
    write_csv(sd/'schedule.csv',rows); write_csv(sd/'relationships.csv',rels); write_csv(sd/'history_events.csv',history); write_csv(sd/'lineage.csv',lineage)
    (sd/'cases.jsonl').write_text('\n'.join(json.dumps(x) for x in cases)+'\n',encoding='utf-8')
    (sd/'reality_streams.jsonl').write_text('\n'.join(json.dumps(x) for x in streams)+'\n',encoding='utf-8')
    daily=[{'id':c['id'],'date':c['evidence'].get('date'),'discipline':c['evidence'].get('discipline'),'location':c['evidence'].get('location'),'description':c['evidence'].get('description')} for c in cases]
    write_csv(sd/'daily_reports.csv',daily); write_csv(sd/'monthly_corrections.csv',[])
    meta={'split':SPLIT,'seed':SEED,'activities':len(rows),'relationships':len(rels),'resolver_cases':len(cases),'base_cases':116,'new_mixed_cases':64,'reality_streams':len(streams)}
    hashes={}
    for p in sorted(sd.iterdir()):
        if p.is_file(): hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    meta['sha256']=hashes
    (sd/'holdout_meta.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps(meta,indent=2))

if __name__=='__main__': main()
