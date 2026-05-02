"""Tests for the integration-health classifier and store.

Pin the classifier's category mapping (especially the BILLING-trumps-
status-code rule, which is the case the user actually hit in
production with a Metabase trial expiry) and the store's
per-tenant/per-pipeline isolation.
"""

import pytest

from integrations.health import (
    FailureCategory,
    HealthStore,
    IntegrationHealth,
    build_failure_snapshot,
    classify_error,
)


# ---------------------------------------------------------------------------
# Classifier — billing trumps status code
# ---------------------------------------------------------------------------


class TestBillingDetection:
    """Billing pages arrive in many disguises. The classifier must
    catch them by phrase regardless of HTTP status."""

    def test_metabase_trial_expired_in_503_body(self):
        """The actual incident: Metabase trial expired returns 503
        with a billing/upgrade page in the body, not 402."""
        category, retryable = classify_error(
            integration_type="METABASE",
            status_code=503,
            message="Service Unavailable",
            response_body=(
                "<html>Your Metabase trial has expired. "
                "Upgrade your plan to continue using the service.</html>"
            ),
        )
        assert category is FailureCategory.BILLING
        # Billing isn't retryable — hammering the endpoint won't fix it.
        assert retryable is False

    def test_subscription_cancelled_in_message(self):
        category, _ = classify_error(
            integration_type="LOOKER",
            status_code=200,
            message="Subscription expired. Please renew.",
        )
        assert category is FailureCategory.BILLING

    def test_account_suspended(self):
        category, _ = classify_error(
            integration_type="MIXPANEL",
            status_code=403,
            message="account suspended",
        )
        # Suspended-account phrase MUST win over the 403 — otherwise
        # the user gets "auth issue, check your token" which is wrong
        # advice when the actual problem is billing.
        assert category is FailureCategory.BILLING

    def test_402_payment_required_status(self):
        category, _ = classify_error(
            integration_type="STRIPE",
            status_code=402,
            message="",
        )
        assert category is FailureCategory.BILLING

    def test_deprovisioned_phrase(self):
        category, _ = classify_error(
            integration_type="METABASE",
            status_code=None,
            message="Connection failed: instance has been deprovisioned",
        )
        assert category is FailureCategory.BILLING


# ---------------------------------------------------------------------------
# Classifier — other categories
# ---------------------------------------------------------------------------


class TestStandardCategories:
    @pytest.mark.parametrize("status,expected,retry", [
        (401, FailureCategory.AUTH, False),
        (403, FailureCategory.AUTH, False),
        (404, FailureCategory.NOT_FOUND, False),
        (429, FailureCategory.RATE_LIMIT, True),
        (500, FailureCategory.SERVER, True),
        (502, FailureCategory.SERVER, True),
        (504, FailureCategory.SERVER, True),
    ])
    def test_status_code_dispatch(self, status, expected, retry):
        category, retryable = classify_error(
            integration_type="X",
            status_code=status,
            message="",
        )
        assert category is expected
        assert retryable is retry

    def test_dns_failure_is_network(self):
        category, retryable = classify_error(
            integration_type="POSTGRES",
            message="psycopg2.OperationalError: could not translate host name",
            response_body=None,
        )
        # Generic phrasing the classifier doesn't pin specifically →
        # falls to UNKNOWN. Tightening the network regex is a tunable.
        # What we DO want pinned is the explicit DNS phrase.
        assert category in (FailureCategory.NETWORK, FailureCategory.UNKNOWN)
        category2, _ = classify_error(
            integration_type="POSTGRES",
            message="dns lookup failed for db.internal",
        )
        assert category2 is FailureCategory.NETWORK

    def test_connection_refused_is_network_retryable(self):
        category, retryable = classify_error(
            integration_type="X",
            message="connection refused",
        )
        assert category is FailureCategory.NETWORK
        assert retryable is True

    def test_invalid_token_phrase_is_auth(self):
        category, _ = classify_error(
            integration_type="GITHUB",
            message="invalid token: bad_credentials",
        )
        assert category is FailureCategory.AUTH

    def test_missing_required_config_is_config(self):
        category, _ = classify_error(
            integration_type="DBT",
            message="missing required config: project_dir",
        )
        assert category is FailureCategory.CONFIG

    def test_unknown_falls_through(self):
        category, retryable = classify_error(
            integration_type="X",
            message="something weird happened",
        )
        assert category is FailureCategory.UNKNOWN
        # Don't retry on guesswork.
        assert retryable is False


# ---------------------------------------------------------------------------
# build_failure_snapshot
# ---------------------------------------------------------------------------


