"""Strict structured agent output (spec 43) and provenance (spec 44).

VEDA never parses free prose from a model. The agent returns JSON matching
AgentResult; anything that does not validate is rejected and preserved for
inspection rather than half-applied.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import (AliasChoices, BaseModel, ConfigDict, Field,
                      ValidationError, field_validator)


class _Base(BaseModel):
    """Accept the obvious synonyms a model reaches for.

    Rejecting a whole evidence link because the model wrote "evidence_id"
    instead of "evidence_ref" costs real information for no benefit. The
    schema stays strict about meaning and forgiving about spelling.
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

# spec 44 - every important fact declares where it came from
Provenance = Literal[
    "MCP_FACT",                 # a schedule fact read from Horizun
    "SOURCE_FILE",              # read verbatim out of an uploaded document
    "HUMAN_INPUT",              # a person said so
    "AI_INFERENCE",             # the model concluded it
    "DETERMINISTIC_CALCULATION",  # VEDA computed it by rule
    "DERIVED",                  # rolled up from other stored rows
]

EvidenceState = Literal[
    "new", "processing", "linked", "needs_review", "confirmed",
    "rejected", "duplicate", "conflicting", "quarantined", "historical",
    "context", "issue", "deferred",
]

# An uploaded document is a container of heterogeneous observations. Only
# activity-progress / general observations are resolved against the schedule.
ObservationType = Literal[
    "activity_progress", "manpower", "equipment", "weather", "issue",
    "target", "report_metadata", "signoff", "general",
]

LinkRelation = Literal[
    "supporting", "conflicting", "historical", "duplicate", "weak", "unresolved",
]

ReviewKind = Literal[
    "clarification", "evidence_decision", "schedule_authority", "conflict",
    "issue_confirmation", "risk_confirmation", "schedule_approval",
    "security_review", "failed_validation",
]


class EvidenceItem(_Base):
    ref: str = Field(validation_alias=AliasChoices("ref", "id", "evidence_id",
                                                   "evidence_ref"),
                     description="Stable reference used to cite this item")
    source_file: str | None = None
    locator: str | None = Field(None, description="page / sheet / row")
    date: str | None = None
    author: str | None = None
    contractor: str | None = None
    crew: str | None = None
    discipline: str | None = None
    location: str | None = None
    chainage: str | None = None
    quantity: float | None = None
    unit: str | None = None
    description: str = ""
    observed_progress: float | None = Field(
        None, description="Observed field progress percent. Never official progress.")
    observation_type: ObservationType = Field(
        "activity_progress",
        description="Kind of observation. Only activity_progress / general are "
                    "resolved against schedule activities.")
    section: str | None = None
    confidence: float = 0.5
    state: EvidenceState = "new"
    provenance: Provenance = "SOURCE_FILE"

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class EvidenceLink(_Base):
    """A candidate association, not an accepted fact (spec 35)."""
    evidence_ref: str = Field(validation_alias=AliasChoices(
        "evidence_ref", "evidence_id", "ref", "id"))
    activity_uid: int | None = Field(None, validation_alias=AliasChoices(
        "activity_uid", "uid", "activity"))
    activity_name: str | None = None
    confidence: float = 0.5
    relation: LinkRelation = "supporting"
    supporting_signals: list = Field(default_factory=list)
    conflicting_signals: list = Field(default_factory=list)
    provenance: Provenance = "AI_INFERENCE"

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class Issue(_Base):
    """A problem that already exists (spec 30, 32)."""
    ref: str | None = None
    title: str
    description: str = ""
    source: str | None = None
    status: str = "open"
    priority: str = "medium"
    severity: str = "medium"
    owner: str | None = None
    date: str | None = None
    target_resolution: str | None = None
    activity_uids: list = Field(default_factory=list,
                                validation_alias=AliasChoices(
                                    "activity_uids", "activity_uid", "uids"))
    wbs: str | None = None
    schedule_impact_days: float | None = None
    schedule_impact_note: str | None = None
    evidence_refs: list = Field(default_factory=list,
                                validation_alias=AliasChoices(
                                    "evidence_refs", "evidence_ids", "evidence"))
    confidence: float = 0.6
    provenance: Provenance = "AI_INFERENCE"


