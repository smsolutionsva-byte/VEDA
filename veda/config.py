"""VEDA runtime configuration.

Everything is local. No cloud services are required beyond the reasoning
provider the operator chooses (Claude Code CLI, or Gemini/Antigravity).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VEDA_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "veda.db"
PROJECTS_DIR = DATA_DIR / "projects"
OUTPUTS_DIR = DATA_DIR / "outputs"
WEB_DIR = Path(__file__).resolve().parent / "web"

HOST = os.environ.get("VEDA_HOST", "127.0.0.1")
PORT = int(os.environ.get("VEDA_PORT", "8770"))

# ---------------------------------------------------------------- Horizun MCP
def _find_horizun() -> str:
    explicit = os.environ.get("VEDA_HORIZUN_CMD")
    if explicit:
        return explicit
    found = shutil.which("horizun-msproject-mcp")
    if found:
        return found
    # dotnet global tools default location
    for cand in (
        Path.home() / ".dotnet" / "tools" / "horizun-msproject-mcp.exe",
        Path.home() / ".dotnet" / "tools" / "horizun-msproject-mcp",
    ):
        if cand.exists():
            return str(cand)
    return "horizun-msproject-mcp"


HORIZUN_CMD = _find_horizun()
HORIZUN_TIMEOUT = int(os.environ.get("VEDA_HORIZUN_TIMEOUT", "180"))

# Provider-neutral. "claude_code", "antigravity" and "local_antigravity" all
# implement AgentProvider.
def _default_provider() -> str:
    """Pick the best provider based on what's available."""
    explicit = os.environ.get("VEDA_AGENT_PROVIDER")
    if explicit:
        return explicit
    # Running inside Antigravity IDE → use the local agent bridge
    if os.environ.get("ANTIGRAVITY_AGENTAPI_EXE"):
        return "local_antigravity"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "antigravity"
    return "claude_code"

AGENT_PROVIDER = _default_provider()
CLAUDE_CMD = os.environ.get("VEDA_CLAUDE_CMD") or shutil.which("claude") or "claude"
CLAUDE_MODEL = os.environ.get("VEDA_CLAUDE_MODEL", "sonnet")
AGENT_TIMEOUT = int(os.environ.get("VEDA_AGENT_TIMEOUT", "900"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.environ.get("VEDA_GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_BASE = os.environ.get(
    "VEDA_GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta"
)

# Deterministic fallback: when no reasoning provider is reachable, VEDA still
# runs the MCP schedule pipeline and rule-based evidence extraction so the
# platform is demonstrable end to end. Inference-grade output is then simply
# absent rather than fabricated.
ALLOW_DETERMINISTIC_FALLBACK = (
    os.environ.get("VEDA_ALLOW_FALLBACK", "1").lower() not in ("0", "false", "no")
)

# ------------------------------------------------------------------- Security
MAX_UPLOAD_MB = int(os.environ.get("VEDA_MAX_UPLOAD_MB", "200"))
SCHEDULE_EXTS = {
    ".xer", ".mpp", ".mpt", ".mpx", ".xml", ".pmxml", ".pp", ".planner", ".sdef",
}
EVIDENCE_EXTS = {
    ".csv", ".xlsx", ".xlsm", ".xls", ".pdf", ".docx", ".txt", ".json", ".md", ".log",
}


def ensure_dirs() -> None:
    for d in (DATA_DIR, PROJECTS_DIR, OUTPUTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    p = PROJECTS_DIR / project_id
    (p / "files").mkdir(parents=True, exist_ok=True)
    (p / "revisions").mkdir(parents=True, exist_ok=True)
    (p / "outputs").mkdir(parents=True, exist_ok=True)
    return p
