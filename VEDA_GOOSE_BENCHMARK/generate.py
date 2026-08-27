#!/usr/bin/env python3
from __future__ import annotations
import csv, json, random, hashlib
from datetime import date, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
ACTIONS={
 'P':['Install','Align','Grout','Inspect','Commission'],
 'V':['Fabricate','Transport','Erect','Weld','Hydrotest'],
 'PT':['Install','Calibrate','Loop Check','Inspect','Commission'],
 'CBL':['Pull Cable','Terminate','Inspect','Test','Commission'],
 'SP':['Fabricate','Transport','Erect','Weld','NDT'],
}
DISCS={'P':'Mechanical','V':'Piping','PT':'Instrumentation','CBL':'Electrical','SP':'Piping'}

def phase_for(action):
    if action in {'Commission','Loop Check','Calibrate','Test'}: return 'Commissioning'
    if action in {'Fabricate'}: return 'Fabrication'
    return 'Construction'

def make_split(split:str,seed:int,n_groups:int=2500):
    rng=random.Random(seed); rows=[]; rel=[]; uid=1000
    base=date(2026,1,1)
    types=list(ACTIONS)
    for g in range(n_groups):
        typ=types[g%len(types)]; seq=ACTIONS[typ]
        unit=1+(g%8); area=chr(65+(g//8)%6); rack=1+(g%7)
        # Dense, confusable owner-style identities.
        num=100+(g%780)
        suffix=chr(65+(g//780)%3)
        tag=(f'{typ}-{num}{suffix}' if typ not in {'CBL','SP'} else f'{typ}-{3000+g%1900}')
        start0=base+timedelta(days=(g*7)%330)
        prev=None
        for j,action in enumerate(seq):
            auid=uid; uid+=1
            phase=phase_for(action); st=start0+timedelta(days=j*3); fn=st+timedelta(days=2)
            name=f'{action} {tag}'
            wbs=f'1.U{unit}.A{area}.{phase[:3].upper()}.{DISCS[typ][:3].upper()}'
            path=f'Project > Unit {unit} > Area {area} > {phase} > {DISCS[typ]}'
            rows.append(dict(uid=auid,display_id=f'{split[:1].upper()}-{auid}',name=name,wbs=wbs,wbs_path=path,
                             status='not_started',start=st.isoformat(),finish=fn.isoformat(),actual_start='',actual_finish='',
                             baseline_start=st.isoformat(),baseline_finish=fn.isoformat(),is_summary=0,is_milestone=0,
                             custom_json=json.dumps({'Equipment Tag':tag,'Area':area,'Unit':unit,'Pipe Rack':f'PR-{rack:02d}'}) ))
            if prev is not None:
                rel.append(dict(pred_uid=prev,succ_uid=auid,type='FS',lag_days=0,driving=1))
            prev=auid
    return rows,rel,uid

def add_activity(rows, uid, name, unit, area, phase, disc, st, fn, tag=None, status='not_started', actual_start='', actual_finish='', wbs_extra=''):
    wbs=f'9.U{unit}.A{area}.{phase[:3].upper()}.{disc[:3].upper()}{wbs_extra}'
    path=f'Project > Unit {unit} > Area {area} > {phase} > {disc}'
    custom={'Area':area,'Unit':unit}
    if tag: custom['Equipment Tag']=tag
    rows.append(dict(uid=uid,display_id=f'S-{uid}',name=name,wbs=wbs,wbs_path=path,status=status,start=st,finish=fn,
                     actual_start=actual_start,actual_finish=actual_finish,baseline_start=st,baseline_finish=fn,
                     is_summary=0,is_milestone=0,custom_json=json.dumps(custom)))
    return uid

def build(split,seed):
    rows,rels,nextuid=make_split(split,seed)
    cases=[]; history=[]; lineage=[]; stream_scenarios=[]
    uid=900000 if split=='test' else 800000
    rng=random.Random(seed+99)
    def case(cat,edge,evidence,expected=None,expected_set=None,relation='EXACT',abstain=False,notes=''):
        nonlocal cases
        cases.append({'id':f'{split.upper()}-{len(cases)+1:04d}','category':cat,'edge_case':edge,'evidence':evidence,
                      'expected_uid':expected,'expected_uids':expected_set or ([expected] if expected else []),
                      'expected_relation':relation,'should_abstain':abstain,'notes':notes})
    def hist(hu,date_,wbs_uid,action='progress',source='HISTORY_DPR.xlsx'):
        history.append({'id':f'h-{split}-{len(history)+1}','activity_uid':wbs_uid,'event_date':date_,'action_type':action,
                        'event_state':'finish','source_file':source})

    # 1) Same name, different WBS.  Repeated variants.
    for k in range(12):
        d=date(2025,1,10)+timedelta(days=k*25)
        us=[]
        for area in ['A','B','C','D']:
            uid+=1; add_activity(rows,uid,'Final equipment alignment',5,area,'Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat())
            us.append(uid)
        target=us[k%4]; area=['A','B','C','D'][k%4]
        case('wbs','same_name_different_wbs',{'description':f'Unit 5 Area {area}: final equipment alignment completed','date':(d+timedelta(days=1)).isoformat(),'discipline':'Mechanical','source_file':'DPR.xlsx'},target)

    # 2) Same asset/action, different lifecycle phase.
    for k in range(12):
        tag=f'P-{770+k}A'; d=date(2026,7,1)+timedelta(days=k)
        uid+=1; eng=uid; add_activity(rows,uid,f'Install {tag}',3,'B','Engineering','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat(),tag)
        uid+=1; con=uid; add_activity(rows,uid,f'Install {tag}',3,'B','Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat(),tag)
        case('phase','same_asset_action_different_phase',{'description':f'Site installation of {tag} completed in Unit 3 Area B','date':(d+timedelta(days=1)).isoformat(),'discipline':'Mechanical','source_file':'MECH_DPR.xlsx'},con)

    # 3) Missing asset: semantic text identical; live workfront + graph must break tie.
    for k in range(16):
        d=date(2025,1,5)+timedelta(days=k*35)
        # Correct branch A has multiple recent actuals. Wrong branch B is also graph-ready.
        branch=[]
        for area in ['A','B']:
            uid+=1; pred=uid; add_activity(rows,uid,'Equipment placement',2,area,'Construction','Mechanical',(d-timedelta(days=6)).isoformat(),(d-timedelta(days=4)).isoformat(),status='complete',actual_start=(d-timedelta(days=6)).isoformat(),actual_finish=(d-timedelta(days=4)).isoformat())
            uid+=1; cand=uid; add_activity(rows,uid,'Final alignment',2,area,'Construction','Mechanical',d.isoformat(),(d+timedelta(days=2)).isoformat())
            rels.append({'pred_uid':pred,'succ_uid':cand,'type':'FS','lag_days':0,'driving':1}); branch.append(cand)
            # Support activity in both; only target area gets a dense recent workfront.
            if area=='A':
                for z in range(4):
                    uid+=1; helper=uid; add_activity(rows,uid,f'Adjacent mechanical work {k}-{z}',2,'A','Construction','Mechanical',(d-timedelta(days=3-z)).isoformat(),(d-timedelta(days=2-z)).isoformat(),status='complete',actual_start=(d-timedelta(days=3-z)).isoformat(),actual_finish=(d-timedelta(days=2-z)).isoformat())
                    hist(helper,(d-timedelta(days=2-z)).isoformat(),helper)
        target=branch[0]
        case('workfront','missing_asset_graph_and_frontier',{'description':'Final alignment completed on the active mechanical workfront','date':d.isoformat(),'discipline':'Mechanical','source_file':'SHIFT_LOG.txt'},target,notes='No asset/location token; current workfront should dominate a semantic tie.')

    # 4) Same text/action/location, different execution window.
    for k in range(12):
        tag=f'P-{820+k}B'; march=date(2026,3,2)+timedelta(days=k); sept=date(2026,9,2)+timedelta(days=k)
        uid+=1; old=uid; add_activity(rows,uid,f'Reinstall {tag}',6,'C','Construction','Mechanical',march.isoformat(),(march+timedelta(days=2)).isoformat(),tag,status='complete',actual_start=march.isoformat(),actual_finish=(march+timedelta(days=1)).isoformat())
        uid+=1; new=uid; add_activity(rows,uid,f'Reinstall {tag}',6,'C','Construction','Mechanical',sept.isoformat(),(sept+timedelta(days=2)).isoformat(),tag)
        case('temporal','same_text_different_date_workfront',{'description':f'{tag} reinstalled again at Area C after overhaul','date':sept.isoformat(),'discipline':'Mechanical','source_file':'SEPT_DPR.xlsx','location':'Unit 6 Area C'},new)

    # 5) Legitimate out-of-sequence: correct branch active, predecessor incomplete.
    for k in range(12):
        d=date(2025,2,1)+timedelta(days=k*35)
        choices=[]
        for area in ['D','E']:
            uid+=1; pred=uid; add_activity(rows,uid,'Release temporary bypass materials',4,area,'Construction','Piping',(d-timedelta(days=4)).isoformat(),(d-timedelta(days=2)).isoformat(),status='not_started')
            if area=='E':
                # Wrong branch looks normally ready.
                rows[-1]['status']='complete'; rows[-1]['actual_finish']=(d-timedelta(days=2)).isoformat(); rows[-1]['actual_start']=(d-timedelta(days=3)).isoformat()
            uid+=1; cand=uid; add_activity(rows,uid,'Install temporary bypass',4,area,'Construction','Piping',d.isoformat(),(d+timedelta(days=2)).isoformat())
            rels.append({'pred_uid':pred,'succ_uid':cand,'type':'FS','lag_days':0,'driving':1}); choices.append(cand)
        # Correct D has OOS work but live activity around same workfront.
        for z in range(4):
            uid+=1; helper=uid; add_activity(rows,uid,f'Area D piping emergency work {k}-{z}',4,'D','Construction','Piping',(d-timedelta(days=2)).isoformat(),d.isoformat(),status='complete',actual_start=(d-timedelta(days=2)).isoformat(),actual_finish=d.isoformat())
            hist(helper,d.isoformat(),helper)
        case('out_of_sequence','progress_override_active_workfront',{'description':'Install temporary bypass started under emergency workfront','date':d.isoformat(),'discipline':'Piping','source_file':'SUPERVISOR_CALL.txt'},choices[0],notes='Correct activity violates normal predecessor logic; workfront should rescue it.')

    # 6) One observation -> many L6 nodes.
    for k in range(10):
        d=date(2026,5,1)+timedelta(days=k)
        sp=[]
        for j in range(3):
            tag=f'SP-{7000+k*3+j}'
            uid+=1; add_activity(rows,uid,f'Erect {tag}',7,'A','Construction','Piping',d.isoformat(),(d+timedelta(days=1)).isoformat(),tag); sp.append(uid)
        tags=[rows[-3+i]['name'].split()[-1] for i in range(3)]
        case('granularity','one_observation_many_l6',{'description':f"Spools {tags[0]}, {tags[1]} and {tags[2]} erected in Unit 7 Area A",'date':d.isoformat(),'discipline':'Piping','location':'Unit 7 Area A','source_file':'PIPING_DPR.xlsx'},expected_set=sp,relation='AGGREGATES',abstain=True)

    # 7) Fine field event -> coarse L5 task.
    for k in range(10):
        d=date(2026,5,20)+timedelta(days=k); tag=f'SP-{7600+k}'
        uid+=1; coarse=uid; add_activity(rows,uid,'Erect process piping package',7,'B','Construction','Piping',d.isoformat(),(d+timedelta(days=5)).isoformat(),tag=None)
        case('granularity','fine_event_coarse_schedule',{'description':f'{tag} erected at Unit 7 Area B','date':d.isoformat(),'discipline':'Piping','location':'Unit 7 Area B','source_file':'FOREMAN.xlsx'},coarse,relation='PART_OF')

    # 8) New scope: exact unseen asset surrounded by confusing neighbors.
    for k in range(8):
        d=date(2026,11,1)+timedelta(days=k); tag=f'P-{990+k}Z'
        case('new_scope','unplanned_asset',{'description':f'Emergency install {tag} in Unit 8 Area F - not in IFC schedule','date':d.isoformat(),'discipline':'Mechanical','location':'Unit 8 Area F','source_file':'CALL_NOTE.txt'},expected_set=[],relation='NEW_SCOPE',abstain=True)

    # 9) Revision split: historical L5 node -> two current L6 nodes.
    for k in range(8):
        d=date(2026,4,1)+timedelta(days=k); old=uid+1; uid+=1
        # old identity is not current schedule; lineage points to current children.
        uid+=1; a=uid; add_activity(rows,uid,f'Erect header section {k}A',1,'F','Construction','Piping',d.isoformat(),(d+timedelta(days=2)).isoformat())
        uid+=1; b=uid; add_activity(rows,uid,f'Erect header section {k}B',1,'F','Construction','Piping',d.isoformat(),(d+timedelta(days=2)).isoformat())
        lineage += [dict(from_uid=old,to_uid=a,relation='split_candidate',score=.91),dict(from_uid=old,to_uid=b,relation='split_candidate',score=.89)]
        case('revision','schedule_revision_split',{'description':f'Historical header erection package {k} completed before schedule split','date':d.isoformat(),'discipline':'Piping','source_file':'OLD_DPR.pdf','historical_activity_uid':old},expected_set=[a,b],relation='SPLIT_ACROSS',abstain=True)

    # 10) Semantic hard negatives: same asset, adjacent actions; action must win.
    for k in range(16):
        d=date(2026,6,20)+timedelta(days=k); tag=f'V-{610+k}'
        ids={}
        for action in ['Erect','Weld','Hydrotest','Inspect']:
            uid+=1; add_activity(rows,uid,f'{action} {tag}',3,'E','Construction','Piping',d.isoformat(),(d+timedelta(days=2)).isoformat(),tag); ids[action]=uid
        target_action=['Erect','Weld','Hydrotest','Inspect'][k%4]
        case('hard_negative','same_asset_wrong_action',{'description':f'{tag} {target_action.lower()} work completed in Area E','date':d.isoformat(),'discipline':'Piping','location':'Unit 3 Area E','source_file':'DPR.xlsx'},ids[target_action])

    # Longitudinal reality-graph scenarios. These are evaluated separately from ranking.
    for k in range(6):
        tagx=f'P-{500+k}A'; tagy=f'P-{500+k}B'; d=date(2026,2,1)+timedelta(days=k*5)
        obs=[
          {'id':f'{split}-rep-{k}-1','description':f'{tagx} installed at Unit 2 Area C 05:00','date':d.isoformat(),'time':'05:00','source_file':'DPR.xlsx','location':'Unit 2 Area C'},
          {'id':f'{split}-rep-{k}-2','description':f'{tagx} installed at Unit 2 Area C','date':d.isoformat(),'time':'05:10','source_file':'WHATSAPP.txt','location':'Unit 2 Area C'},
          {'id':f'{split}-rep-{k}-3','description':f'{tagx} failed and was removed after bearing damage','date':(d+timedelta(days=2)).isoformat(),'time':'14:00','source_file':'SITE_DIARY.pdf','location':'Unit 2 Area C'},
          {'id':f'{split}-rep-{k}-4','description':f'Correction: {tagx} was replaced with {tagy} again; notified on WhatsApp because {tagx} broke','date':(d+timedelta(days=20)).isoformat(),'time':'09:00','source_file':'MONTHLY_REPORT.xlsx','location':'Unit 2 Area C'},
        ]
        stream_scenarios.append({'id':f'{split}-replacement-{k}','kind':'replacement_monthly_correction','observations':obs,
                                 'expect':{'max_canonical_events':4,'min_corroborations':1,'min_supersessions':1,'replacement_old':tagx,'replacement_new':tagy}})
    for k in range(5):
        tag=f'CBL-{8800+k}'; d=date(2026,3,10)+timedelta(days=k*4)
        obs=[
          {'id':f'{split}-rw-{k}-1','description':f'{tag} cable pulled and completed in Unit 4 Area A','date':d.isoformat(),'source_file':'ELEC_DPR.xlsx','location':'Unit 4 Area A'},
          {'id':f'{split}-rw-{k}-2','description':f'{tag} removed after insulation test failed','date':(d+timedelta(days=1)).isoformat(),'source_file':'QC_LOG.pdf','location':'Unit 4 Area A'},
          {'id':f'{split}-rw-{k}-3','description':f'{tag} reinstalled again after repair at Unit 4 Area B','date':(d+timedelta(days=3)).isoformat(),'source_file':'ELEC_DPR.xlsx','location':'Unit 4 Area B'},
          {'id':f'{split}-rw-{k}-4','description':f'{tag} cable pull completed after rework at Unit 4 Area B','date':(d+timedelta(days=4)).isoformat(),'source_file':'QC_CLOSEOUT.pdf','location':'Unit 4 Area B'},
        ]
        stream_scenarios.append({'id':f'{split}-rework-{k}','kind':'remove_reinstall_different_zone','observations':obs,
                                 'expect':{'min_canonical_events':4,'min_supersessions':2,'preserve_locations':['area:a','area:b']}})
    for k in range(5):
        tag=f'PT-{1600+k}'; d=date(2026,4,15)+timedelta(days=k)
        obs=[
          {'id':f'{split}-ct-{k}-1','description':f'{tag} calibration completed and accepted','date':d.isoformat(),'source_file':'INST_DPR.xlsx'},
          {'id':f'{split}-ct-{k}-2','description':f'{tag} calibration not completed; QC rejected due zero drift','date':d.isoformat(),'source_file':'QC_NOTE.pdf'},
        ]
        stream_scenarios.append({'id':f'{split}-contradict-{k}','kind':'same_day_source_contradiction','observations':obs,
                                 'expect':{'min_contradictions':1}})

    return rows,rels,cases,history,lineage,stream_scenarios

def write_csv(path,rows,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:
        path.write_text('',encoding='utf-8'); return
    fields=fields or sorted({k for r in rows for k in r})
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def main():
    out=HERE/'data'; out.mkdir(exist_ok=True)
    meta={}
    for split,seed in [('dev',8101),('test',9207)]:
        rows,rels,cases,history,lineage,streams=build(split,seed)
        sd=out/split; sd.mkdir(exist_ok=True)
        write_csv(sd/'schedule.csv',rows)
        write_csv(sd/'relationships.csv',rels)
        write_csv(sd/'history_events.csv',history)
        write_csv(sd/'lineage.csv',lineage)
        (sd/'cases.jsonl').write_text('\n'.join(json.dumps(x) for x in cases)+'\n',encoding='utf-8')
        (sd/'reality_streams.jsonl').write_text('\n'.join(json.dumps(x) for x in streams)+'\n',encoding='utf-8')
        # Human-readable report exports: same observations in mixed reporting cadences.
        daily=[{'id':c['id'],'date':c['evidence'].get('date'),'discipline':c['evidence'].get('discipline'),'location':c['evidence'].get('location'),'description':c['evidence'].get('description')} for c in cases if 'MONTHLY' not in str(c['evidence'].get('source_file'))]
        monthly=[]
        for s in streams:
            monthly.extend([{'scenario':s['id'],'date':o.get('date'),'description':o.get('description'),'source_file':o.get('source_file')} for o in s['observations'] if 'MONTHLY' in str(o.get('source_file')) or 'QC' in str(o.get('source_file'))])
        write_csv(sd/'daily_reports.csv',daily)
        write_csv(sd/'monthly_corrections.csv',monthly)
        meta[split]={'seed':seed,'activities':len(rows),'relationships':len(rels),'resolver_cases':len(cases),'reality_streams':len(streams)}
    files=[]
    for p in sorted(out.rglob('*')):
        if p.is_file(): files.append({'file':str(p.relative_to(HERE)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
    meta['files']=files
    (HERE/'benchmark_meta.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in meta.items() if k!='files'},indent=2))
if __name__=='__main__': main()
