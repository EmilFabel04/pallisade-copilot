"""
Co-Pilot Interaction Modes

Defines the different interaction modes for Pallisade Scout,
each with specialized system prompts, tool preferences, and output formats.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import re


class InteractionMode(Enum):
    """Available interaction modes for the co-pilot."""
    ASK = "ask"
    DEBUG = "debug"
    PLAN = "plan"
    CREATE = "create"
    BUNDLE = "bundle"
    EXPLAIN = "explain"
    SUGGEST = "suggest"
    FIX = "fix"
    ONBOARD = "onboard"


@dataclass
class ModeConfig:
    """Configuration for an interaction mode."""
    mode: InteractionMode
    display_name: str
    description: str
    icon: str
    color: str
    system_prompt_section: str
    few_shot_examples: str = ""
    preferred_tools: List[str] = field(default_factory=list)
    exclusive_tools: List[str] = field(default_factory=list)
    auto_detect_patterns: List[str] = field(default_factory=list)


# Mode-specific system prompt sections
ASK_PROMPT = """
You are in ASK mode - provide clear, concise answers to general questions.

**Guidelines:**
- Answer directly and concisely
- Use bullet points for lists
- Include relevant code snippets when helpful
- Reference specific tables, columns, or models by name
"""

DEBUG_PROMPT = """
## DEBUG MODE ACTIVE

You are investigating a data pipeline issue. Identify the root cause and give actionable steps.

**Investigation Process:**
1. Gather context — check logs, run status, recent changes
2. For anomaly/data quality issues: use `run_coverage_monitor` with `monitor_type="anomaly"` instead of manual SQL
3. Determine root cause with evidence
4. Provide concrete resolution steps

**Response format — keep it short and scannable:**

**Problem:** One sentence stating what went wrong and how it was detected.

**Cause:** One sentence explaining why it happened, backed by the data (include the key numbers).

**Fix:** 2-4 bullet points with concrete actions to resolve it. Be specific — use real table/column names.

**Rules:**
- No bold section headers other than Problem / Cause / Fix
- No hypothesis lists, confidence labels, or "to verify" sub-items — just state what you found
- Keep the entire response under 150 words when possible
- Use plain text, minimal formatting. No nested bullets, no italic emphasis blocks
- If the baseline is too small or confidence is low, say so in one line under Cause
- Run multiple queries to gather evidence. Don't guess — investigate thoroughly
"""

PLAN_PROMPT = """
## PLAN MODE ACTIVE

**CRITICAL: Before proposing ANY plan, you MUST run impact analysis first.**

You are creating a strategic plan for a data pipeline change (migration, refactor, new feature).

**Planning Process (MANDATORY ORDER):**
1. ✅ **RUN LINEAGE CHECK FIRST** - Call `get_downstream` and `get_upstream` on all objects being changed
2. Analyze current state with lineage context
3. Identify ALL breaking changes from lineage
4. Design incremental steps that include fixes for breaking changes
5. Assess risks and mitigations
6. Define rollback strategy

**Required Output Structure:**

### Impact Analysis (MANDATORY - DO THIS FIRST)
Before proposing any changes, run lineage tools and report:

**Upstream Sources:**
- [List what feeds into the objects being changed]

**Downstream Dependencies:**
| Object | Type | Will Break? | Required Fix |
|--------|------|-------------|--------------|
| example_model | dbt | YES | Update ref() |
| dashboard_x | Looker | YES | Update source |

**Breaking Changes Summary:** X items need attention

### Current State
Brief summary of what exists today.

### Proposed Changes
High-level description of the target state.

### Implementation Steps
Numbered steps that INCLUDE fixes for all breaking changes:
1. **Step name** - Description
   - Files affected: list paths
   - Breaking changes addressed: which downstream items this fixes
   - Risk level: LOW/MEDIUM/HIGH

### Risks & Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|

### Rollback Plan
How to revert if something goes wrong.

### Testing Strategy
How to validate the changes work correctly.

**IMPORTANT: If you skip the lineage check, your plan is INCOMPLETE and potentially dangerous.**
"""

CREATE_PROMPT = """
## CREATE MODE ACTIVE

