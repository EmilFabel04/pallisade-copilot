"""Path-traversal hardening tests for dbt Core config resolution."""
import json
from pathlib import Path

import pytest

from scanner.api.routers.dbt import _resolve_dbt_core_paths


@pytest.fixture
def allowed_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a dbt project under a tmp allow-listed root with a valid manifest."""
    root = tmp_path / "projects"
    project = root / "warehouse-analytics"
    (project / "target").mkdir(parents=True)
    (project / "target" / "manifest.json").write_text(json.dumps({"nodes": {}, "sources": {}}))
    monkeypatch.setenv("DBT_ALLOWED_PROJECT_ROOTS", str(root))
    return project


def test_rejects_when_allowlist_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DBT_ALLOWED_PROJECT_ROOTS", raising=False)
    manifest, err = _resolve_dbt_core_paths({"project_path": str(tmp_path)})
    assert manifest is None
    assert err is not None
    assert "not enabled" in err.lower()


def test_rejects_path_outside_allowlist(
    allowed_project: Path, tmp_path: Path
) -> None:
    # An attacker-supplied path that sits *next to* the allow-listed root,
    # not under it.
    evil = tmp_path / "not-allowed"
    evil.mkdir()
    manifest, err = _resolve_dbt_core_paths({"project_path": str(evil)})
    assert manifest is None
    assert err is not None


def test_rejects_dotdot_traversal(
    allowed_project: Path, tmp_path: Path
) -> None:
    # Try to escape via ../
    traversal = f"{allowed_project}/../../etc"
    manifest, err = _resolve_dbt_core_paths({"project_path": traversal})
    assert manifest is None
    assert err is not None


def test_rejects_symlink_to_outside(
    allowed_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Replace the valid manifest with a symlink pointing outside the allow-list.
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({"nodes": {}}))
    manifest_file = allowed_project / "target" / "manifest.json"
    manifest_file.unlink()
    manifest_file.symlink_to(outside)

    manifest, err = _resolve_dbt_core_paths({"project_path": str(allowed_project)})
    assert manifest is None
    assert err is not None


def test_accepts_valid_project(allowed_project: Path) -> None:
    manifest, err = _resolve_dbt_core_paths({"project_path": str(allowed_project)})
    assert err is None
    assert manifest is not None
    assert manifest.name == "manifest.json"
    assert manifest.is_file()


def test_rejects_missing_project_path(allowed_project: Path) -> None:
    manifest, err = _resolve_dbt_core_paths({})
    assert manifest is None
    assert err is not None
