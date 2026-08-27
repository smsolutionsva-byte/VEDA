#!/usr/bin/env python3
"""Semantic integration audit for VEDA's resolution stack.

This intentionally uses Python AST inspection instead of grep-only checks, so
renaming ACCEPT -> 0.5 inside a function does not fool the audit.
"""
from pathlib import Path
import ast, json, re


def root():
    here=Path(__file__).resolve().parent
    for p in [here,*here.parents]:
        if (p/'veda'/'pipeline'/'linking.py').exists(): return p
    raise SystemExit('Put benchmark folder inside VEDA repo root.')

p=root(); findings=[]
link_path=p/'veda'/'pipeline'/'linking.py'; engine_path=p/'veda'/'retrieval'/'engine.py'
risk_path=p/'veda'/'resolution'/'risk.py'; ranker_path=p/'veda'/'resolution'/'ranker.py'
link=link_path.read_text(encoding='utf-8',errors='replace')
engine=engine_path.read_text(encoding='utf-8',errors='replace') if engine_path.exists() else ''
ranker=ranker_path.read_text(encoding='utf-8',errors='replace') if ranker_path.exists() else ''
risk=risk_path.read_text(encoding='utf-8',errors='replace') if risk_path.exists() else ''

def add(check,ok,note=''): findings.append({'check':check,'ok':bool(ok),'note':note})

add('hybrid_search_exists','def hybrid_search' in engine)
add('engineering_ranker_exists','def rank(' in ranker and 'engineering_rank_score' in ranker)
add('risk_policy_exists','def assess(' in risk and 'schedule_write_allowed' in risk)
add('production_linker_calls_hybrid_search','retrieval_engine.hybrid_search' in link or 'hybrid_search(' in link)
add('production_linker_uses_risk_policy','risk_policy.assess' in link)
add('calibrated_probability_used_in_linker','calibrated_probability' in link)
add('legacy_candidates_for_unused', not bool(re.search(r'\bcandidates_for\s*\(', link[link.find('def link_evidence'):])),'Legacy helper may remain for compatibility but must not drive production linking.')

# AST: detect literal numeric comparisons in link_evidence itself.  A decision
# policy module may legitimately contain defaults; policy must not be hidden in
# the orchestrator.
tree=ast.parse(link)
literal_thresholds=[]
for node in ast.walk(tree):
    if isinstance(node,ast.FunctionDef) and node.name=='link_evidence':
        for x in ast.walk(node):
            if isinstance(x,ast.Compare):
                vals=[]
                sides=[x.left,*x.comparators]
                for side in sides:
                    if isinstance(side,ast.Constant) and isinstance(side.value,(int,float)) and side.value not in (0,1):
                        vals.append(side.value)
                if vals: literal_thresholds.extend(vals)
add('linker_has_no_hidden_numeric_policy_thresholds',not literal_thresholds,
    'Found literal compare values: '+repr(literal_thresholds) if literal_thresholds else 'Policy lives outside link_evidence.')

# Ranking vs calibration separation.
add('rank_score_separate_from_probability','rank_score' in link and 'calibrated_probability' in link)
add('recommended_vs_committed_uid_separate','recommended_uid' in link and 'committed_uid' in link)
add('event_state_separate_from_activity_identity','classify_event' in link and 'event_state' in link)
add('execution_event_layer_present','execution_events' in link)

# Database/schema checks.
db=(p/'veda'/'db.py').read_text(encoding='utf-8',errors='replace')
for table in ('execution_events','execution_event_sources','activity_lineage','retrieval_documents'):
    add('schema_'+table,('CREATE TABLE IF NOT EXISTS '+table) in db)
add('native_sparse_persisted','sparse_json' in db and 'bge_sparse' in engine)

print(json.dumps(findings,indent=2))
failed=[x for x in findings if not x['ok']]
print('\nSTATUS:', 'PASS' if not failed else 'FINDINGS')
if failed:
    print('Inspect these findings; do not patch merely to satisfy the audit:')
    for x in failed: print('-',x['check'],x.get('note',''))