class Risk(_Base):
    """A possible future event (spec 31, 32)."""
    ref: str | None = None
    title: str
    description: str = ""
    category: str | None = None
    probability: str = "medium"
    impact: str = "medium"
    rating: str | None = None
    owner: str | None = None
    status: str = "open"
    mitigation: str | None = None
    trigger: str | None = None
    activity_uids: list = Field(default_factory=list,
                                validation_alias=AliasChoices(
                                    "activity_uids", "activity_uid", "uids"))
    wbs: str | None = None
    schedule_impact_days: float | None = None
    critical_path_relevance: str | None = None
    evidence_refs: list = Field(default_factory=list,
                                validation_alias=AliasChoices(
                                    "evidence_refs", "evidence_ids", "evidence"))
    confidence: float = 0.6
    provenance: Provenance = "AI_INFERENCE"


class ReviewQuestion(_Base):
    """One question standing for a whole cluster of ambiguity (spec 41)."""
    kind: ReviewKind = "clarification"
    title: str
    question: str
    detail: str | None = None
    options: list = Field(default_factory=list)
    cluster_key: str | None = None
    affected_evidence_refs: list = Field(
        default_factory=list,
        validation_alias=AliasChoices("affected_evidence_refs",
                                      "affected_evidence_ids", "affected_ids"))
    entity_type: str | None = None
    entity_id: str | None = None
    priority: str = "normal"


class ChangeProposal(_Base):
    """A durable task proposal. Never applied without dry-run + approval.

    update keeps the v0.1.1 field/proposed_value shape. create/delete are
    explicit operations so a human change request can safely ask for structural
    schedule edits without smuggling them into a fake field update.
    """
    operation: Literal["update", "create", "delete"] = "update"
    target_type: str = "activity"
    target_uid: int | None = Field(None, validation_alias=AliasChoices(
        "target_uid", "uid", "activity_uid"))
    target_name: str | None = None
    parent_uid: int | None = None
    after_uid: int | None = None
    field: str | None = None
    current_value: str | None = None
    proposed_value: str | None = None
    task_fields: dict = Field(default_factory=dict)
    reason: str = ""
    evidence_refs: list = Field(default_factory=list,
                                validation_alias=AliasChoices(
                                    "evidence_refs", "evidence_ids", "evidence"))
    confidence: float = 0.5
    provenance: Provenance = "AI_INFERENCE"


class Artifact(_Base):
    kind: str = "report"
    title: str
    format: str = "markdown"
    content: str | None = None
    description: str | None = None


class ScheduleFinding(_Base):
    """A grounded observation about the schedule, citing its basis."""
    title: str
    detail: str = ""
    activity_uids: list = Field(default_factory=list,
                                validation_alias=AliasChoices(
                                    "activity_uids", "activity_uid", "uids"))
    basis: str = ""
    provenance: Provenance = "AI_INFERENCE"


class AgentResult(_Base):
    summary: str = ""
    schedule_findings: list = Field(default_factory=list)
    evidence: list = Field(default_factory=list)
    evidence_links: list = Field(default_factory=list)
    issues: list = Field(default_factory=list)
    risks: list = Field(default_factory=list)
    review_questions: list = Field(default_factory=list)
    change_proposals: list = Field(default_factory=list)
    artifacts: list = Field(default_factory=list)
    notes: list = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def _ev(cls, v):
        return _coerce_list(v, EvidenceItem)

    @field_validator("evidence_links", mode="before")
    @classmethod
    def _el(cls, v):
        return _coerce_list(v, EvidenceLink)

    @field_validator("issues", mode="before")
    @classmethod
    def _is(cls, v):
        return _coerce_list(v, Issue)

    @field_validator("risks", mode="before")
    @classmethod
    def _rk(cls, v):
        return _coerce_list(v, Risk)

    @field_validator("review_questions", mode="before")
    @classmethod
    def _rq(cls, v):
        return _coerce_list(v, ReviewQuestion)

    @field_validator("change_proposals", mode="before")
    @classmethod
    def _cp(cls, v):
        return _coerce_list(v, ChangeProposal)

    @field_validator("artifacts", mode="before")
    @classmethod
    def _ar(cls, v):
        return _coerce_list(v, Artifact)

    @field_validator("schedule_findings", mode="before")
    @classmethod
    def _sf(cls, v):
        return _coerce_list(v, ScheduleFinding)


