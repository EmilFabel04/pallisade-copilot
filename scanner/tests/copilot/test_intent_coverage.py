"""Coverage of the four CREATE / BUNDLE / ONBOARD / SUGGEST intents.

Until item 6 of the Tier-4 plan landed, these four ``InteractionMode``
values existed (with prompts and tool wiring) but were unreachable from
natural language — they fired only via slash commands. Tests here pin
NL→Intent classification and the Intent→mode mapping for each, so the
modes stay reachable through the classifier path.
"""

from copilot.intent import classify_intent, intent_to_mode, Intent


class TestCreateIntent:
    def test_create_a_watch(self):
        result = classify_intent("create a watch for my orders table")
        assert result.primary.intent == Intent.CREATE

    def test_add_a_monitor(self):
        result = classify_intent("add a monitor on the events table")
        assert result.primary.intent == Intent.CREATE

    def test_set_up_a_check(self):
        result = classify_intent("set up a check for null rate on user_id")
        assert result.primary.intent == Intent.CREATE

    def test_intent_to_mode(self):
        result = classify_intent("create a watch for my orders table")
        assert intent_to_mode(result) == "create"


class TestBundleIntent:
    def test_bundle_these_monitors(self):
        result = classify_intent("bundle these monitors into one group")
        assert result.primary.intent == Intent.BUNDLE

    def test_combine_alerts(self):
        result = classify_intent("combine these alerts into a single group")
        assert result.primary.intent == Intent.BUNDLE

    def test_consolidate_checks(self):
        result = classify_intent("consolidate the freshness checks for orders")
        assert result.primary.intent == Intent.BUNDLE

    def test_intent_to_mode(self):
        result = classify_intent("bundle these monitors into one group")
        assert intent_to_mode(result) == "bundle"


class TestOnboardIntent:
    def test_set_up_my_warehouse(self):
        result = classify_intent("set up my snowflake warehouse")
        assert result.primary.intent == Intent.ONBOARD

    def test_connect_dbt(self):
        result = classify_intent("connect dbt to this project")
        assert result.primary.intent == Intent.ONBOARD

    def test_onboard_keyword(self):
        result = classify_intent("onboard a new BigQuery integration")
        assert result.primary.intent == Intent.ONBOARD

    def test_intent_to_mode(self):
        result = classify_intent("connect dbt to this project")
        assert intent_to_mode(result) == "onboard"


class TestSuggestIntent:
    def test_suggest_monitors(self):
        result = classify_intent("suggest some monitors for my orders table")
        assert result.primary.intent == Intent.SUGGEST

    def test_recommend_checks(self):
        result = classify_intent("recommend checks for the events pipeline")
        assert result.primary.intent == Intent.SUGGEST

    def test_propose_alerts(self):
        result = classify_intent("propose some alerts for this table")
        assert result.primary.intent == Intent.SUGGEST

    def test_intent_to_mode(self):
        result = classify_intent("recommend checks for the events pipeline")
        assert intent_to_mode(result) == "suggest"


class TestExistingIntentsUnaffected:
    """The new intents must not steal cases from existing classifications."""

    def test_info_still_wins_for_count(self):
        result = classify_intent("how many orders do I have?")
        assert result.primary.intent == Intent.INFO

    def test_debug_still_wins_for_failure(self):
        result = classify_intent("why did my orders DAG fail last night?")
        assert result.primary.intent == Intent.DEBUG

    def test_fix_still_wins_over_create(self):
        # "fix" + "broken" should still win over a stray "create" verb in
        # the message — fix is a stronger signal.
        result = classify_intent("fix the broken create_table step in my dag")
        assert result.primary.intent == Intent.FIX

    def test_explain_still_wins_for_explain_command(self):
        result = classify_intent("explain how lineage extraction works")
        assert result.primary.intent == Intent.EXPLAIN