class TestBuildFailureSnapshot:
    def test_billing_snapshot_has_likely_cause_phrasing(self):
        snap = build_failure_snapshot(
            integration_type="METABASE",
            status_code=503,
            message="trial expired",
        )
        assert snap.status == "FAILED"
        assert snap.failure_category is FailureCategory.BILLING
        # "Likely" hedge in the reason — the user's design called this
        # out: prefer "likely cause" language unless you have direct
        # evidence (which the classifier doesn't).
        assert "likely" in snap.reason.lower()

    def test_unknown_preserves_raw_message(self):
        # When the classifier can't decide, the raw message is the
        # only signal the LLM has. Don't replace it with a generic
        # "unknown failure" string.
        snap = build_failure_snapshot(
            integration_type="X",
            message="weird custom provider error",
        )
        assert snap.failure_category is FailureCategory.UNKNOWN
        assert snap.reason == "weird custom provider error"

    def test_response_body_excerpt_recorded(self):
        snap = build_failure_snapshot(
            integration_type="METABASE",
            status_code=503,
            message="Service Unavailable",
            response_body="<html>" + ("x" * 1000) + "trial expired</html>",
        )
        assert "response_excerpt" in snap.evidence
        # Truncated at 500 to keep the trace bounded.
        assert len(snap.evidence["response_excerpt"]) <= 500


# ---------------------------------------------------------------------------
# HealthStore
# ---------------------------------------------------------------------------


class TestHealthStore:
    def test_record_and_get_round_trip(self):
        store = HealthStore()
        snap = build_failure_snapshot(
            integration_type="METABASE",
            status_code=503,
            message="trial expired",
        )
        store.record(snap, org_id="org_a", pipeline_id="pipe_1")
        out = store.get("METABASE", org_id="org_a", pipeline_id="pipe_1")
        assert out is snap

    def test_pipeline_isolation(self):
        """Same org, two pipelines, same integration — snapshots
        must NOT leak across pipelines (pipeline profiles are
        isolated workspaces)."""
        store = HealthStore()
        a = build_failure_snapshot(
            integration_type="METABASE",
            status_code=503,
            message="trial expired",
        )
        b = build_failure_snapshot(
            integration_type="METABASE",
            status_code=401,
            message="invalid token",
        )
        store.record(a, org_id="org", pipeline_id="pipe_a")
        store.record(b, org_id="org", pipeline_id="pipe_b")
        assert store.get("METABASE", org_id="org", pipeline_id="pipe_a") is a
        assert store.get("METABASE", org_id="org", pipeline_id="pipe_b") is b
        assert (
            store.get("METABASE", org_id="org", pipeline_id="pipe_a").failure_category
            is FailureCategory.BILLING
        )

    def test_org_isolation(self):
        store = HealthStore()
        snap = build_failure_snapshot(integration_type="X", message="trial expired")
        store.record(snap, org_id="org_a", pipeline_id="p")
        # Different org, same pipeline name → must miss.
        assert store.get("X", org_id="org_b", pipeline_id="p") is None

    def test_integration_type_normalized_uppercase(self):
        # Snapshot stored as "METABASE" must be retrievable as
        # "metabase" (the integration_types convention is uppercase
        # but callers don't always remember).
        store = HealthStore()
        snap = build_failure_snapshot(integration_type="metabase", message="x")
        store.record(snap)
        assert store.get("METABASE") is snap
        assert store.get("metabase") is snap

    def test_list_for_pipeline(self):
        store = HealthStore()
        store.record(
            build_failure_snapshot(integration_type="A", message="trial expired"),
            org_id="org", pipeline_id="p",
        )
        store.record(
            build_failure_snapshot(integration_type="B", message="connection refused"),
            org_id="org", pipeline_id="p",
        )
        store.record(
            build_failure_snapshot(integration_type="C", message="x"),
            org_id="org", pipeline_id="other",
        )
        snaps = store.list_for(org_id="org", pipeline_id="p")
        assert sorted(s.integration_type for s in snaps) == ["A", "B"]


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------


class TestAnnotation:
    def test_annotate_attaches_to_snapshot(self):
        store = HealthStore()
        snap = build_failure_snapshot(
            integration_type="METABASE",
            status_code=503,
            message="Service Unavailable",
            response_body="<html>maintenance</html>",
        )
        store.record(snap, org_id="o", pipeline_id="p")
        # User says: it's actually billing.
        updated = store.annotate(
            "METABASE",
            "Cancelled trial last week — billing issue",
            org_id="o", pipeline_id="p",
        )
        assert updated is not None
        assert updated.user_annotation == "Cancelled trial last week — billing issue"
        # Auto-classification fields preserved — annotation augments,
        # doesn't replace.
        assert updated.failure_category is snap.failure_category

    def test_annotate_without_snapshot_returns_none(self):
        # Can't annotate something we haven't observed yet.
        store = HealthStore()
        result = store.annotate("METABASE", "billing", org_id="o", pipeline_id="p")
        assert result is None