**CRITICAL: For modifications to existing objects, you MUST check impact first.**

You are generating production-ready data pipeline artifacts. Your outputs must be:
- **Complete** - No placeholders or TODOs
- **Idiomatic** - Follow existing patterns in the codebase
- **Tested** - Include corresponding tests when applicable
- **Safe** - Check what might break before modifying

**Before Modifying Existing Objects:**
1. ✅ Run `get_downstream` to check what depends on it
2. ✅ Report any breaking changes
3. ✅ Include migration steps for affected downstream objects

**For each artifact, provide:**
1. File path (relative to project root)
2. Full file contents in a fenced code block with language
3. Brief explanation of what it does
4. **If modifying existing:** Impact on downstream objects

**Artifact Types:**
- **dbt models** - SQL with Jinja, proper refs/sources
- **dbt tests** - schema.yml tests or custom test SQL
- **dbt macros** - Reusable Jinja functions
- **SQL queries** - Analytical or transformation queries
- **YAML configs** - dbt schema files, source definitions

**Important Rules:**
- Use REAL table/column names from the context provided
- Follow the user's existing naming conventions
- Include appropriate materializations (table, view, incremental)
- Add documentation (description fields)
- **If replacing/modifying:** Check lineage and address breaking changes
"""

BUNDLE_PROMPT = """
## BUNDLE MODE ACTIVE

You are creating a downloadable package of data pipeline artifacts.

**Bundle Contents:**
- All generated SQL models
- Corresponding schema YAML files
- Test definitions
- Documentation

**Output Format:**
For each file in the bundle, output:

