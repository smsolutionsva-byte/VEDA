"""One-command, offline verification suite for the VEDA 0.4 release."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    "v040_execution_proof_regression_test.py",
    "field_capture_actuals_regression_test.py",
    "review_voice_rag_regression_test.py",
    "execution_controls_regression_test.py",
    "execution_lifecycle_regression_test.py",
    "dcr_pipeline_acceptance_test.py",
    "source_semantics_smoke_test.py",
    "metarank_integration_test.py",
]


def run(command: list[str], label: str, env: dict) -> bool:
    print("\n==", label, "==")
    result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if result.returncode:
        print("FAILED:", label, "(exit", result.returncode, ")")
        return False
    return True


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    ok = run([sys.executable, "-m", "compileall", "-q", "veda", "tools"],
             "Python syntax", env)
    node = shutil.which("node")
    if node:
        for source in ("veda/web/app.js", "veda/web/views.js", "veda/web/field-capture.js",
                       "veda/web/spatial-control.js"):
            ok = run([node, "--check", source], "JavaScript syntax: " + source, env) and ok
        for test in ("tools/shell_ui_regression_test.js", "tools/ask_ui_regression_test.js",
                     "tools/dashboard_ui_regression_test.js",
                     "tools/execution_ui_regression_test.js"):
            ok = run([node, str(ROOT / test)], test, env) and ok
    else:
        print("SKIP JavaScript syntax: node is not installed")
    for test in TESTS:
        ok = run([sys.executable, str(ROOT / "tools" / test)], test, env) and ok
    print("\nVEDA 0.4 verification:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
