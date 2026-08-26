"""VEDA Agent Watcher — polls the inbox and prints context for the Antigravity agent.

Usage:
  python tools/agent_watcher.py [--url http://127.0.0.1:8770] [--interval 10]

This script is a helper that the Antigravity IDE agent can run to watch for
pending jobs. When a job appears, it fetches the context and prints it so the
agent can process it. The agent then uses this script (or direct HTTP calls)
to call VEDA tools and post the result back.

In practice, the Antigravity agent can also poll directly using curl or httpx
without this script.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

try:
    import httpx
except ImportError:
    import urllib.request
    httpx = None  # type: ignore


def _get(url: str) -> dict:
    if httpx:
        r = httpx.get(url, timeout=10)
        return r.json()
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _post(url: str, data: dict) -> dict:
    if httpx:
        r = httpx.post(url, json=data, timeout=30)
        return r.json()
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def poll_once(base: str) -> dict | None:
    """Check the inbox and return the item if one is pending."""
    resp = _get(base + "/api/agent/inbox")
    return resp.get("item")


def call_tool(base: str, tool: str, args: dict, project_id: str) -> dict:
    """Call a VEDA tool via the agent bridge endpoint."""
    return _post(base + "/api/agent/tool", {
        "tool": tool, "args": args, "project_id": project_id})


def post_result(base: str, inbox_id: str, result: dict,
                events: list | None = None) -> dict:
    """Post the structured result back to VEDA."""
    return _post(base + "/api/agent/result", {
        "inbox_id": inbox_id,
        "result": result,
        "events": events or [],
    })


def main():
    parser = argparse.ArgumentParser(description="VEDA Agent Watcher")
    parser.add_argument("--url", default="http://127.0.0.1:8770",
                        help="VEDA server URL")
    parser.add_argument("--interval", type=int, default=10,
                        help="Poll interval in seconds")
    parser.add_argument("--once", action="store_true",
                        help="Poll once and exit")
    args = parser.parse_args()

    print(f"VEDA Agent Watcher")
    print(f"  Server: {args.url}")
    print(f"  Interval: {args.interval}s")
    print()

    while True:
        try:
            item = poll_once(args.url)
            if item:
                print("=" * 70)
                print(f"JOB FOUND: {item['inbox_id']}")
                print(f"  Project: {item['project']['name']} ({item['project_id']})")
                print(f"  Job:     {item['job_id']}")
                print(f"  Files:   {len(item.get('files', []))}")
                print()
                print("PROMPT:")
                print(item["prompt"][:2000])
                print()
                print("=" * 70)
                # In practice, the Antigravity agent reads this output,
                # processes it, and calls post_result()
            else:
                sys.stdout.write(".")
                sys.stdout.flush()
        except Exception as exc:
            print(f"\n[error] {exc}")

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
