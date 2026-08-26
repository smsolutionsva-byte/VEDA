from __future__ import annotations
import os, tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp(prefix="veda-smooth-"))
os.environ["VEDA_DATA_DIR"] = str(tmp)

from veda import db, reviews, jobs
from veda.pipeline import linking

db.init_db()
pid = db.insert("projects", {"name":"Smooth", "status":"active", "created_at":db.now(), "updated_at":db.now()})
snap = db.insert("schedule_snapshots", {"project_id":pid,"revision":1,"is_current":1,"task_count":2,"created_at":db.now()})
for uid, did, name, wbs in [(1,"A-1","Cable tray installation","ELEC.A"),(2,"A-2","Cable tray installation","ELEC.B")]:
    db.insert("activities", {"project_id":pid,"snapshot_id":snap,"uid":uid,"display_id":did,"name":name,"wbs":wbs,"start":"2026-01-01","finish":"2026-12-31","created_at":db.now()})

# Two evidence rows with same candidate set should create one precise review.
ids=[]
for n in range(2):
    ids.append(db.insert("evidence", {"project_id":pid,"source_file":"dpr.txt","description":"electrical cable tray installation","discipline":"electrical","state":"new","date":"2026-06-01","created_at":db.now()}))
linking.link_evidence(pid, evidence_rows=db.q("SELECT * FROM evidence WHERE project_id=?",[pid]))
rr=reviews.open_for(pid)
assert len(rr)==1, rr
r=rr[0]
assert all("A-" in o or o=="Leave unassigned for now" for o in r["options"]), r["options"]
choice=next(o for o in r["options"] if o.startswith("A-1"))
r=reviews.answer(r["id"], answer_text=choice, wake=False)
effect=linking.apply_cluster_answer(pid,r)
reviews.record_effect(r["id"],effect)
assert effect["assigned"]==2, effect
assert (db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=? AND state='confirmed'",[pid]) or {})["c"]==2
assert not db.q("SELECT id FROM jobs WHERE project_id=? AND kind='resume_review'",[pid])

# New matching evidence reuses the same human mapping in the same revision.
e3=db.insert("evidence", {"project_id":pid,"source_file":"dpr2.txt","description":"electrical cable tray installation","discipline":"electrical","state":"new","date":"2026-06-02","created_at":db.now()})
linking.link_evidence(pid, evidence_rows=[db.q1("SELECT * FROM evidence WHERE id=?",[e3])])
assert db.q1("SELECT state FROM evidence WHERE id=?",[e3])["state"]=="confirmed"
assert len(reviews.open_for(pid))==0

# HTTP review endpoint applies a clarification synchronously with no resume job.
from veda.api.routes import answer_review
e4=db.insert("evidence", {"project_id":pid,"source_file":"manual.txt","description":"manual ambiguous row","state":"needs_review","created_at":db.now()})
label="A-2 · Cable tray installation · ELEC.B"
rid2=reviews.create(project_id=pid, kind="clarification", title="Manual ambiguity", question="Choose activity",
                    options=[label,"Leave unassigned for now"], affected_ids=[e4], cluster_key="manual|cands=2",
                    extra={"option_uids":{label:2}})
resp=answer_review(rid2, {"answer":label,"by":"tester"})
assert resp["effect"]["assigned"]==1, resp
assert db.q1("SELECT state FROM evidence WHERE id=?",[e4])["state"]=="confirmed"
assert not db.q("SELECT id FROM jobs WHERE project_id=? AND kind='resume_review' AND status IN ('queued','running')",[pid])

# Explicit correction reverses every link created/reused from that review.
reopened=reviews.reopen(r["id"])
all_ids=reopened["affected_ids"]
assert len(all_ids)==3, all_ids
assert not db.q("SELECT id FROM evidence_links WHERE review_id=?",[r["id"]])

# Revision change makes old open clarification stale, never silently reusable.
db.ex("UPDATE schedule_snapshots SET is_current=0 WHERE project_id=?",[pid])
snap2=db.insert("schedule_snapshots", {"project_id":pid,"revision":2,"is_current":1,"task_count":2,"created_at":db.now()})
reviews.invalidate_stale(pid)
assert reviews.get(r["id"])["status"]=="stale"

# Legacy awaiting_review and duplicate queued analysis normalize at startup.
j1=db.insert("jobs", {"project_id":pid,"kind":"analysis","status":"queued","result_json":db.jdumps({"input":{"a":1}}),"created_at":db.now()})
j2=db.insert("jobs", {"project_id":pid,"kind":"analysis","status":"queued","result_json":db.jdumps({"input":{"b":2}}),"created_at":db.now()+1})
j3=db.insert("jobs", {"project_id":pid,"kind":"analysis","status":"awaiting_review","created_at":db.now()})
pending=jobs._recover_startup_jobs()
assert db.q1("SELECT status FROM jobs WHERE id=?",[j3])["status"]=="done"
queued=db.q("SELECT id FROM jobs WHERE project_id=? AND kind='analysis' AND status='queued'",[pid])
assert len(queued)==1, queued
print("smooth workflow smoke test: ok")
