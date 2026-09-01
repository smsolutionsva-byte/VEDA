"""Deterministic complexity routing for Ask VEDA.

The router never answers schedule questions itself.  Its only job is deciding
how much reasoning a turn needs: a safe local conversational response, a small
chat model, or the fully grounded project workflow.  Ambiguity is biased toward
the deep lane so speed cannot weaken schedule accuracy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ReasoningMode = Literal["instant", "fast", "deep"]


@dataclass(frozen=True)
class QuestionRoute:
    mode: ReasoningMode
    reason: str


_GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|hiya|yo|sup|good\s+(?:morning|afternoon|evening))"
    r"(?:\s+(?:veda|bro|there))?[!.?\s]*$", re.IGNORECASE)
_THANKS = re.compile(
    r"^\s*(?:thanks|thank\s+you|thx|ty|appreciate\s+it)[!.?\s]*$",
    re.IGNORECASE)
_FAREWELL = re.compile(
    r"^\s*(?:bye|goodbye|see\s+you|later|good\s+night)[!.?\s]*$",
    re.IGNORECASE)
_LAUGHTER = re.compile(
    r"^\s*(?:ha(?:ha)+|lol+|lmao+|rofl|😂+|🤣+|sussy\s+baka)[!.?\s]*$",
    re.IGNORECASE)
_IDENTITY = re.compile(
    r"^\s*(?:who\s+are\s+you|what\s+(?:is|does)\s+(?:this\s+app|veda)|"
    r"what\s+can\s+you\s+do|help)\s*[!.?]*\s*$", re.IGNORECASE)
_WELLBEING = re.compile(
    r"^\s*(?:how\s+are\s+you|how(?:'s|\s+is)\s+it\s+going|you\s+good)"
    r"\s*[!.?]*\s*$", re.IGNORECASE)
_PREVIOUS_USER = re.compile(
    r"\b(?:what|which)\s+(?:was|is)\s+my\s+(?:previous|last)\s+message\b|"
    r"\bwhat\s+did\s+i\s+(?:just\s+)?say\b", re.IGNORECASE)
_PREVIOUS_ASSISTANT = re.compile(
    r"\bwhat\s+did\s+you\s+(?:just\s+)?say\b|"
    r"\brepeat\s+your\s+(?:previous|last)\s+(?:answer|message)\b",
    re.IGNORECASE)

# These terms imply that an answer can change a project decision or assert a
# stored fact.  That always earns the full system prompt, schema and tool path.
_PROJECT_TERMS = re.compile(
    r"\b(?:project|schedule|programme|program|activity|activities|task|tasks|"
    r"wbs|critical\s+path|critical|float|baseline|forecast|finish|start|"
    r"milestone|predecessor|successor|relationship|logic|constraint|lag|"
    r"calendar|resource|assignment|progress|percent\s+complete|earned\s+value|"
    r"spi|cpi|delay|late|overdue|risk|issue|evidence|field|dpr|report|qa|dcma|"
    r"lookahead|recovery|reschedule|p6|primavera|mpp|xer|cost|duration|crew|"
    r"chainage|quantity|data\s+date|status\s+date|uploaded|document|file|"
    r"dashboard|proposal|change\s+request)\b", re.IGNORECASE)
_PROJECT_IDENTIFIER = re.compile(
    r"\b[A-Z]{1,8}[-_][A-Z0-9_-]*\d[A-Z0-9_-]*\b|"
    r"\b\d{4}-\d{2}-\d{2}\b", re.IGNORECASE)
_DEEP_FOLLOW_UP = re.compile(
    r"^\s*(?:why|how|which\s+one|what\s+about\s+(?:that|it|those)|"
    r"explain(?:\s+that)?|tell\s+me\s+more|show\s+me|go\s+on|continue|"
    r"and\s+(?:that|it|the\s+rest)|can\s+you\s+check\s+(?:that|it))"
    r"[?.!\s]*$", re.IGNORECASE)
_CONTEXT_REFERENCE = re.compile(
    r"\b(?:it|that|this|those|them|they|there|same|previous|above)\b",
    re.IGNORECASE)


def instant_reply(message: str, project_name: str,
                  history: list[dict] | None = None) -> str | None:
    """Return a no-model conversational reply when it is fully determined."""
    text = str(message or "").strip()
    history = history or []
    if _GREETING.fullmatch(text):
        return "Hey! What would you like to work on in " + project_name + "?"
    if _THANKS.fullmatch(text):
        return "You're welcome! What would you like to look at next?"
    if _FAREWELL.fullmatch(text):
        return "See you! I'll keep the project context ready for next time."
    if _LAUGHTER.fullmatch(text):
        return "😂 Fair enough. What do you want to check next?"
    if _WELLBEING.fullmatch(text):
        return "Doing good—and ready when you are. What should we look at?"
    if _IDENTITY.fullmatch(text):
        return ("I'm VEDA, your construction project intelligence assistant. "
                "I can chat normally, and I switch to grounded schedule and "
                "evidence analysis when your question needs project facts.")
    if _PREVIOUS_USER.search(text):
        if history:
            previous = str(history[-1].get("title") or "")[:500]
            return 'Your previous message was: "' + previous + '".'
        return "There isn't an earlier Ask VEDA message in this project yet."
    if _PREVIOUS_ASSISTANT.search(text):
        if history:
            previous = str(history[-1].get("description") or "")[:1000]
            return 'My previous answer was: "' + previous + '".'
        return "I haven't answered an earlier message in this project yet."
    return None


def route_question(message: str, *, previous_mode: str | None = None,
                   force_deep: bool = False,
                   history: list[dict] | None = None,
                   project_name: str = "this project") -> QuestionRoute:
    """Choose the cheapest lane that cannot weaken project accuracy."""
    text = str(message or "").strip()
    if force_deep:
        return QuestionRoute("deep", "external project context requires grounding")
    if instant_reply(text, project_name, history) is not None:
        return QuestionRoute("instant", "deterministic conversational intent")
    if _PROJECT_TERMS.search(text) or _PROJECT_IDENTIFIER.search(text):
        return QuestionRoute("deep", "project or schedule facts requested")
    if previous_mode == "deep":
        word_count = len(re.findall(r"\b\w+\b", text))
        if (_DEEP_FOLLOW_UP.fullmatch(text) or
                (word_count <= 12 and _CONTEXT_REFERENCE.search(text))):
            return QuestionRoute("deep", "follow-up to grounded project reasoning")
    return QuestionRoute("fast", "general conversation without project facts")
