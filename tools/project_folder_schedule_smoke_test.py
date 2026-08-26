"""Regression: project-folder schedule discovery must not miss CSV revisions."""
from __future__ import annotations
import asyncio, os, sys, tempfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory(prefix='veda_folder_sched_')
os.environ['VEDA_DATA_DIR'] = str(Path(_TMP.name) / 'data')
os.environ['VEDA_OCR'] = '0'

from starlette.datastructures import UploadFile
from veda import db
from veda.api.routes import _store_ingestion_batch
from veda.mcpc import tabular_schedule


def sched(extra=''):
    return ("activity_id,name,wbs_path,planned_start,planned_finish,percent_complete,predecessors\n"
            "A1,Mobilise,P1.W1,2026-01-01,2026-01-02,100,\n"
            f"A2,Install{extra},P1.W1,2026-01-03,2026-01-05,40,A1\n").encode()


def main():
    db.init_db()
    pid = db.insert('projects', {'name':'Project 1','status':'active','updated_at':db.now()})

    async def run():
        fs = [UploadFile(filename='current.csv', file=BytesIO(sched())),
              UploadFile(filename='current.csv', file=BytesIO(sched(' extended')))]
        return await _store_ingestion_batch(
            pid, fs, relative_paths=[
                'Project 1/Schedule/current.csv',
                'Project 1/ScheduleExtended/current.csv'])
    r = asyncio.run(run())
    assert r['schedule_count'] == 2, r
    assert r['schedule_selection_required'] is True
    assert r['event'] is None
    paths = [x['relative_path'] for x in r['schedule_candidates']]
    assert 'Project 1/Schedule/current.csv' in paths
    assert 'Project 1/ScheduleExtended/current.csv' in paths
    assert any(x['alternate_hint'] for x in r['schedule_candidates'])
    batch = db.q1('SELECT * FROM ingestion_batches WHERE id=?', [r['batch_id']])
    assert batch['status'] == 'awaiting_schedule'

    # Ordinary progress evidence must not become a schedule merely because it is CSV.
    evidence = Path(_TMP.name) / 'dpr.csv'
    evidence.write_text('date,crew,description,progress\n2026-01-03,A,installed pipe,40\n')
    assert not tabular_schedule.inspect(str(evidence), 'Project 1/Daily Reports/dpr.csv')['candidate']

    # A schedule-shaped table is adaptable to MSPDI for Horizun and preserves source IDs.
    src = Path(_TMP.name) / 'schedule.csv'; src.write_bytes(sched())
    out, meta = tabular_schedule.prepare_mspdi(str(src), str(Path(_TMP.name)/'adapted'))
    assert Path(out).exists() and meta['activity_count'] == 2
    assert meta['by_uid']['1']['source_id'] == 'A1'
    print('project-folder schedule regression: PASS')

if __name__ == '__main__':
    main()
