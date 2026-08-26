"""Regression checks for source-aware XER normalization."""
from __future__ import annotations

import tempfile
from pathlib import Path

from veda.mcpc.source_semantics import inspect_source


def write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # 1) PROJWBS hierarchy is structure, TASK is activities. Custom WBS
        # separator must be preserved and WBS Summary activity remains a TASK.
        p = td / "structure.xer"
        write(p, """
ERMHDR\t23.12\t2026-08-22\tProject\tt\tt\tt\tPM\tUSD
%T\tPROJECT
%F\tproj_id\tproj_short_name\tclndr_id\tname_sep_char\tplan_start_date\tplan_end_date\tlast_recalc_date\tcritical_path_type
%R\t1\tLIVE\t100\t/\t2026-01-01 08:00\t2026-12-31 17:00\t2026-08-22 12:00\tCT_TotFloat
%T\tCALENDAR
%F\tclndr_id\tday_hr_cnt
%R\t100\t10
%T\tPROJWBS
%F\twbs_id\tproj_id\tparent_wbs_id\twbs_short_name\twbs_name\tproj_node_flag
%R\t10\t1\t\tROOT\tRoot\tY
%R\t11\t1\t10\tA\tArea A\tN
%R\t12\t1\t11\tB\tArea B\tN
%T\tTASK
%F\ttask_id\tproj_id\twbs_id\ttask_code\ttask_name\ttask_type\ttarget_start_date\ttarget_end_date
%R\t1000\t1\t12\tA1\tLeaf\tTT_Task\t2026-01-02 08:00\t2026-02-01 17:00
%R\t1001\t1\t11\tSUM\tSummary activity\tTT_WBS\t2026-01-02 08:00\t2026-02-01 17:00
%E
""")
        m = inspect_source(str(p))
        assert m and m["task_count"] == 2 and m["wbs_count"] == 3
        assert m["task_type_counts"]["TT_WBS"] == 1
        assert m["wbs_nodes"][2]["code"] == "ROOT/A/B"
        assert m["planned_start"] == "2026-01-01"
        assert m["planned_finish"] == "2026-02-01"
        assert m["must_finish_by"] == "2026-12-31"
        assert m["forecast_finish"] is None
        assert m["hours_per_day"] == 10

        # 2) Remaining Early Finish provides current forecast; PROJECT schedule
        # finish takes precedence when present.
        p = td / "forecast.xer"
        write(p, """
%T\tPROJECT
%F\tproj_id\tproj_short_name\tlast_recalc_date\tscd_end_date
%R\t1\tLIVE\t2026-08-22 12:00\t2026-09-05 17:00
%T\tTASK
%F\ttask_id\tproj_id\ttask_type\ttarget_end_date\treend_date
%R\t1\t1\tTT_Task\t2026-08-20 17:00\t2026-09-07 17:00
%E
""")
        m = inspect_source(str(p))
        assert m["forecast_finish"] == "2026-09-05"
        assert m["forecast_basis"] == "PROJECT.scd_end_date"

        # 3) Multi-project XER resolves safely from Horizun task UID overlap.
        p = td / "multi.xer"
        write(p, """
%T\tPROJECT
%F\tproj_id\tproj_short_name\torig_proj_id
%R\t1\tONE\t
%R\t2\tTWO\t
%T\tTASK
%F\ttask_id\tproj_id\ttask_type
%R\t10\t1\tTT_Task
%R\t20\t2\tTT_Task
%E
""")
        amb = inspect_source(str(p))
        assert amb and amb["source_guarded"] is False and amb["ambiguous_project"] is True
        m = inspect_source(str(p), task_uid_hints=[20, 999])
        assert m["source_guarded"] is True and m["project_id"] == "2"
        assert m["task_ids"] == {"20"}

        # 4) Assigned baseline is distinct from the allowed P6 current-project
        # fallback semantics.
        p = td / "baseline.xer"
        write(p, """
%T\tPROJECT
%F\tproj_id\tproj_short_name\tsum_base_proj_id\torig_proj_id
%R\t1\tLIVE\t2\t
%R\t2\tLIVE-BL\t\t1
%T\tTASK
%F\ttask_id\tproj_id\ttask_type
%R\t10\t1\tTT_Task
%R\t11\t2\tTT_Task
%E
""")
        m = inspect_source(str(p))
        assert m["baseline_assigned"] is True and m["baseline_id"] == "2"

        # 5) Malformed WBS parents/cycles cannot recurse forever or convert
        # structure into activity counts.
        p = td / "weird_wbs.xer"
        write(p, """
%T\tPROJECT
%F\tproj_id\tproj_short_name
%R\t1\tLIVE
%T\tPROJWBS
%F\twbs_id\tproj_id\tparent_wbs_id\twbs_short_name\twbs_name
%R\t10\t1\t11\tA\tA
%R\t11\t1\t10\tB\tB
%R\t12\t1\t999\tORPH\tOrphan
%T\tTASK
%F\ttask_id\tproj_id\twbs_id\ttask_type
%R\t1\t1\t12\tTT_Task
%E
""")
        m = inspect_source(str(p))
        assert m["task_count"] == 1 and m["wbs_count"] == 3
        assert any(n["short_code"] == "ORPH" and n["level"] == 1 for n in m["wbs_nodes"])

    print("source semantics smoke test: PASS")


if __name__ == "__main__":
    main()
