"""Parse a free-text reply into {"column": "<name>"}.

The LLM should already produce structured output via the
record_clarification_answer tool, but this parser is the fallback when
the LLM emits prose only — it scans for a candidate name in the reply.
"""
from typing import List, Optional, Dict


def parse_reply(reply: str, candidates: List[str]) -> Optional[Dict[str, str]]:
    text = reply.lower()
    for cand in sorted(candidates, key=len, reverse=True):
        if cand.lower() in text:
            return {"column": cand}
    return None
