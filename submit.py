import json
import urllib.request

job_data = json.load(open("job.json"))
overview = json.load(open("overview.json"))

out_json = {
    "summary": "Project analysis completed. Schedule health is 75.0% with some missing logic.",
    "schedule_findings": [
        {
            "finding_title": "Missing logic",
            "description": "3 of 22 activities (13.6%) have no predecessor or no successor.",
            "provenance": "MCP_FACT",
            "impact": "Schedule accuracy may be reduced."
        }
    ],
    "evidence": [],
    "evidence_links": [],
    "issues": [],
    "risks": [],
    "review_questions": [],
    "change_proposals": [],
    "artifacts": [],
    "notes": []
}

payload = {
    "inbox_id": job_data["item"]["inbox_id"],
    "result": out_json,
    "events": []
}

req = urllib.request.Request(
    'http://127.0.0.1:8770/api/agent/result',
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

try:
    response = urllib.request.urlopen(req)
    print("Success:", response.read().decode())
except Exception as e:
    print("Error:", e)
    if hasattr(e, 'read'):
        print(e.read().decode())
