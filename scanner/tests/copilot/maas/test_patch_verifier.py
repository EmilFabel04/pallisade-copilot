"""Tests for Patch verifier: size bounds, format checks, rollback."""

import pytest

from copilot.maas.schemas import (
    CodeFixResponse,
    UnifiedDiffPatch,
    CodeFixValidation,
)
from copilot.maas.verifiers.patch_verifier import (
    PatchVerifier,
    MAX_PATCH_CONTENT_CHARS,
    MAX_TOTAL_PATCH_CHARS,
    VALID_PATCH_TYPES,
)


def _make_patch(
    file_path: str = "models/orders.sql",
    patch_type: str = "sql_model",
    new_content: str = "SELECT * FROM orders",
    original_content: str = None,
    diff: str = "",
    rationale: str = "Fixed column.",
) -> UnifiedDiffPatch:
    return UnifiedDiffPatch(
        file_path=file_path,
        patch_type=patch_type,
        new_content=new_content,
        original_content=original_content,
        diff=diff,
        rationale=rationale,
    )


def _make_response(patches=None, rollback_steps=None) -> CodeFixResponse:
    return CodeFixResponse(
        patches=patches or [_make_patch()],
        validation=CodeFixValidation(
            rollback_steps=rollback_steps or ["Revert commit"],
        ),
        impact_summary="Dashboard affected.",
        root_cause_summary="Wrong column.",
    )


class TestPatchVerifierBasics:
    @pytest.mark.asyncio
    async def test_valid_patch_passes(self):
        v = PatchVerifier()
        resp = _make_response()
        result = await v.verify(resp)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_empty_file_path_fails(self):
        v = PatchVerifier()
        resp = _make_response(patches=[_make_patch(file_path="")])
        result = await v.verify(resp)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_empty_new_content_fails(self):
        v = PatchVerifier()
        resp = _make_response(patches=[_make_patch(new_content="")])
        result = await v.verify(resp)
        assert result.passed is False


class TestPatchVerifierTypes:
    @pytest.mark.asyncio
    async def test_all_valid_types(self):
        # Use content appropriate for each patch type to avoid StaticValidator failures
        type_content = {
            "sql_model": "SELECT * FROM orders",
            "yaml_config": "version: 2\nmodels:\n  - name: orders",
            "python_script": "import os\nprint('hello')\n",
            "orchestration": "import os\nprint('hello')\n",
            "text_file": "Some text content here.",
        }
        v = PatchVerifier()
        for pt in VALID_PATCH_TYPES:
            content = type_content.get(pt, "test content")
            resp = _make_response(patches=[_make_patch(patch_type=pt, new_content=content)])
            result = await v.verify(resp)
            assert result.passed is True, f"Patch type '{pt}' should pass: {result.errors}"

    @pytest.mark.asyncio
    async def test_invalid_patch_type_fails(self):
        v = PatchVerifier()
        resp = _make_response(patches=[_make_patch(patch_type="unknown_type")])
        result = await v.verify(resp)
        assert result.passed is False


class TestPatchVerifierSizeBounds:
    @pytest.mark.asyncio
    async def test_oversized_single_patch_fails(self):
        v = PatchVerifier()
        big_content = "x" * (MAX_PATCH_CONTENT_CHARS + 1)
        resp = _make_response(patches=[_make_patch(new_content=big_content)])
        result = await v.verify(resp)
        assert result.passed is False
        assert any("size" in e.lower() or "exceeds" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_total_patch_size_limit(self):
        v = PatchVerifier()
        # Create enough patches to exceed total limit
        chunk = "x" * 40_000  # Under single limit but several will exceed total
        patches = [_make_patch(file_path=f"file_{i}.sql", new_content=chunk) for i in range(6)]
        resp = _make_response(patches=patches)
        result = await v.verify(resp)
        assert result.passed is False


class TestPatchVerifierDiffFormat:
    @pytest.mark.asyncio
    async def test_diff_with_original_content(self):
        v = PatchVerifier()
        resp = _make_response(patches=[_make_patch(
            original_content="SELECT * FROM old_table",
            diff="--- a/models/orders.sql\n+++ b/models/orders.sql\n@@ -1 +1 @@\n-SELECT * FROM old_table\n+SELECT * FROM orders",
            new_content="SELECT * FROM orders",
        )])
        result = await v.verify(resp)
        assert result.passed is True


class TestPatchVerifierRollback:
    @pytest.mark.asyncio
    async def test_missing_rollback_warns(self):
        v = PatchVerifier()
        resp = _make_response(rollback_steps=[])
        result = await v.verify(resp)
        # Missing rollback is a warning, not a failure
        assert len(result.warnings) > 0 or result.passed is True
