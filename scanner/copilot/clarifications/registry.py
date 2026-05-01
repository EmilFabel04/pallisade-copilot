"""Per-kind handler registry.

Each kind plugs in a handler with: payload validator, answer validator,
prompt loader, and on_resolve hook (which writes conventions/overrides).
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass
class KindHandler:
    kind: str
    validate_payload: Callable[[Dict[str, Any]], None]
    validate_answer: Callable[[Dict[str, Any]], None]
    load_prompt: Callable[[Dict[str, Any]], str]
    on_resolve: Callable[[Any, Dict[str, Any], Any], None]


KIND_REGISTRY: Dict[str, KindHandler] = {}


def register_kind(handler: KindHandler) -> None:
    if handler.kind in KIND_REGISTRY:
        raise ValueError(f"Kind {handler.kind!r} already registered")
    KIND_REGISTRY[handler.kind] = handler


def get_kind_handler(kind: str) -> KindHandler:
    if kind not in KIND_REGISTRY:
        raise KeyError(f"Unknown clarification kind: {kind!r}")
    return KIND_REGISTRY[kind]
