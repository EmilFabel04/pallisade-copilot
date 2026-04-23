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


class RunPodClient:
    """
    Async HTTP client for RunPod vLLM endpoints.

    Uses OpenAI-compatible /v1/chat/completions API.
    Each specialist gets its own RunPodClient instance with separate
    base_url, api_key, and circuit breaker state.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str = "default",
        timeout: float = 90.0,
        max_retries: int = 1,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries
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
        max_tokens: int = 512,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Call the OpenAI-compatible chat completions endpoint.

        Returns dict with 'content' (JSON-extracted), 'usage', 'latency_ms'.
        Raises RunPodUnavailableError if circuit is open or retries exhausted.
        """
        if not self._circuit.can_attempt():
            raise RunPodUnavailableError(
                f"Circuit breaker open for {self.base_url}"
            )

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
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
