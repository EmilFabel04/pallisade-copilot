"""
Copilot Intent Classification

Multi-intent classifier with scoring for routing user messages
to the correct copilot behavior. Replaces single-match regex mode
detection with weighted scoring across keywords, question form,
conversation history, and target extraction.
"""

import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple


class Intent(Enum):
    INFO = "info"
    DEBUG = "debug"
    FIX = "fix"
    PR = "pr"
    PLAN = "plan"
    EXPLAIN = "explain"


@dataclass
class ScoredIntent:
    intent: Intent
    score: float  # 0.0 - 1.0
    evidence: List[str] = field(default_factory=list)


@dataclass
class IntentResult:
    primary: ScoredIntent
    secondary: Optional[ScoredIntent] = None
    target_hint: Optional[str] = None  # e.g., "airflow", "dbt", "fivetran"
    target_entities: List[str] = field(default_factory=list)
    raw_scores: Dict[Intent, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Keyword signals (weight: 0.4)
# Each entry: (pattern, sub-weight) — higher sub-weight = stronger signal
# ---------------------------------------------------------------------------

_KEYWORD_SIGNALS: Dict[Intent, List[Tuple[str, float]]] = {
    Intent.INFO: [
        (r"\bhow many\b", 0.9),
        (r"\bshow me\b", 0.7),
        (r"\blist\b", 0.6),
        (r"\bcount\b", 0.7),
        (r"\bwhat is\b", 0.5),
        (r"\bwhat are\b", 0.5),
        (r"\bwhich\b", 0.4),
        (r"\btop \d+", 0.7),
        (r"\bmost\b", 0.5),
        (r"\blargest\b", 0.5),
        (r"\bsmallest\b", 0.5),
        (r"\baverage\b", 0.6),
        (r"\btotal\b", 0.6),
        (r"\bsum\b", 0.5),
        (r"\bdo i have\b", 0.6),
        (r"\bare there\b", 0.5),
        (r"\bquery\b", 0.4),
        (r"\bselect\b", 0.3),
        (r"\blookup\b", 0.5),
        (r"\bfind\b", 0.4),
    ],
    Intent.DEBUG: [
        (r"\bfail(?:ed|ing|ure|s)?\b", 0.8),
        (r"\berror\b", 0.8),
        (r"\bbroken\b", 0.9),
        (r"\bnot working\b", 0.9),
        (r"\bwhy did\b", 0.8),
        (r"\bwhat went wrong\b", 0.9),
        (r"\binvestigat", 0.8),
        (r"\broot cause\b", 0.9),
        (r"\bdebug\b", 0.9),
        (r"\banomaly\b", 0.7),
        (r"\banomali", 0.7),
        (r"\boutlier", 0.6),
        (r"\bunusual\b", 0.6),
        (r"\bspike\b", 0.7),
        (r"\bdrop(?:ped)?\b", 0.6),
        (r"\bunexpected\b", 0.7),
        (r"\bdeviation\b", 0.6),
        (r"\babnormal\b", 0.6),
        (r"\bwrong\b", 0.6),
        (r"\bstale\b", 0.7),
        (r"\bmissing\b", 0.5),
        (r"\bincorrect\b", 0.6),
        (r"\bdiscrepanc", 0.7),
    ],
    Intent.FIX: [
        (r"\bfix\b", 0.8),
        (r"\brepair\b", 0.8),
        (r"\bcorrect\b", 0.5),
        (r"\bpatch\b", 0.8),
        (r"\bresolve\b", 0.6),
        (r"\bapply.{0,10}fix\b", 0.9),
        (r"\bgenerate.{0,10}fix\b", 0.9),
        (r"\bcreate.{0,10}fix\b", 0.9),
    ],
    Intent.PR: [
        (r"\bcreate.{0,10}pr\b", 0.95),
        (r"\bopen.{0,10}pr\b", 0.95),
        (r"\bpull request\b", 0.95),
        (r"\bopen.{0,10}pull request\b", 0.95),
        (r"\bpush.{0,10}change", 0.7),
        (r"\bgo ahead\b", 0.7),
        (r"\bdo it\b", 0.7),
        (r"\bproceed\b", 0.7),
        (r"\bapply\b", 0.5),
        (r"\bsubmit\b", 0.5),
    ],
    Intent.PLAN: [
        (r"\bmigrat", 0.8),
        (r"\brefactor\b", 0.8),
        (r"\bstrategy\b", 0.7),
        (r"\bredesign\b", 0.8),
        (r"\bhow should i\b", 0.7),
        (r"\bplan for\b", 0.8),
        (r"\bbest approach\b", 0.7),
        (r"\barchitect", 0.6),
        (r"\bimplement", 0.4),
    ],
    Intent.EXPLAIN: [
        (r"\bexplain\b", 0.8),
        (r"\bteach me\b", 0.9),
        (r"\bhow does .+ work\b", 0.8),
        (r"\bwalk me through\b", 0.8),
        (r"\bhelp me understand\b", 0.9),
        (r"\bwhat does .+ mean\b", 0.7),
        (r"\bwhat is the difference\b", 0.7),
        (r"\btell me about\b", 0.5),
    ],
}

# ---------------------------------------------------------------------------
# Question form signals (weight: 0.2)
# Full-message regex patterns that strongly indicate an intent
# ---------------------------------------------------------------------------

_QUESTION_FORM_SIGNALS: List[Tuple[str, Intent, float]] = [
    # DEBUG forms
    (r"^why\s+(did|does|is|are|was|were)\b", Intent.DEBUG, 0.85),
    (r"^what\s+(went wrong|happened|caused|is wrong)\b", Intent.DEBUG, 0.9),
    (r"^is\s+.+\s+(broken|failing|down)\b", Intent.DEBUG, 0.8),
    # INFO forms
    (r"^how\s+many\b", Intent.INFO, 0.9),
    (r"^what\s+is\s+the\s+(count|total|sum|average|number)\b", Intent.INFO, 0.85),
    (r"^show\s+me\b", Intent.INFO, 0.7),
    (r"^list\s+(all|the|my)\b", Intent.INFO, 0.8),
    (r"^do\s+i\s+have\b", Intent.INFO, 0.7),
    # FIX forms
    (r"^fix\s+(the|this|my)\b", Intent.FIX, 0.9),
    (r"^(can you |please )?(fix|repair|correct|patch)\b", Intent.FIX, 0.85),
    # PR forms
    (r"^(can you |please )?(create|open)\s+a?\s*(pr|pull request)\b", Intent.PR, 0.95),
    # PLAN forms
    (r"^how\s+should\s+i\b", Intent.PLAN, 0.8),
    (r"^(can you |please )?(plan|design|architect)\b", Intent.PLAN, 0.8),
    # EXPLAIN forms
    (r"^(can you |please )?explain\b", Intent.EXPLAIN, 0.85),
    (r"^how\s+does\b", Intent.EXPLAIN, 0.7),
    (r"^what\s+is\s+a?\s*\w+\s*\?", Intent.EXPLAIN, 0.5),
]

# ---------------------------------------------------------------------------
# History signals (weight: 0.2)
# ---------------------------------------------------------------------------

_CONTINUATION_KEYWORDS: Dict[Intent, List[Tuple[str, float]]] = {
    Intent.PR: [
        (r"\bgo ahead\b", 0.9),
        (r"\bdo it\b", 0.9),
        (r"\bproceed\b", 0.85),
        (r"\byes\b", 0.5),
        (r"\bapply\b", 0.7),
        (r"\bship it\b", 0.9),
        (r"\bmerge\b", 0.7),
    ],
    Intent.FIX: [
        (r"\bfix it\b", 0.9),
        (r"\bfix that\b", 0.85),
        (r"\bmake it work\b", 0.8),
        (r"\bresolve it\b", 0.8),
    ],
}

# ---------------------------------------------------------------------------
# Target extraction
# ---------------------------------------------------------------------------

_INTEGRATION_NAMES = {
    "airflow": "airflow",
    "dag": "airflow",
    "dbt": "dbt",
    "fivetran": "fivetran",
    "airbyte": "airbyte",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "big query": "bigquery",
    "postgres": "postgres",
    "postgresql": "postgres",
    "redshift": "redshift",
    "databricks": "databricks",
    "looker": "looker",
    "tableau": "tableau",
    "power bi": "powerbi",
    "powerbi": "powerbi",
    "monte carlo": "monte_carlo",
    "elementary": "elementary",
    "soda": "soda",
    "github": "github",
    "dagster": "dagster",
    "prefect": "prefect",
    "n8n": "n8n",
}

_ENTITY_PATTERNS = [
    # project.dataset.table
    re.compile(r"\b([a-zA-Z_][\w-]*\.[a-zA-Z_][\w-]*\.[a-zA-Z_][\w-]*)\b"),
    # dataset.table
    re.compile(r"\b([a-zA-Z_][\w-]*\.[a-zA-Z_][\w-]+)\b"),
    # backtick-quoted identifiers
    re.compile(r"`([^`]+)`"),
    # "the X table/model/dag"
    re.compile(r"\bthe\s+(\w+)\s+(?:table|model|dag|view|source|dashboard)\b"),
    # "my X table/model/dag"
    re.compile(r"\bmy\s+(\w+)\s+(?:table|model|dag|view|source|dashboard)\b"),
]

# Common words that match entity patterns but aren't entities
_ENTITY_STOP_WORDS = {
    "the", "this", "that", "my", "our", "your", "a", "an", "some",
    "all", "any", "each", "every", "first", "last", "new", "old",
    "same", "other", "main", "data", "from", "with", "into",
}


def _extract_target_hint(message_lower: str) -> Optional[str]:
    """Extract the most likely integration target from the message."""
    for keyword, integration in _INTEGRATION_NAMES.items():
        if keyword in message_lower:
            return integration
    return None


def _extract_target_entities(message: str) -> List[str]:
    """Extract mentioned table/model/entity names."""
    entities = []
    seen = set()
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.finditer(message):
            entity = match.group(1).strip()
            if (
                entity.lower() not in _ENTITY_STOP_WORDS
                and entity.lower() not in seen
                and len(entity) > 1
            ):
                seen.add(entity.lower())
                entities.append(entity)
    return entities


def _score_keywords(message_lower: str) -> Dict[Intent, Tuple[float, List[str]]]:
    """Score each intent based on keyword matches. Returns (score, evidence) per intent."""
    scores: Dict[Intent, Tuple[float, List[str]]] = {}
    for intent, signals in _KEYWORD_SIGNALS.items():
        max_score = 0.0
        evidence = []
        for pattern, weight in signals:
            if re.search(pattern, message_lower):
                if weight > max_score:
                    max_score = weight
                evidence.append(pattern)
        scores[intent] = (max_score, evidence)
    return scores


def _score_question_form(message_lower: str) -> Dict[Intent, Tuple[float, List[str]]]:
    """Score each intent based on sentence structure."""
    scores: Dict[Intent, Tuple[float, List[str]]] = {}
    for pattern, intent, weight in _QUESTION_FORM_SIGNALS:
        if re.search(pattern, message_lower):
            current = scores.get(intent, (0.0, []))
            if weight > current[0]:
                scores[intent] = (weight, current[1] + [f"form:{pattern}"])
    return scores


def _score_history(
    message_lower: str, history: Optional[List[Dict]]
) -> Dict[Intent, Tuple[float, List[str]]]:
    """Score intents based on conversation history context."""
    scores: Dict[Intent, Tuple[float, List[str]]] = {}
    if not history:
        return scores

    # Check if prior conversation was debug/diagnostic
    prior_was_debug = False
    for msg in reversed(history[-6:]):  # Look at last 6 messages
        content_lower = (msg.get("content") or "").lower()
        if msg.get("role") == "user":
            for pattern, _ in _KEYWORD_SIGNALS.get(Intent.DEBUG, []):
                if re.search(pattern, content_lower):
                    prior_was_debug = True
                    break
        if prior_was_debug:
            break

    if prior_was_debug:
        # Check if current message is a continuation / action request
        for intent, keywords in _CONTINUATION_KEYWORDS.items():
            for pattern, weight in keywords:
                if re.search(pattern, message_lower):
                    current = scores.get(intent, (0.0, []))
                    if weight > current[0]:
                        scores[intent] = (weight, current[1] + [f"history:{pattern}"])
    return scores


def classify_intent(
    message: str, history: Optional[List[Dict]] = None
) -> IntentResult:
    """
    Classify user message into one or more intents with confidence scores.

    Args:
        message: The user's current message.
        history: Optional conversation history as list of {"role": ..., "content": ...}.

    Returns:
        IntentResult with primary intent, optional secondary, target hints.
    """
    message_lower = message.lower().strip()

    # --- Gather scores from all signal sources ---
    keyword_scores = _score_keywords(message_lower)
    form_scores = _score_question_form(message_lower)
    history_scores = _score_history(message_lower, history)

    # --- Weighted combination ---
    W_KEYWORD = 0.4
    W_FORM = 0.2
    W_HISTORY = 0.2
    # Remaining 0.2 is for explicit commands (handled upstream via slash commands)

    combined: Dict[Intent, float] = {}
    all_evidence: Dict[Intent, List[str]] = {}

    for intent in Intent:
        kw_score, kw_ev = keyword_scores.get(intent, (0.0, []))
        form_score, form_ev = form_scores.get(intent, (0.0, []))
        hist_score, hist_ev = history_scores.get(intent, (0.0, []))

        total = (kw_score * W_KEYWORD) + (form_score * W_FORM) + (hist_score * W_HISTORY)
        combined[intent] = total
        all_evidence[intent] = kw_ev + form_ev + hist_ev

    # --- Sort by score ---
    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)

    # --- Build result ---
    primary_intent, primary_score = ranked[0]
    primary = ScoredIntent(
        intent=primary_intent,
        score=min(primary_score, 1.0),
        evidence=all_evidence[primary_intent],
    )

    # Multi-intent: if second score is also significant
    secondary = None
    if len(ranked) > 1:
        sec_intent, sec_score = ranked[1]
        if sec_score > 0.3 and (primary_score - sec_score) < 0.3:
            secondary = ScoredIntent(
                intent=sec_intent,
                score=min(sec_score, 1.0),
                evidence=all_evidence[sec_intent],
            )

    # --- Fallback: if nothing scored above threshold, default to INFO ---
    if primary.score < 0.1:
        primary = ScoredIntent(intent=Intent.INFO, score=0.3, evidence=["fallback"])

    # --- Extract targets ---
    target_hint = _extract_target_hint(message_lower)
    target_entities = _extract_target_entities(message)

    return IntentResult(
        primary=primary,
        secondary=secondary,
        target_hint=target_hint,
        target_entities=target_entities,
        raw_scores=combined,
    )


def intent_to_mode(result: IntentResult) -> str:
    """
    Map IntentResult to existing InteractionMode string value.

    Returns the mode string (e.g., "ask", "debug", "fix") for use
    with the existing modes.py system.
    """
    MAPPING = {
        Intent.INFO: "ask",
        Intent.DEBUG: "debug",
        Intent.FIX: "fix",
        Intent.PR: "fix",  # PR uses FIX mode's tools
        Intent.PLAN: "plan",
        Intent.EXPLAIN: "explain",
    }

    # Multi-intent: DEBUG+PR or DEBUG+FIX → use FIX mode
    if result.secondary and result.secondary.intent in (Intent.PR, Intent.FIX):
        return "fix"

    return MAPPING.get(result.primary.intent, "ask")
