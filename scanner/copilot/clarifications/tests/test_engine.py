import pytest
from copilot.clarifications.registry import (
    KindHandler,
    register_kind,
    get_kind_handler,
    KIND_REGISTRY,
)


def _make_handler(name: str) -> KindHandler:
    return KindHandler(
        kind=name,
        validate_payload=lambda p: None,
        validate_answer=lambda a: None,
        load_prompt=lambda payload: f"prompt for {name}",
        on_resolve=lambda req, ans, db: None,
    )


def test_register_and_lookup_kind():
    KIND_REGISTRY.clear()
    h = _make_handler("test_kind")
    register_kind(h)
    assert get_kind_handler("test_kind") is h


def test_get_unknown_kind_raises():
    KIND_REGISTRY.clear()
    with pytest.raises(KeyError):
        get_kind_handler("does_not_exist")


def test_register_duplicate_raises():
    KIND_REGISTRY.clear()
    register_kind(_make_handler("dup"))
    with pytest.raises(ValueError):
        register_kind(_make_handler("dup"))
