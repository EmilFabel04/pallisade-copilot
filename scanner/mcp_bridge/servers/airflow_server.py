"""
Wrapper entry point for the Airflow MCP server (astro_airflow_mcp).

Patches TokenManager._fetch_token to handle Airflow 2.x basic_auth
backend correctly before delegating to the upstream main().

Problem: The upstream v0.4.1 POSTs to /auth/token with credentials as
JSON body (no Authorization header). On Airflow 2.x with the basic_auth
backend, the auth middleware rejects the unauthenticated request with 401
(not 404). The original code only handles 404 and only catches
httpx.RequestError — the resulting HTTPStatusError propagates uncaught,
preventing the basic auth fallback from executing.

Fix: Treat ANY 4xx from /auth/token as "endpoint unavailable" and fall
back to basic auth. Catch both RequestError and HTTPStatusError.

Run as:  python -m mcp_bridge.servers.airflow_server
"""

import logging
import time

import httpx

from astro_airflow_mcp.auth import TokenManager

logger = logging.getLogger(__name__)


def _patched_fetch_token(self: TokenManager) -> None:
    """Replacement for TokenManager._fetch_token with 4xx fallback."""
    token_url = f"{self.airflow_url}/auth/token"

    try:
        with httpx.Client(timeout=self._timeout) as client:
            if self.username and self.password:
                logger.debug("Fetching token with username/password credentials")
                response = client.post(
                    token_url,
                    json={"username": self.username, "password": self.password},
                    headers={"Content-Type": "application/json"},
                )
            else:
                logger.debug("Attempting credential-less token fetch")
                response = client.get(token_url)

        # Any 4xx means the token endpoint is not usable — fall back to
        # basic auth. Covers 404 (AF2 no endpoint), 401 (AF2 basic_auth
        # middleware), and 403 (permission denied).
        if 400 <= response.status_code < 500:
            self._token_endpoint_available = False
            self._token = None
            if not self.username and not self.password:
                logger.info(
                    "Token endpoint returned %d (likely Airflow 2.x). "
                    "Defaulting to admin:admin for basic auth.",
                    response.status_code,
                )
                self.username = "admin"  # nosec B105
                self.password = "admin"  # nosec B105
            else:
                logger.info(
                    "Token endpoint returned %d (likely Airflow 2.x). "
                    "Using provided credentials for basic auth.",
                    response.status_code,
                )
            return

        response.raise_for_status()
        data = response.json()

        if "access_token" in data:
            self._token = data["access_token"]
            self._token_fetched_at = time.time()
            self._token_endpoint_available = True
            if "expires_in" in data:
                self._token_lifetime_seconds = float(data["expires_in"])
            logger.info("Successfully fetched Airflow API token")
        else:
            logger.warning("Unexpected token response format: %s", data)
            self._token = None

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning("Failed to fetch token from %s: %s", token_url, e)
        self._token_endpoint_available = False
        self._token = None


def main():
    """Apply auth patch and delegate to upstream entry point."""
    TokenManager._fetch_token = _patched_fetch_token
    logger.info("[Pallisade] Applied Airflow auth patch (4xx fallback to basic auth)")

    from astro_airflow_mcp.__main__ import main as upstream_main
    upstream_main()


if __name__ == "__main__":
    main()
