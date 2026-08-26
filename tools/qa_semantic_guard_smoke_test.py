"""Regression checks for XER QA semantic guards."""
from __future__ import annotations

import tempfile
from pathlib import Path

from veda.mcpc.qa_guard import guard_schedule_qa
from veda.mcpc.schedule_ops import _health_score


def raw_qa():
    findings = [
        {"rule": "dcma_01_logic", "evaluated": True, "passed": False,
         "summary": "missing logic", "uids": [1]},
        {"rule": "dcma_09_invalid_dates", "evaluated": True, "passed": False,
         "summary": "bad dates", "measured": 49.3, "uids": [2]},
        {"rule": "dcma_11_missed_tasks", "evaluated": True, "passed": False,
         "summary": "missed", "measured": 18.9, "uids": [3]},
        {"rule": "dcma_14_bei", "evaluated": True, "passed": False,
         "summary": "bei", "measured": 0.5, "uids": [4]},
    ]
    findings += [
        {"rule": f"pass_{i}", "evaluated": True, "passed": True,
         "summary": "ok", "uids": []}
        for i in range(14)
    ]
    return {"checks": 18, "passed": 14, "failed": 4,
            "notEvaluated": 0, "findings": findings}


def write_xer(path: Path, *, forecast=False, baseline=False,
              actual="2026-08-22 17:00"):
    pfields = ["proj_id", "proj_short_name", "last_recalc_date"]
    prow = ["1", "LIVE", "2026-08-22 12:00"]
    if baseline:
        pfields.append("sum_base_proj_id")
        prow.append("2")

    tfields = ["task_id", "proj_id", "status_code", "target_start_date",
               "target_end_date", "act_start_date", "act_end_date"]
    trow = ["10", "1", "TK_Complete", "2026-08-01 08:00",
            "2026-08-20 17:00", "2026-08-20 08:00", actual]
    if forecast:
        tfields += ["restart_date", "reend_date"]
        trow += ["2026-08-23 08:00", "2026-08-25 17:00"]

    lines = [
        "ERMHDR\t23.12\t2026-08-22\tProject\ttest\ttest\ttest\tPM\tUSD",
        "%T\tPROJECT",
        "%F\t" + "\t".join(pfields),
        "%R\t" + "\t".join(prow),
    ]
    if baseline:
        # Embedded baseline row.  Assignment is proven by sum_base_proj_id.
        bfields = list(pfields)
        # A baseline copy normally carries orig_proj_id; add it to both rows by
        # rebuilding this tiny fixture for clarity.
        lines = [
            lines[0], "%T\tPROJECT",
            "%F\tproj_id\tproj_short_name\tlast_recalc_date\tsum_base_proj_id\torig_proj_id",
            "%R\t1\tLIVE\t2026-08-22 12:00\t2\t",
            "%R\t2\tLIVE-BL\t2026-08-01 12:00\t\t1",
        ]
    lines += [
        "%T\tTASK",
        "%F\t" + "\t".join(tfields),
        "%R\t" + "\t".join(trow),
        "%E",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def by_rule(out, rule):
    return next(f for f in out["findings"] if f["rule"] == rule)


def main():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # 1) Planned dates only: forecast and baseline checks must not be guessed.
        p = td / "planned_only.xer"
        write_xer(p)
        out = guard_schedule_qa(raw_qa(), schedule_path=str(p))
        assert out["passed"] == 14 and out["failed"] == 1 and out["notEvaluated"] == 3
        assert by_rule(out, "dcma_09_invalid_dates")["evaluated"] is False
        assert by_rule(out, "dcma_11_missed_tasks")["evaluated"] is False
        assert by_rule(out, "dcma_14_bei")["evaluated"] is False
        assert _health_score(out) == 93.3

        # 2) A genuinely future actual must still fail DCMA-09 even without forecast fields.
        p = td / "future_actual.xer"
        write_xer(p, actual="2026-08-23 08:00")
        out = guard_schedule_qa(raw_qa(), schedule_path=str(p))
        d9 = by_rule(out, "dcma_09_invalid_dates")
        assert d9["evaluated"] is True and d9["passed"] is False
        assert d9["uids"] == [10]
        assert "actual date violation" in d9["summary"]

        # 3) Same calendar day, later clock time, is not a future-day violation.
        p = td / "same_day.xer"
        write_xer(p, actual="2026-08-22 23:59")
        out = guard_schedule_qa(raw_qa(), schedule_path=str(p))
        assert by_rule(out, "dcma_09_invalid_dates")["evaluated"] is False

        # 4) Real remaining/forecast fields + assigned baseline: do not override Horizun.
        p = td / "fully_semantic.xer"
        write_xer(p, forecast=True, baseline=True)
        out = guard_schedule_qa(raw_qa(), schedule_path=str(p))
        assert by_rule(out, "dcma_09_invalid_dates")["summary"] == "bad dates"
        assert by_rule(out, "dcma_11_missed_tasks")["summary"] == "missed"
        assert by_rule(out, "dcma_14_bei")["summary"] == "bei"
        assert out["failed"] == 4 and out["notEvaluated"] == 0

    print("qa semantic guard smoke test: PASS")


if __name__ == "__main__":
    main()
