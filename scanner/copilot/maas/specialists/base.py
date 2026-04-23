"""
Abstract base for MAAS specialists.

Each specialist:
1. Builds a system prompt with the expected JSON schema
2. Calls the RunPod vLLM endpoint via RunPodClient
3. Parses the response into a Pydantic model
4. Returns the parsed model or raises SpecialistError
"""

from abc import ABC, abstractmethod
from typing import Any, TypeVar, Type
import logging

from pydantic import BaseModel, ValidationError

from ..client import RunPodClient, RunPodUnavailableError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class SpecialistError(Exception):
    """Raised when a specialist call fails after retries."""
    pass


class BaseSpecialist(ABC):
    """Abstract base for MAAS specialists."""

    def __init__(self, client: RunPodClient):
        self.client = client

    @property
    @abstractmethod
    def name(self) -> str:
        """Specialist name for logging and observability."""
        ...

    @abstractmethod
    def build_messages(self, evidence: str, query: str, **kwargs) -> list:
        """Build the messages list for the specialist call."""
        ...

    @property
    @abstractmethod
    def response_model(self) -> Type[BaseModel]:
        """The Pydantic model class to parse the response into."""
        ...

    async def call(
        self,
        evidence: str,
        query: str,
        max_retries: int = 1,
        **kwargs,
    ) -> BaseModel:
        """
        Call the specialist with evidence and parse the JSON response.

        On parse failure: retry once with a correction prompt.
        On HTTP failure: raise SpecialistError (orchestrator handles fallback).
        """
        messages = self.build_messages(evidence, query, **kwargs)
        content = ""

        for attempt in range(max_retries + 1):
            try:
                result = await self.client.chat_completion(
                    messages=messages,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                content = result["content"]
                parsed = self.response_model.model_validate_json(content)
                logger.info(
                    f"[MAAS/{self.name}] Success "
                    f"(attempt {attempt + 1}, {result['latency_ms']}ms)"
                )
                return parsed

            except ValidationError as e:
                logger.warning(
                    f"[MAAS/{self.name}] JSON parse error "
                    f"(attempt {attempt + 1}): {e}"
                )
                if attempt < max_retries:
                    # Retry with correction prompt
                    messages.append({
                        "role": "assistant",
                        "content": content,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Your response had validation errors:\n{e}\n\n"
                            f"Return a single JSON object matching this schema. "
                            f"No markdown, no code fences, no extra keys.\n"
                            f"{self.response_model.model_json_schema()}"
                        ),
                    })
                else:
                    raise SpecialistError(
                        f"{self.name} returned invalid JSON after "
                        f"{max_retries + 1} attempts: {e}"
                    )

            except RunPodUnavailableError as e:
                raise SpecialistError(f"{self.name} unavailable: {e}")

            except SpecialistError:
                raise

            except Exception as e:
                logger.exception(f"[MAAS/{self.name}] Unexpected error")
                raise SpecialistError(f"{self.name} error: {e}")
