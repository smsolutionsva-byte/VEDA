"""Read-only MCP proxy for Horizun.

Reasoning providers may inspect schedule facts, but schedule writes must go
through VEDA's proposal -> validation -> dry-run -> human approval pipeline.
This proxy exposes only the read tools used by VEDA and blocks every write tool.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from veda import __version__, db  # noqa: E402
from veda.mcpc import horizun  # noqa: E402

HORIZUN_READ_TOOLS = [
    "project_health", "project_open", "project_info", "tasks_query",
    "links_query", "resources_query", "timephased_query", "schedule_analyze",
    "schedule_qa", "baseline_compare", "schedule_target", "schedule_recovery",
]

PROJECT_ID = os.environ.get("VEDA_PROJECT_ID", "")
JOB_ID = os.environ.get("VEDA_JOB_ID", "")
ALLOWED = set(HORIZUN_READ_TOOLS)


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def _result(value) -> dict:
    if isinstance(value, dict) and "content" in value:
        return value
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, default=str)}]}


def _tools() -> list[dict]:
    out = []
    try:
        for tool in horizun.list_tools(refresh=False):
            if tool.get("name") in ALLOWED:
                out.append(tool)
    except Exception:
        # Keep startup deterministic: health errors surface on actual tool calls.
        pass
    return out


def main() -> None:
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            resp = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "veda-horizun-readonly", "version": __version__},
            }
        elif method == "tools/list":
            resp = {"tools": _tools()}
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name not in ALLOWED:
                resp = _err("Horizun tool is blocked by VEDA read-only policy: " + str(name))
            else:
                try:
                    value = horizun.call(
                        name, params.get("arguments") or {}, project_id=PROJECT_ID,
                        job_id=JOB_ID, log=True)
                    resp = _result(value)
                except Exception as exc:  # noqa: BLE001
                    resp = _err(type(exc).__name__ + ": " + str(exc))
        elif method in ("notifications/initialized", "notifications/cancelled"):
            continue
        elif method == "ping":
            resp = {}
        else:
            if mid is None:
                continue
            out.write(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32601, "message": "method not found: " + str(method)}}) + "\n")
            out.flush()
            continue
        if mid is not None:
            out.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": resp}) + "\n")
            out.flush()


if __name__ == "__main__":
    db.init_db()
    main()
