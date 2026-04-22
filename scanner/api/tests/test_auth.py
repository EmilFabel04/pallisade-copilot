"""Tests for scanner.api.auth middlewares and dependency."""

import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_with_auth(shared_secret: str = "a" * 64):
    """Build a minimal FastAPI app with InternalAuthMiddleware registered."""
    env = {
        "ENVIRONMENT": "development",
        "SCANNER_SHARED_SECRET": shared_secret,
    }
    with patch.dict("os.environ", env):
        # Import inside the patched env so Settings sees the right values.
        from scanner.api.dependencies import Settings
        from scanner.api.auth import InternalAuthMiddleware

        app = FastAPI()
        app.add_middleware(InternalAuthMiddleware, settings=Settings())

        @app.get("/api/v1/ping")
        async def ping():
            return {"ok": True}

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        return TestClient(app)


class TestInternalAuthMiddleware:
    SECRET = "a" * 64

    def test_missing_header_returns_401(self):
        client = _app_with_auth(self.SECRET)
        r = client.get("/api/v1/ping")
        assert r.status_code == 401
        assert r.json() == {"error": "unauthorized"}

    def test_wrong_header_returns_401(self):
        client = _app_with_auth(self.SECRET)
        r = client.get("/api/v1/ping", headers={"X-Internal-Auth": "b" * 64})
        assert r.status_code == 401

    def test_correct_header_passes(self):
        client = _app_with_auth(self.SECRET)
        r = client.get("/api/v1/ping", headers={"X-Internal-Auth": self.SECRET})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_health_endpoint_exempt(self):
        """Health checks don't need the secret (for k8s/load-balancer probes)."""
        client = _app_with_auth(self.SECRET)
        r = client.get("/health")
        assert r.status_code == 200


def _app_with_full_stack(shared_secret: str = "a" * 64):
    env = {"ENVIRONMENT": "development", "SCANNER_SHARED_SECRET": shared_secret}
    with patch.dict("os.environ", env):
        from fastapi import Depends
        from scanner.api.dependencies import Settings
        from scanner.api.auth import (
            InternalAuthMiddleware,
            ActingPrincipalMiddleware,
            ActingPrincipal,
            require_principal,
        )

        app = FastAPI()
        settings = Settings()
        app.add_middleware(ActingPrincipalMiddleware)
        app.add_middleware(InternalAuthMiddleware, settings=settings)

        @app.get("/api/v1/whoami")
        async def whoami(principal: ActingPrincipal = Depends(require_principal)):
            return {
                "user_id": principal.user_id,
                "org_id": principal.organization_id,
                "request_id": principal.request_id,
            }

        return TestClient(app)


class TestActingPrincipalMiddleware:
    SECRET = "a" * 64

    def _headers(self, **overrides):
        base = {
            "X-Internal-Auth": self.SECRET,
            "X-Acting-User": "user_123",
            "X-Acting-Org": "org_456",
            "X-Request-Id": "req_789",
        }
        base.update(overrides)
        return base

    def test_all_headers_present_populates_principal(self):
        client = _app_with_full_stack(self.SECRET)
        r = client.get("/api/v1/whoami", headers=self._headers())
        assert r.status_code == 200
        assert r.json() == {"user_id": "user_123", "org_id": "org_456", "request_id": "req_789"}

    def test_missing_acting_user_returns_400(self):
        client = _app_with_full_stack(self.SECRET)
        headers = self._headers()
        del headers["X-Acting-User"]
        r = client.get("/api/v1/whoami", headers=headers)
        assert r.status_code == 400
        assert r.json() == {"error": "missing_principal"}

    def test_missing_acting_org_returns_400(self):
        client = _app_with_full_stack(self.SECRET)
        headers = self._headers()
        del headers["X-Acting-Org"]
        r = client.get("/api/v1/whoami", headers=headers)
        assert r.status_code == 400

    def test_missing_request_id_generates_one(self):
        client = _app_with_full_stack(self.SECRET)
        headers = self._headers()
        del headers["X-Request-Id"]
        r = client.get("/api/v1/whoami", headers=headers)
        assert r.status_code == 200
        assert r.json()["request_id"]  # server-generated