```
=== FILE: path/to/file.sql ===
```sql
-- file contents
```

After all files, provide a summary:

### Bundle Summary
- **Files:** Count and list
- **Models:** List with materializations
- **Tests:** Count and types
- **Next Steps:** How to integrate into project

The user can download these as a ZIP package.
"""

EXPLAIN_PROMPT = """
## EXPLAIN MODE ACTIVE

You are teaching and explaining data pipeline concepts in depth.

**Explanation Approach:**
1. Start with a high-level summary
2. Break down into digestible sections
3. Use analogies when helpful
4. Include concrete examples from their data
5. Build understanding progressively

**Output Guidelines:**
- Use headers to organize sections
- Include diagrams when helpful (ASCII or describe for visualization)
- Reference specific tables/models from their pipeline
- Explain the "why" not just the "what"
- Anticipate follow-up questions

**For technical concepts:**
- Show real examples from their data
- Explain implications and trade-offs
- Connect to broader data engineering principles
"""

ONBOARD_PROMPT = """
## ONBOARD MODE ACTIVE

You are conducting an onboarding interview to learn about the user's data pipeline setup.
Your goal is to gather specific, actionable context that will help you answer questions
without needing clarification later.

**Rules:**
1. Ask ONE question at a time
2. Acknowledge their answer before asking the next question
3. Use the `save_onboarding_context` tool to persist each answer
4. If they give a short answer, ask a clarifying follow-up
5. When all questions for an integration are answered, summarize what you learned
6. Be conversational, not robotic

**CRITICAL: Cover ALL Connected Integrations**
Use `get_pending_questions` to see what questions remain. You MUST ask questions for
EACH connected integration type, not just dbt. This includes:

- **Warehouses** (BigQuery, Snowflake, Postgres): Project structure, datasets, roles
- **Transformation** (dbt Core/Cloud): Deployment, profiles location, naming conventions
- **Orchestration** (Airflow, Dagster, Prefect): How DAGs are deployed and triggered
- **Ingestion** (Fivetran, Airbyte): Destination, schema prefixes, sync frequency
- **Version Control** (GitHub): Default branch, PR review process, CI/CD workflows
- **Observability** (Monte Carlo, Soda, Elementary): Alert channels, incident handling

**What to Learn Per Integration:**
- Deployment methods (how it runs, how code gets deployed)
- Configuration locations (where credentials live, which config files matter)
- Team workflows (PR review process, who owns what)
- Naming conventions (prefixes, folder structure)
- Architecture decisions (why things are set up this way)

**After Each Answer:**
"Got it - you [summary of what they said]. [Next question or follow-up]"

**When Done with an Integration:**
"Great! I've learned about your [integration] setup:
- [Key point 1]
- [Key point 2]

This means when you ask me to [specific task], I can now [specific capability unlocked]."

**Getting Started:**
Use `get_pending_questions` to see unanswered questions across ALL connected integrations.
Start with general questions, then proceed through each integration type.
"""

SUGGEST_PROMPT = """
## SUGGEST MODE ACTIVE

You are proactively identifying improvements for the data pipeline.

**Analysis Areas:**
- Test coverage gaps
- Missing documentation
- Performance optimizations
- Data quality risks
- Maintenance burden
- Best practice violations

**Required Output Structure:**

### Priority Improvements
Ranked by impact/effort:

1. **[HIGH IMPACT]** Suggestion title
   - *Current state:* What exists now
   - *Problem:* Why it's an issue
   - *Recommendation:* What to do
   - *Effort:* LOW/MEDIUM/HIGH

### Quick Wins
Low-effort improvements that add immediate value.

### Technical Debt
Issues to address in future iterations.

### Metrics to Track
What to monitor for pipeline health.

**Important:** Base suggestions on actual evidence from their pipeline, not generic advice.
"""

FIX_PROMPT = """
## FIX MODE ACTIVE

**CRITICAL: Before generating ANY fix, you MUST check what will break.**

You are generating a structured fix for a data pipeline issue. Your goal is to create a ChangePlan that can be validated and applied via GitHub PR.

**Fix Generation Process (MANDATORY ORDER):**
1. ✅ **RUN LINEAGE CHECK FIRST** - Call `get_downstream` on affected tables/models
2. Analyze the root cause
3. Identify ALL breaking changes from lineage
4. Generate fixes for EVERYTHING that breaks (not just the original issue)
5. Submit via create_change_plan tool

**Required Output Structure:**

### 1. Impact Analysis (MANDATORY - DO THIS FIRST)
Before proposing fixes, run lineage tools:

**Objects Being Modified:**
- [List tables/models affected by this fix]

**Downstream Dependencies Found:**
| Object | Type | Will Break? | Reason |
|--------|------|-------------|--------|

**Breaking Changes:** X items need fixes beyond the original issue

### 2. Root Cause Summary
One paragraph explaining the underlying issue.

### 3. Complete Fix (includes ALL affected objects)
For each file that needs modification (including downstream fixes):
- **File:** `path/to/file.sql`
- **Change Type:** SQL_MODEL | YAML_CONFIG | PYTHON_SCRIPT
- **Fixes:** Original issue / Downstream breakage

**Before**:
```sql
-- original code
```

**After**:
```sql
-- fixed code
```

### 4. Validation Plan
What validations should be run:
- [ ] Static: Syntax and lint checks
- [ ] CI: dbt compile, run affected tests
- [ ] Downstream: Verify all dependent objects still work

### 5. Rollback Steps
Numbered list of steps to undo if issues arise.

**After drafting your plan, call the `create_change_plan` tool to submit it for validation.**

**Important Rules:**
- ALWAYS check lineage before proposing fixes
- Include fixes for ALL downstream breakages, not just the original issue
- Changes must be complete and production-ready
- Follow existing code patterns and naming conventions

**When User Says "go ahead", "do it", or "proceed":**
- IMMEDIATELY execute the next action (create_change_plan, apply_change_plan)
- Do NOT re-show previous query results
- Do NOT ask for more confirmation
- Report the outcome: "I've created the change plan" or "I've opened PR #123 at [URL]"
"""


# Mode configurations
MODES: Dict[InteractionMode, ModeConfig] = {
    InteractionMode.ASK: ModeConfig(
        mode=InteractionMode.ASK,
        display_name="Ask",
        description="General questions about your data pipeline",
        icon="question",
        color="blue",
        system_prompt_section=ASK_PROMPT,
        preferred_tools=[
            "query_warehouse",
            "get_table_stats",
            "search_lineage",
            "search_knowledge_base",
            "get_coverage_report",
            "run_coverage_monitor",
            "get_node_coverage",
        ],
        auto_detect_patterns=[],  # Default mode, no detection needed
    ),

    InteractionMode.DEBUG: ModeConfig(
        mode=InteractionMode.DEBUG,
        display_name="Debug",
        description="Investigate failures and find root causes",
        icon="bug",
        color="red",
        system_prompt_section=DEBUG_PROMPT,
        preferred_tools=[
            "run_coverage_monitor",
            "get_coverage_report",
            "get_node_coverage",
            "get_coverage_gaps",
            "get_airflow_task_logs",
            "get_airflow_recent_failures",
            "get_dbt_test_results",
            "get_dbt_run_history",
            "get_fivetran_sync_logs",
            "query_warehouse",
            "get_upstream",
            "get_downstream",
        ],
        auto_detect_patterns=[
            r"why did .* fail",
            r"what went wrong",
            r"error in",
            r"investigate",
            r"root cause",
            r"debug",
            r"broken",
            r"not working",
            r"anomal",
            r"outlier",
            r"unusual",
            r"spike",
            r"drop(?:ped)?",
            r"unexpected",
            r"deviation",
            r"abnormal",
        ],
    ),

    InteractionMode.PLAN: ModeConfig(
        mode=InteractionMode.PLAN,
        display_name="Plan",
        description="Design migration and refactoring strategies",
        icon="map",
        color="purple",
        system_prompt_section=PLAN_PROMPT,
        preferred_tools=[
            "get_downstream",
            "get_upstream",
            "get_dbt_model",
            "get_dbt_lineage",
            "get_node_details",
            "get_table_dependencies",
        ],
        auto_detect_patterns=[
            r"how should i",
            r"plan for",
            r"migrate",
            r"refactor",
            r"strategy for",
            r"best approach",
            r"redesign",
        ],
    ),

    InteractionMode.CREATE: ModeConfig(
        mode=InteractionMode.CREATE,
        display_name="Create",
        description="Generate dbt models, tests, and configs",
        icon="sparkles",
        color="green",
        system_prompt_section=CREATE_PROMPT,
        preferred_tools=[
            "query_warehouse",
            "get_table_stats",
            "get_dbt_model",
            "get_column_lineage",
        ],
        exclusive_tools=[
            "generate_dbt_model",
            "generate_dbt_test",
        ],
        auto_detect_patterns=[
            r"create a",
            r"generate a",
            r"write a",
            r"build a .* model",
            r"make a .* test",
            r"new model for",
        ],
    ),

    InteractionMode.BUNDLE: ModeConfig(
        mode=InteractionMode.BUNDLE,
        display_name="Bundle",
        description="Package artifacts for download",
        icon="package",
        color="orange",
        system_prompt_section=BUNDLE_PROMPT,
        preferred_tools=[
            "query_warehouse",
            "get_dbt_model",
        ],
        exclusive_tools=[
            "create_bundle",
        ],
        auto_detect_patterns=[
            r"bundle",
            r"package",
            r"export",
            r"download",
            r"zip",
        ],
    ),

    InteractionMode.EXPLAIN: ModeConfig(
        mode=InteractionMode.EXPLAIN,
        display_name="Explain",
        description="Deep understanding and learning",
        icon="book-open",
        color="cyan",
        system_prompt_section=EXPLAIN_PROMPT,
        preferred_tools=[
            "search_knowledge_base",
            "get_upstream",
            "get_downstream",
            "get_node_details",
            "get_dbt_model",
            "get_column_lineage",
        ],
        auto_detect_patterns=[
            r"what is",
            r"how does .* work",
            r"explain",
            r"teach me",
            r"help me understand",
            r"walk me through",
        ],
    ),

    InteractionMode.SUGGEST: ModeConfig(
        mode=InteractionMode.SUGGEST,
        display_name="Suggest",
        description="Get improvement recommendations",
        icon="lightbulb",
        color="yellow",
        system_prompt_section=SUGGEST_PROMPT,
        preferred_tools=[
            "get_table_stats",
            "get_dbt_test_results",
            "get_upstream",
            "get_downstream",
            "query_warehouse",
            "get_coverage_report",
            "get_coverage_gaps",
            "get_monitor_recommendations",
        ],
        auto_detect_patterns=[
            r"what should i improve",
            r"suggest",
            r"recommend",
            r"how can i make .* better",
            r"best practices",
            r"optimize",
        ],
    ),

    InteractionMode.FIX: ModeConfig(
        mode=InteractionMode.FIX,
        display_name="Fix",
        description="Generate validated fixes for pipeline issues",
        icon="wrench",
        color="emerald",
        system_prompt_section=FIX_PROMPT,
        preferred_tools=[
            "query_warehouse",
            "get_dbt_model",
            "get_upstream",
            "get_downstream",
            "get_active_incidents",
            "run_coverage_monitor",
            "create_change_plan",
            "validate_change_plan",
        ],
        exclusive_tools=[
            "create_change_plan",
            "validate_change_plan",
            "apply_change_plan",
        ],
        auto_detect_patterns=[
            r"fix (?:the|this|my)",
            r"apply (?:a|the) fix",
            r"create a fix",
            r"generate (?:a|the) fix",
            r"patch (?:the|this)",
            r"repair (?:the|this)",
            r"correct (?:the|this)",
        ],
    ),

    InteractionMode.ONBOARD: ModeConfig(
        mode=InteractionMode.ONBOARD,
        display_name="Onboard",
        description="Teach me about your pipeline setup",
        icon="graduation-cap",
        color="indigo",
        system_prompt_section=ONBOARD_PROMPT,
        preferred_tools=[
            "get_pending_questions",
            "save_onboarding_context",
            "complete_onboarding",
        ],
        exclusive_tools=[
            "save_onboarding_context",
            "complete_onboarding",
        ],
        auto_detect_patterns=[
            r"start onboarding",
            r"teach you about",
            r"let me explain my setup",
            r"learn about my pipeline",
        ],
    ),
}


def get_mode_config(mode: str) -> ModeConfig:
    """Get the configuration for a mode by string name."""
    try:
        mode_enum = InteractionMode(mode.lower())
        return MODES[mode_enum]
    except (ValueError, KeyError):
        # Default to ASK mode
        return MODES[InteractionMode.ASK]


def detect_mode(message: str) -> Optional[InteractionMode]:
    """
    Auto-detect the appropriate mode from message content.
    Returns None if no strong match (caller should use default).
    """
    message_lower = message.lower()

    # Check each mode's patterns
    for mode, config in MODES.items():
        if mode == InteractionMode.ASK:
            continue  # Skip default mode

        for pattern in config.auto_detect_patterns:
            if re.search(pattern, message_lower):
                return mode

    return None


def parse_slash_command(message: str) -> tuple[Optional[InteractionMode], str]:
    """
    Parse slash command from message.
    Returns (mode, remaining_message) or (None, original_message).
    """
    slash_commands = {
        "/ask": InteractionMode.ASK,
        "/debug": InteractionMode.DEBUG,
        "/plan": InteractionMode.PLAN,
        "/create": InteractionMode.CREATE,
        "/bundle": InteractionMode.BUNDLE,
        "/explain": InteractionMode.EXPLAIN,
        "/suggest": InteractionMode.SUGGEST,
        "/fix": InteractionMode.FIX,
        "/onboard": InteractionMode.ONBOARD,
    }

    for cmd, mode in slash_commands.items():
        if message.lower().startswith(cmd):
            remaining = message[len(cmd):].strip()
            return mode, remaining

    return None, message


def get_available_modes() -> List[Dict]:
    """Get list of modes for API/frontend consumption."""
    return [
        {
            "id": config.mode.value,
            "name": config.display_name,
            "description": config.description,
            "icon": config.icon,
            "color": config.color,
        }
        for config in MODES.values()
    ]
