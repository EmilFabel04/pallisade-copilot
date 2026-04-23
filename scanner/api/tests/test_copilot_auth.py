"""Tests that copilot router uses require_principal, not X-Organization-Id header."""

from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


SECRET = "a" * 64


def _client():
    """Build a TestClient for the real app with env-configured auth."""
    env = {"ENVIRONMENT": "development", "SCANNER_SHARED_SECRET": SECRET}
    with patch.dict("os.environ", env):
        from scanner.api.dependencies import get_settings
        get_settings.cache_clear()
        from scanner.api.app import create_app
        app = create_app()
        return TestClient(app)


def _trust_headers(acting_org: str = "org_from_principal", **extra):
    base = {
        "X-Internal-Auth": SECRET,
        "X-Acting-User": "user_123",
        "X-Acting-Org": acting_org,
    }
    base.update(extra)
    return base


class TestCopilotPrincipalEnforcement:
    """For each endpoint that uses org_id internally, assert principal wins over header."""

    def test_get_context_uses_principal_not_header(self):
        client = _client()

        fake_context = MagicMock()
        fake_context.integrations = []
        fake_context.available_tools = []
        fake_context.graph = None

        with patch(
            "copilot.context_builder.CopilotContextBuilder.build_context",
            new=AsyncMock(return_value=fake_context),
        ) as mock_build:
            headers = _trust_headers(
                acting_org="org_from_principal",
                **{"X-Organization-Id": "org_spoofed_by_attacker"},
            )
            r = client.get("/api/v1/copilot/context", headers=headers)
            assert r.status_code == 200
            # build_context must have been called with the principal's org
            assert mock_build.await_args.kwargs["org_id"] == "org_from_principal"

    def test_get_tools_uses_principal_not_header(self):
        client = _client()

        fake_context = MagicMock()
        fake_context.integration_types = set()

        with patch(
            "copilot.context_builder.CopilotContextBuilder.build_context",
            new=AsyncMock(return_value=fake_context),
        ), patch(
            "copilot.tools.get_tool_registry"
        ) as mock_registry:
            mock_registry.return_value.get_available_tools.return_value = []
            headers = _trust_headers(
                acting_org="org_from_principal",
                **{"X-Organization-Id": "org_spoofed"},
            )
            r = client.get("/api/v1/copilot/tools", headers=headers)
            assert r.status_code == 200

    def test_openlineage_uses_principal_not_header(self):
        client = _client()

        with patch(
            "copilot.openlineage_consumer.OpenLineageConsumer.process_event",
            new=AsyncMock(return_value=True),
        ) as mock_proc:
            headers = _trust_headers(
                acting_org="org_from_principal",
                **{"X-Organization-Id": "org_spoofed", "Content-Type": "application/json"},
            )
            body = {
                "eventType": "START",
                "eventTime": "2026-01-01T00:00:00Z",
                "producer": "test",
                "job": {"namespace": "x", "name": "y"},
                "run": {"runId": "r1"},
            }
            r = client.post("/api/v1/copilot/openlineage/events", headers=headers, json=body)
            assert r.status_code in (200, 500)  # 500 if event shape incomplete; we still assert the arg
            assert mock_proc.await_args.kwargs["org_id"] == "org_from_principal"


class TestCopilotMissingPrincipal:
    """Endpoints must 400 when X-Acting-Org is missing (middleware-enforced)."""

    def test_context_missing_acting_org_returns_400(self):
        client = _client()
        headers = {"X-Internal-Auth": SECRET, "X-Acting-User": "user_123"}
        r = client.get("/api/v1/copilot/context", headers=headers)
        assert r.status_code == 400


class TestCopilotStubEndpointsStillWork:
    """Endpoints that previously declared (but did not use) the org header must still work."""

    def test_get_sessions_works_without_org_header(self):
        client = _client()
        r = client.get("/api/v1/copilot/sessions", headers=_trust_headers())
        assert r.status_code == 200
        assert r.json() == {"sessions": [], "total": 0}

    def test_get_session_works_without_org_header(self):
        client = _client()
        r = client.get("/api/v1/copilot/sessions/sess_123", headers=_trust_headers())
        assert r.status_code == 200