def _coerce_list(v: Any, model: type) -> list:
    """Drop individually malformed rows instead of failing the whole result.

    A model that gets one of forty evidence rows wrong should not cost the
    other thirty-nine; the dropped rows are reported in the parse notes.
    """
    if v is None:
        return []
    if isinstance(v, dict):
        v = [v]
    if not isinstance(v, list):
        return []
    out = []
    for item in v:
        if isinstance(item, model):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        try:
            out.append(model(**item))
        except ValidationError:
            continue
    return out


class ParseOutcome(BaseModel):
    ok: bool
    result: AgentResult | None = None
    error: str | None = None
    raw_excerpt: str | None = None
    dropped: int = 0
    drop_reasons: list = Field(default_factory=list)


_LIST_MODELS = {
    "evidence": EvidenceItem, "evidence_links": EvidenceLink, "issues": Issue,
    "risks": Risk, "review_questions": ReviewQuestion,
    "change_proposals": ChangeProposal, "artifacts": Artifact,
    "schedule_findings": ScheduleFinding,
}


def _prevalidate(data: dict) -> tuple:
    """Drop malformed rows up front so the reason can be reported, not guessed."""
    cleaned = dict(data)
    reasons: list = []
    dropped = 0
    for key, model in _LIST_MODELS.items():
        v = data.get(key)
        if v is None:
            continue
        if isinstance(v, dict):
            v = [v]
        if not isinstance(v, list):
            reasons.append(key + ": expected a list, got " + type(v).__name__)
            cleaned[key] = []
            continue
        keep = []
        for n, item in enumerate(v):
            if not isinstance(item, dict):
                dropped += 1
                reasons.append(key + "[" + str(n) + "]: not an object")
                continue
            try:
                model(**item)
                keep.append(item)
            except ValidationError as exc:
                dropped += 1
                first = exc.errors()[0] if exc.errors() else {}
                loc = ".".join(str(x) for x in first.get("loc", ()))
                reasons.append(key + "[" + str(n) + "]." + loc + ": " +
                               str(first.get("msg", "invalid")))
        cleaned[key] = keep
    return cleaned, dropped, reasons[:25]


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_agent_result(text: str | dict) -> ParseOutcome:
    """Validate an agent payload. Rejects malformed results safely (spec 43)."""
    if isinstance(text, dict):
        data = text
    else:
        raw = (text or "").strip()
        if not raw:
            return ParseOutcome(ok=False, error="empty agent output")
        data = _extract_json(raw)
        if data is None:
            return ParseOutcome(ok=False, error="no JSON object found in agent output",
                                raw_excerpt=raw[:1200])
    if not isinstance(data, dict):
        return ParseOutcome(ok=False, error="agent output was not a JSON object")

    cleaned, dropped, reasons = _prevalidate(data)
    try:
        result = AgentResult(**cleaned)
    except ValidationError as exc:
        return ParseOutcome(ok=False, error=str(exc)[:1500],
                            raw_excerpt=json.dumps(data)[:1200])
    return ParseOutcome(ok=True, result=result, dropped=dropped,
                        drop_reasons=reasons)


def _extract_json(raw: str):
    m = _FENCE.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    while start != -1:
        depth, instr, esc = 0, False, False
        for i in range(start, len(raw)):
            c = raw[i]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
                continue
            if c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i + 1])
                    except Exception:
                        break
        start = raw.find("{", start + 1)
    return None


def json_schema() -> dict:
    """JSON Schema handed to providers that support structured output."""
    schema = AgentResult.model_json_schema()
    schema["additionalProperties"] = False
    return schema
