"""Heuristic parser for failure_review free-text replies.

Investigate-hints are checked first because phrases like "look into it" can
contain "into" which collides with looser expected-style words.
"""
from typing import Optional, Dict


_EXPECTED_HINTS = (
    "expected", "normal", "noise", "fine", "dampen", "ignore", "weekend",
    "holiday", "scheduled", "maintenance",
)
_INVESTIGATE_HINTS = (
    "investigate", "look into", "look at", "check this", "weird",
    "broken", "real", "alert", "incident",
)


def parse_reply(reply: str) -> Optional[Dict[str, str]]:
    text = reply.lower()
    if any(h in text for h in _INVESTIGATE_HINTS):
        return {"disposition": "investigate"}
    if any(h in text for h in _EXPECTED_HINTS):
        return {"disposition": "expected"}
    return None
