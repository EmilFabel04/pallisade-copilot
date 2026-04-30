"""Tiny in-process pub/sub for clarification lifecycle events.

Used so guessers (sla_discovery, monitor evaluation) can react to
context_resolved without import cycles.
"""
from collections import defaultdict
from typing import Any, Callable, Dict, List


class EventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        self._subs[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        if handler in self._subs[event]:
            self._subs[event].remove(handler)

    def emit(self, event: str, payload: Any) -> None:
        for h in list(self._subs[event]):
            h(payload)


BUS = EventBus()
