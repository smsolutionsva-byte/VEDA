"""Audit trail (spec 49).

Every meaningful action is recorded with who did it, what changed, whether it
was approved and whether the result was verified. Audit rows are append-only.
"""
from __future__ import annotations

from typing import Any

from . import db


def record(project_id: str | None, *, actor: str = "system",
           actor_type: str = "system", action: str, tool: str | None = None,
           source: str | None = None, entity_type: str | None = None,
           entity_id: str | None = None, previous_value: Any = None,
           new_value: Any = None, approval: str | None = None,
           verification: str | None = None, result: str | None = None,
           job_id: str | None = None, detail: dict | None = None) -> str:
    return db.insert("audit", {
        "project_id": project_id, "job_id": job_id,
        "actor": actor, "actor_type": actor_type,
        "action": action, "tool": tool, "source": source,
        "entity_type": entity_type, "entity_id": entity_id,
        "previous_value": _s(previous_value), "new_value": _s(new_value),
        "approval": approval, "verification": verification,
        "result": _s(result),
        "detail_json": db.jdumps(detail) if detail else None,
    })


def _s(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return db.jdumps(v)
    return str(v)[:4000]


def for_project(project_id: str, limit: int = 300, offset: int = 0,
                entity_type: str | None = None,
                entity_id: str | None = None) -> list:
    sql = "SELECT * FROM audit WHERE project_id=?"
    params: list = [project_id]
    if entity_type:
        sql += " AND entity_type=?"
        params.append(entity_type)
    if entity_id:
        sql += " AND entity_id=?"
        params.append(entity_id)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = db.q(sql, params)
    for r in rows:
        r["detail"] = db.jloads(r.pop("detail_json", None), {})
    return rows
