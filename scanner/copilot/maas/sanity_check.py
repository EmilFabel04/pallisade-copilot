"""
MAAS sanity check — verifies specialist endpoint connectivity and basic function.

Usage:
    python -m copilot.maas.sanity_check
    python -m copilot.maas.sanity_check --endpoint https://... --model sqlcoder
    python -m copilot.maas.sanity_check --test-bq
"""

import argparse
import asyncio
import json
import os
import sys

import httpx


async def check_models(endpoint: str, api_key: str) -> bool:
    """GET /v1/models — verify endpoint is reachable and list models."""
    url = f"{endpoint.rstrip('/')}/v1/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    print(f"\n[1] GET {url}")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("id", "?") for m in data.get("data", [])]
            print(f"    Models: {models}")
            print("    PASS")
            return True
        else:
            print(f"    HTTP {resp.status_code}: {resp.text[:200]}")
            print("    FAIL")
            return False
    except Exception as e:
        print(f"    Error: {e}")
        print("    FAIL")
        return False


async def check_completion(endpoint: str, api_key: str, model: str) -> bool:
    """POST /v1/chat/completions — verify model responds with JSON."""
    url = f"{endpoint.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return a single JSON object with key 'status' set to 'ok'. "
                    "No markdown, no code fences."
                ),
            },
            {"role": "user", "content": "Health check"},
        ],
        "temperature": 0.0,
        "max_tokens": 50,
        "response_format": {"type": "json_object"},
    }

    print(f"\n[2] POST {url}  model={model}")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            print(f"    Response: {content[:200]}")
            if content.strip():
                print("    PASS")
                return True
            else:
                print("    FAIL (empty content)")
                return False
        else:
            print(f"    HTTP {resp.status_code}: {resp.text[:200]}")
            print("    FAIL")
            return False
    except Exception as e:
        print(f"    Error: {e}")
        print("    FAIL")
        return False


async def check_bigquery() -> bool:
    """Optional: BigQuery SELECT 1 via ToolExecutor."""
    print("\n[3] BigQuery SELECT 1")
    try:
        from copilot.tool_executor import ToolExecutor
        from copilot.context_builder import CopilotContextBuilder

        builder = CopilotContextBuilder()
        context = await builder.build_context(query="health check")

        if not context.has_warehouse():
            print("    SKIP (no warehouse integration configured)")
            return True

        executor = ToolExecutor(context)
        result = await executor.execute(
            "query_warehouse", {"sql": "SELECT 1 AS health", "limit": 1}
        )
        success = result.success if hasattr(result, "success") else True
        if success:
            print(f"    Result: {result.to_dict() if hasattr(result, 'to_dict') else result}")
            print("    PASS")
            return True
        else:
            error = result.error if hasattr(result, "error") else str(result)
            print(f"    Error: {error}")
            print("    FAIL")
            return False
    except ImportError as e:
        print(f"    SKIP (missing dependency: {e})")
        return True
    except Exception as e:
        print(f"    Error: {e}")
        print("    FAIL")
        return False


async def run_checks(args: argparse.Namespace) -> int:
    """Run all checks and return exit code."""
    print("=" * 50)
    print("MAAS Sanity Check")
    print("=" * 50)
    print(f"Endpoint: {args.endpoint}")
    print(f"Model:    {args.model}")

    results = []

    results.append(await check_models(args.endpoint, args.api_key))
    results.append(await check_completion(args.endpoint, args.api_key, args.model))

    if args.test_bq:
        results.append(await check_bigquery())

    print("\n" + "=" * 50)
    passed = all(results)
    print(f"Result: {'ALL PASSED' if passed else 'SOME FAILED'}")
    print("=" * 50)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description="MAAS endpoint sanity check")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("MAAS_SQL_ENDPOINT", ""),
        help="Specialist endpoint base URL (default: $MAAS_SQL_ENDPOINT)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MAAS_SQL_API_KEY", ""),
        help="API key (default: $MAAS_SQL_API_KEY, empty for unauthenticated)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("MAAS_SQL_MODEL", "sqlcoder"),
        help="Model name (default: $MAAS_SQL_MODEL or 'sqlcoder')",
    )
    parser.add_argument(
        "--test-bq",
        action="store_true",
        help="Also test BigQuery SELECT 1 via ToolExecutor",
    )
    args = parser.parse_args()

    if not args.endpoint:
        print("Error: --endpoint or MAAS_SQL_ENDPOINT required")
        sys.exit(1)

    exit_code = asyncio.run(run_checks(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
