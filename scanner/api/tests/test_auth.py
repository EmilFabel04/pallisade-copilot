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
