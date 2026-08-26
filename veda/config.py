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

# Provider-neutral reasoning.  Auto mode is deliberately ordered by operator
# preference: Antigravity first, Claude Code second, Codex third.  Availability
# is checked at runtime for every job, and a provider that is installed but not
# authenticated / temporarily offline is skipped without blocking the queue.
def _default_provider() -> str:
    if os.environ.get("ANTIGRAVITY_AGENTAPI_EXE"):
        return "local_antigravity"
    return os.environ.get("VEDA_AGENT_PROVIDER", "auto").strip() or "auto"

AGENT_PROVIDER = _default_provider()

def _find_antigravity_cli() -> str:
    explicit = os.environ.get("VEDA_ANTIGRAVITY_CMD")
    if explicit:
        return explicit
    found = shutil.which("agy")
    if found:
        return found
    # Official installers use these locations when PATH has not refreshed yet.
    local = os.environ.get("LOCALAPPDATA")
    candidates = []
    if local:
        candidates.append(Path(local) / "agy" / "bin" / "agy.exe")
    candidates.extend([Path.home() / ".local" / "bin" / "agy",
                       Path.home() / ".local" / "bin" / "agy.exe"])
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return "agy"

ANTIGRAVITY_CMD = _find_antigravity_cli()
# Empty means use the model selected in the operator's Antigravity settings.
ANTIGRAVITY_MODEL = os.environ.get("VEDA_ANTIGRAVITY_MODEL", "").strip() or None
CLAUDE_CMD = os.environ.get("VEDA_CLAUDE_CMD") or shutil.which("claude") or "claude"
CLAUDE_MODEL = os.environ.get("VEDA_CLAUDE_MODEL", "sonnet")
CODEX_CMD = os.environ.get("VEDA_CODEX_CMD") or shutil.which("codex") or "codex"
# Empty means use the Codex CLI's configured/default model.
CODEX_MODEL = os.environ.get("VEDA_CODEX_MODEL", "").strip() or None
AGENT_TIMEOUT = int(os.environ.get("VEDA_AGENT_TIMEOUT", "900"))
# Local Antigravity is an inbox bridge. If no IDE agent claims a job quickly,
# do not hold VEDA's single worker for the full reasoning timeout.
AGENT_CLAIM_TIMEOUT = int(os.environ.get("VEDA_AGENT_CLAIM_TIMEOUT", "30"))

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
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
EVIDENCE_EXTS = {
    ".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".pdf", ".docx", ".txt", ".json", ".md", ".log",
    *IMAGE_EXTS,
}

# OCR is deliberately adaptive: normal PDF text extraction first, OCR only on
# pages that appear image-only / text-poor. This avoids paying OCR cost on every
# page while still handling scanned site diaries and photo PDFs.
OCR_ENABLED = os.environ.get("VEDA_OCR_ENABLED", os.environ.get("VEDA_OCR", "1")).lower() not in ("0", "false", "no")
OCR_DPI = int(os.environ.get("VEDA_OCR_DPI", "170"))
OCR_MAX_PAGES = int(os.environ.get("VEDA_OCR_MAX_PAGES", "250"))


def ensure_dirs() -> None:
    for d in (DATA_DIR, PROJECTS_DIR, OUTPUTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    p = PROJECTS_DIR / project_id
    (p / "files").mkdir(parents=True, exist_ok=True)
    (p / "revisions").mkdir(parents=True, exist_ok=True)
    (p / "outputs").mkdir(parents=True, exist_ok=True)
    return p
