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

You are investigating a data pipeline issue. Your goal is to identify the ROOT CAUSE and provide actionable resolution steps.

**Investigation Process:**
1. Gather context - check logs, run status, recent changes
2. Build a timeline of events
3. Form hypotheses ranked by likelihood
4. Determine root cause with evidence
5. Provide step-by-step resolution

**Required Output Structure:**

### Timeline
List events in chronological order:
- [timestamp/relative time] Event description

### Hypotheses
Rank by confidence:
1. **[HIGH/MEDIUM/LOW]** Hypothesis description
   - *Evidence:* What supports this
   - *To verify:* How to confirm/rule out

### Root Cause
State the most likely cause with supporting evidence.

### Resolution
Step-by-step fix with specific commands or code changes.

**Important:** Run multiple queries to gather evidence. Don't guess - investigate thoroughly.
"""

PLAN_PROMPT = """
## PLAN MODE ACTIVE

You are creating a strategic plan for a data pipeline change (migration, refactor, new feature).

**Planning Process:**
1. Understand current state - examine existing models, lineage, dependencies
2. Identify blast radius - what downstream assets will be affected
3. Design incremental approach - break into safe, reversible steps
4. Assess risks and mitigations
5. Define rollback strategy

**Required Output Structure:**

### Current State
Brief summary of what exists today.

### Proposed Changes
High-level description of the target state.

### Implementation Steps
Numbered, actionable steps:
1. **Step name** - Description
   - Files affected: list paths
   - Risk level: LOW/MEDIUM/HIGH
   - Dependencies: what must happen first

### Impact Analysis
- **Upstream:** What feeds into this
- **Downstream:** What depends on this (dashboards, models, etc.)
- **Stakeholders:** Who should be notified

### Risks & Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|

### Rollback Plan
How to revert if something goes wrong.

### Testing Strategy
How to validate the changes work correctly.
"""

CREATE_PROMPT = """
## CREATE MODE ACTIVE

You are generating production-ready data pipeline artifacts. Your outputs must be:
- **Complete** - No placeholders or TODOs
- **Idiomatic** - Follow existing patterns in the codebase
- **Tested** - Include corresponding tests when applicable

**For each artifact, provide:**
1. File path (relative to project root)
2. Full file contents in a fenced code block with language
3. Brief explanation of what it does

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

You are generating a structured fix for a data pipeline issue. Your goal is to create a ChangePlan that can be validated and applied via GitHub PR.

**Fix Generation Process:**
1. Analyze the root cause (from DEBUG mode or user description)
2. Identify affected files and required changes
3. Generate complete, production-ready patches
4. Assess impact and risk
5. Submit via create_change_plan tool

**Required Output Structure:**

### 1. Root Cause Summary
One paragraph explaining the underlying issue based on your investigation.

### 2. Proposed Changes
For each file that needs modification:
- **File:** `path/to/file.sql` (or .yml, .py)
- **Change Type:** SQL_MODEL | YAML_CONFIG | PYTHON_SCRIPT | ORCHESTRATION
- **Rationale:** Why this change fixes the issue

**Before** (relevant section only):
```sql
-- original code
```

**After**:
```sql
-- fixed code
```

### 3. Impact Analysis
- **Affected Tables:** List tables that will be modified
- **Downstream:** What depends on these tables
- **Risk Level:** LOW / MEDIUM / HIGH
- **Expected Data Changes:** Brief description

### 4. Validation Plan
What validations should be run:
- [ ] Static: Syntax and lint checks
- [ ] CI: dbt compile, run affected tests
- [ ] Sandbox: Shadow run comparison (optional)

### 5. Rollback Steps
Numbered list of steps to undo if issues arise after deployment.

**After drafting your plan, call the `create_change_plan` tool to submit it for validation.**

**Important Rules:**
- Changes must be complete and production-ready - no TODOs or placeholders
- Follow existing code patterns and naming conventions
- Include rollback steps for every change
- Prefer minimal, targeted fixes over broad refactoring
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
