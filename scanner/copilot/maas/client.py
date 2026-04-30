"""
Generic async HTTP client for RunPod vLLM endpoints (OpenAI-compatible).

Features:
- Circuit breaker (3 failures → open, 60s recovery)
- Configurable retries and timeouts
- Hardened JSON extraction (strips code fences, extracts first {...} block)
"""

import httpx
import json
import re
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class RunPodUnavailableError(Exception):
    """Raised when a RunPod endpoint is unreachable or circuit is open."""
    pass


@dataclass
class CircuitBreakerState:
    """Simple circuit breaker for a single endpoint."""
    failures: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False
    FAILURE_THRESHOLD: int = 3
    RECOVERY_TIMEOUT: float = 60.0  # seconds

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.FAILURE_THRESHOLD:
            self.is_open = True

    def record_success(self):
        self.failures = 0
        self.is_open = False

    def can_attempt(self) -> bool:
        if not self.is_open:
            return True
        # Half-open: allow one attempt after recovery timeout
        if time.time() - self.last_failure_time > self.RECOVERY_TIMEOUT:
            self.is_open = False
            return True
        return False


# Regex to strip markdown code fences
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


def _extract_json(text: str) -> str:
    """
    Extract JSON from potentially wrapped vLLM output.

    Handles:
    1. Clean JSON (returns as-is)
    2. Markdown code fences: ```json {...} ```
    3. Preamble text before a JSON object: extracts first balanced {...}
    """
    stripped = text.strip()

    # Fast path: already valid JSON
    if stripped.startswith("{"):
        return stripped

    # Try stripping code fences
    match = _CODE_FENCE_RE.search(stripped)
    if match:
        inner = match.group(1).strip()
        if inner.startswith("{"):
            return inner

    # Extract first balanced {...} block
    start = stripped.find("{")
    if start == -1:
        return stripped  # No JSON found, return as-is for Pydantic to reject

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(stripped)):
        c = stripped[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return stripped[start:i + 1]

    # Unbalanced — return from start anyway, let Pydantic reject
    return stripped[start:]


def _is_gpt5_or_reasoning(model: str) -> bool:
    """True for OpenAI models that use max_completion_tokens / reasoning_effort."""
    m = (model or "").lower()
    return (
        m.startswith("gpt-5")
        or m.startswith("o1")
        or m.startswith("o3")
        or m.startswith("o4")
    )


class RunPodClient:
    """
    Async HTTP client for an OpenAI-compatible /v1/chat/completions endpoint.

    Originally written for self-hosted vLLM on RunPod, but works against
    api.openai.com, api.together.xyz, etc. unchanged. When `model_name` is
    a GPT-5 / o-series model, the payload is adjusted to use
    `max_completion_tokens` and optionally `reasoning_effort`.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str = "default",
        timeout: float = 90.0,
        max_retries: int = 1,
        reasoning_effort: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        # When set, applied to GPT-5 / o-series specialists. "minimal" or
        # "low" is right for narrow JSON-emitting tasks (SQL gen, log triage)
        # — they don't need much internal reasoning and the tokens add cost.
        self.reasoning_effort = reasoning_effort
        self._circuit = CircuitBreakerState()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers=headers,
            )
        return self._client

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: Optional[Dict[str, str]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Call the OpenAI-compatible chat completions endpoint.

        Returns dict with 'content' (JSON-extracted), 'usage', 'latency_ms'.
        Raises RunPodUnavailableError if circuit is open or retries exhausted.

        ``reasoning_effort`` (kwarg, optional): per-call override of the
        instance default. Used by the orchestrator to escalate effort on a
        retry without mutating the shared client. ``None`` falls back to
        ``self.reasoning_effort``.
        """
        if not self._circuit.can_attempt():
            raise RunPodUnavailableError(
                f"Circuit breaker open for {self.base_url}"
            )

        effective_effort = reasoning_effort or self.reasoning_effort

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
        }
        if _is_gpt5_or_reasoning(self.model_name):
            # GPT-5 / o-series: max_completion_tokens, optional reasoning
            # effort. Reasoning tokens count against the budget, so floor
            # the budget at 4096 to leave room for visible JSON output even
            # under "medium" effort. Some reasoning models reject custom
            # temperature; safer to omit it and let the model use its default.
            payload["max_completion_tokens"] = max(max_tokens, 4096)
            if effective_effort:
                payload["reasoning_effort"] = effective_effort
        else:
            payload["temperature"] = temperature
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                client = await self._get_client()
                start = time.monotonic()
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                )
                latency_ms = int((time.monotonic() - start) * 1000)

                if response.status_code == 200:
                    data = response.json()
                    self._circuit.record_success()
                    raw_content = data["choices"][0]["message"]["content"]
                    content = _extract_json(raw_content)
                    return {
                        "content": content,
                        "usage": data.get("usage", {}),
                        "finish_reason": data["choices"][0].get("finish_reason", "stop"),
                        "latency_ms": latency_ms,
                    }
                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                    logger.warning(
                        f"[RunPod] {self.base_url} returned {response.status_code} "
                        f"(attempt {attempt + 1})"
                    )

            except httpx.TimeoutException as e:
                last_error = f"Timeout: {e}"
                logger.warning(
                    f"[RunPod] Timeout calling {self.base_url} (attempt {attempt + 1})"
                )
            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
                logger.warning(
                    f"[RunPod] Connection error to {self.base_url} (attempt {attempt + 1})"
                )
            except Exception as e:
                last_error = str(e)
                logger.exception(f"[RunPod] Unexpected error (attempt {attempt + 1})")

        self._circuit.record_failure()
        raise RunPodUnavailableError(
            f"All retries exhausted for {self.base_url}: {last_error}"
        )

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @property
    def is_available(self) -> bool:
        """Check if this endpoint is reachable (circuit not open)."""
        return self._circuit.can_attempt()
