"""
Onboarding Question Registry

Defines all questions the LLM should ask during onboarding to learn
about the user's data pipeline setup. Questions are organized by
integration type and priority.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from enum import Enum


class QuestionCategory(str, Enum):
    """Categories of onboarding questions."""
    DEPLOYMENT = "deployment"       # How things are deployed
    CONFIGURATION = "configuration" # Config file locations, conventions
    WORKFLOW = "workflow"           # CI/CD, review process
    TEAM = "team"                   # Team structure, ownership
    CONVENTIONS = "conventions"     # Naming, folder structure
    ARCHITECTURE = "architecture"   # How components connect


@dataclass
class OnboardingQuestion:
    """Definition of an onboarding question."""
    key: str                        # Unique identifier
    text: str                       # The question text
    category: QuestionCategory
    integration_type: Optional[str] # None = general question
    priority: int = 5               # Higher = ask first (1-10)
    required: bool = False          # Must be answered
    follow_up_keys: List[str] = field(default_factory=list)  # Questions triggered by this answer
    example_answers: List[str] = field(default_factory=list)  # Help the LLM understand expected format


# ============================================
# GENERAL QUESTIONS (apply to all pipelines)
# ============================================

GENERAL_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="deployment_environments",
        text="What environments do you have for your data pipeline? (e.g., dev/staging/prod, or just prod?)",
        category=QuestionCategory.DEPLOYMENT,
        integration_type=None,
        priority=10,
        required=True,
        example_answers=["dev and prod", "dev, staging, prod", "just production"],
    ),
    OnboardingQuestion(
        key="team_size",
        text="How large is your data team? (Just you, 2-5, 5-10, or 10+?)",
        category=QuestionCategory.TEAM,
        integration_type=None,
        priority=7,
        required=False,
        example_answers=["just me", "3 people", "about 8"],
    ),
    OnboardingQuestion(
        key="code_review_process",
        text="Do you have a code review process for data pipeline changes? If so, how does it work?",
        category=QuestionCategory.WORKFLOW,
        integration_type=None,
        priority=6,
        required=False,
        example_answers=["PR review required", "no formal process", "all changes go through lead"],
    ),
    OnboardingQuestion(
        key="ci_cd_system",
        text="Do you use CI/CD for your data pipeline? If so, which system? (GitHub Actions, GitLab CI, Jenkins, etc.)",
        category=QuestionCategory.WORKFLOW,
        integration_type=None,
        priority=8,
        required=False,
        example_answers=["GitHub Actions", "no CI/CD", "Jenkins"],
    ),
]


# ============================================
# DBT QUESTIONS
# ============================================

DBT_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="dbt_deployment_method",
        text="How do you run dbt in production? (dbt Cloud, GitHub Actions, Airflow, Dagster, manually, etc.)",
        category=QuestionCategory.DEPLOYMENT,
        integration_type="DBT_CORE",
        priority=10,
        required=True,
        example_answers=["dbt Cloud", "GitHub Actions", "Airflow DAG", "manually via CLI"],
    ),
    OnboardingQuestion(
        key="dbt_profiles_location",
        text="Where does dbt get its database credentials? (profiles.yml file, environment variables, dbt Cloud connection)",
        category=QuestionCategory.CONFIGURATION,
        integration_type="DBT_CORE",
        priority=10,
        required=True,
        example_answers=["profiles.yml in ~/.dbt", "environment variables", "dbt Cloud"],
    ),
    OnboardingQuestion(
        key="dbt_target_dataset",
        text="What is your production target dataset/schema where dbt writes models?",
        category=QuestionCategory.CONFIGURATION,
        integration_type="DBT_CORE",
        priority=9,
        required=True,
        example_answers=["analytics", "prod_analytics", "dw_prod"],
    ),
    OnboardingQuestion(
        key="dbt_dev_dataset",
        text="Do you have a separate dev dataset? If so, what's it called?",
        category=QuestionCategory.CONFIGURATION,
        integration_type="DBT_CORE",
        priority=8,
        required=False,
        example_answers=["dbt_dev", "analytics_dev", "same as prod with prefix"],
    ),
    OnboardingQuestion(
        key="dbt_project_structure",
        text="Is your dbt project in a monorepo with other code, or a dedicated repo?",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="DBT_CORE",
        priority=6,
        required=False,
        example_answers=["dedicated dbt repo", "monorepo under /dbt folder", "same repo as our app"],
    ),
    OnboardingQuestion(
        key="dbt_naming_convention",
        text="Do you follow a naming convention for dbt models? (e.g., stg_*, int_*, fct_*, dim_*)",
        category=QuestionCategory.CONVENTIONS,
        integration_type="DBT_CORE",
        priority=7,
        required=False,
        example_answers=["stg/int/fct/dim prefixes", "source_table naming", "no strict convention"],
    ),
]


# ============================================
# BIGQUERY QUESTIONS
# ============================================

BIGQUERY_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="bq_project_structure",
        text="Do you use one GCP project for everything, or separate projects for dev/prod?",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="BIGQUERY",
        priority=9,
        required=True,
        example_answers=["one project", "separate dev and prod projects", "project per environment"],
    ),
    OnboardingQuestion(
        key="bq_dataset_organization",
        text="How do you organize your BigQuery datasets? (by source, by layer, by domain?)",
        category=QuestionCategory.CONVENTIONS,
        integration_type="BIGQUERY",
        priority=7,
        required=False,
        example_answers=["by layer (raw, staging, analytics)", "by source (salesforce, stripe)", "by domain (finance, marketing)"],
    ),
    OnboardingQuestion(
        key="bq_service_account",
        text="Do you use a shared service account for data pipelines, or individual accounts?",
        category=QuestionCategory.CONFIGURATION,
        integration_type="BIGQUERY",
        priority=6,
        required=False,
        example_answers=["shared service account", "per-service accounts", "my personal account for dev"],
    ),
]


# ============================================
# SNOWFLAKE QUESTIONS
# ============================================

SNOWFLAKE_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="sf_role_strategy",
        text="How do you manage Snowflake roles? (One role per user, roles per environment, functional roles?)",
        category=QuestionCategory.CONFIGURATION,
        integration_type="SNOWFLAKE",
        priority=8,
        required=False,
        example_answers=["role per user", "DEV_ROLE and PROD_ROLE", "functional roles like ANALYST, LOADER"],
    ),
    OnboardingQuestion(
        key="sf_warehouse_strategy",
        text="Do you use dedicated warehouses per use case (ETL, BI, dev) or one shared warehouse?",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="SNOWFLAKE",
        priority=8,
        required=False,
        example_answers=["dedicated per use case", "one shared warehouse", "size-based warehouses"],
    ),
    OnboardingQuestion(
        key="sf_database_structure",
        text="How do you organize Snowflake databases? (One per environment, one per domain?)",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="SNOWFLAKE",
        priority=7,
        required=False,
        example_answers=["RAW, ANALYTICS, REPORTING databases", "DEV and PROD databases", "one database"],
    ),
]


# ============================================
# AIRFLOW QUESTIONS
# ============================================

AIRFLOW_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="airflow_deployment",
        text="How is your Airflow deployed? (Managed like Astronomer/MWAA/Cloud Composer, or self-hosted?)",
        category=QuestionCategory.DEPLOYMENT,
        integration_type="AIRFLOW",
        priority=9,
        required=True,
        example_answers=["Cloud Composer", "Astronomer", "self-hosted on Kubernetes", "MWAA"],
    ),
    OnboardingQuestion(
        key="airflow_dag_structure",
        text="How are your DAGs organized? (One repo, multiple repos, monorepo?)",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="AIRFLOW",
        priority=7,
        required=False,
        example_answers=["dedicated dags repo", "dags folder in dbt repo", "multiple repos"],
    ),
    OnboardingQuestion(
        key="airflow_deploy_method",
        text="How do you deploy DAG changes? (Git sync, CI/CD, manual copy?)",
        category=QuestionCategory.WORKFLOW,
        integration_type="AIRFLOW",
        priority=8,
        required=False,
        example_answers=["git sync to bucket", "CI/CD pipeline", "manual upload"],
    ),
]


# ============================================
# FIVETRAN QUESTIONS
# ============================================

FIVETRAN_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="fivetran_destination",
        text="What is your Fivetran destination warehouse?",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="FIVETRAN",
        priority=9,
        required=True,
        example_answers=["BigQuery", "Snowflake", "Redshift"],
    ),
    OnboardingQuestion(
        key="fivetran_schema_prefix",
        text="Do you use a prefix or convention for Fivetran schemas? (e.g., fivetran_*, raw_*)",
        category=QuestionCategory.CONVENTIONS,
        integration_type="FIVETRAN",
        priority=7,
        required=False,
        example_answers=["fivetran_ prefix", "raw_ prefix", "source name only"],
    ),
    OnboardingQuestion(
        key="fivetran_sync_frequency",
        text="What's your typical Fivetran sync frequency?",
        category=QuestionCategory.CONFIGURATION,
        integration_type="FIVETRAN",
        priority=5,
        required=False,
        example_answers=["every 6 hours", "daily", "every 15 minutes"],
    ),
]


# ============================================
# GITHUB QUESTIONS
# ============================================

GITHUB_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="github_default_branch",
        text="What is the default branch for your data repositories? (e.g., main, master, develop)",
        category=QuestionCategory.WORKFLOW,
        integration_type="GITHUB",
        priority=9,
        required=True,
        example_answers=["main", "master", "develop"],
    ),
    OnboardingQuestion(
        key="github_pr_review_required",
        text="Are PR reviews required before merging data changes? If so, how many approvals?",
        category=QuestionCategory.WORKFLOW,
        integration_type="GITHUB",
        priority=8,
        required=False,
        example_answers=["yes, 1 approval required", "no", "yes, 2 approvals"],
    ),
    OnboardingQuestion(
        key="github_ci_cd_workflow",
        text="What CI/CD workflows run on your data repos? (e.g., tests, linting, dbt run)",
        category=QuestionCategory.WORKFLOW,
        integration_type="GITHUB",
        priority=8,
        required=False,
        example_answers=["dbt test on PR", "no CI/CD", "sqlfluff + dbt test + dbt build"],
    ),
    OnboardingQuestion(
        key="github_data_repo_structure",
        text="How is your data code organized in GitHub? (monorepo, separate repos for dbt/orchestration?)",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="GITHUB",
        priority=7,
        required=False,
        example_answers=["monorepo", "separate repos", "dbt in data-warehouse repo"],
    ),
]


# ============================================
# DAGSTER QUESTIONS
# ============================================

DAGSTER_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="dagster_deployment",
        text="How is Dagster deployed? (Dagster Cloud, self-hosted on K8s, Docker, local?)",
        category=QuestionCategory.DEPLOYMENT,
        integration_type="DAGSTER",
        priority=9,
        required=True,
        example_answers=["Dagster Cloud", "self-hosted on K8s", "Docker Compose", "local"],
    ),
    OnboardingQuestion(
        key="dagster_assets_structure",
        text="How do you organize your Dagster assets/jobs? (by domain, by source, single definitions file?)",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="DAGSTER",
        priority=7,
        required=False,
        example_answers=["by domain", "by data source", "single definitions file"],
    ),
    OnboardingQuestion(
        key="dagster_dbt_integration",
        text="Do you use dagster-dbt? If so, how are dbt models exposed as assets?",
        category=QuestionCategory.ARCHITECTURE,
        integration_type="DAGSTER",
        priority=6,
        required=False,
        example_answers=["yes, all models as assets", "no, separate dbt runs", "partial integration"],
    ),
]



# ============================================
# QUESTION LOOKUP FUNCTIONS
# ============================================

# Map integration types to their questions
INTEGRATION_QUESTIONS: Dict[str, List[OnboardingQuestion]] = {
    "DBT_CORE": DBT_QUESTIONS,
    "DBT_CLOUD": DBT_QUESTIONS,  # Same questions
    "BIGQUERY": BIGQUERY_QUESTIONS,
    "SNOWFLAKE": SNOWFLAKE_QUESTIONS,
    "AIRFLOW": AIRFLOW_QUESTIONS,
    "FIVETRAN": FIVETRAN_QUESTIONS,
    "GITHUB": GITHUB_QUESTIONS,
    "DAGSTER": DAGSTER_QUESTIONS,
    "PREFECT": DAGSTER_QUESTIONS,  # Similar orchestration questions
}


def get_questions_for_integration(
    integration_type: str,
    answered_keys: Optional[Set[str]] = None,
) -> List[OnboardingQuestion]:
    """
    Get pending questions for a specific integration type.

    Args:
        integration_type: The integration type (e.g., "DBT_CORE", "BIGQUERY")
        answered_keys: Set of question keys already answered

    Returns:
        List of pending questions, sorted by priority (highest first)
    """
    answered_keys = answered_keys or set()

    questions = INTEGRATION_QUESTIONS.get(integration_type.upper(), [])
    pending = [q for q in questions if q.key not in answered_keys]

    # Sort by priority (highest first)
    return sorted(pending, key=lambda q: -q.priority)


def get_all_pending_questions(
    integration_types: List[str],
    answered_keys: Optional[Set[str]] = None,
) -> List[OnboardingQuestion]:
    """
    Get all pending questions for a set of integrations.

    Includes general questions plus integration-specific ones.

    Args:
        integration_types: List of integration types connected
        answered_keys: Set of question keys already answered

    Returns:
        List of pending questions, sorted by priority
    """
    answered_keys = answered_keys or set()

    all_questions: List[OnboardingQuestion] = []

    # Add general questions
    all_questions.extend(
        q for q in GENERAL_QUESTIONS if q.key not in answered_keys
    )

    # Add integration-specific questions
    seen_keys = set()
    for int_type in integration_types:
        for q in get_questions_for_integration(int_type, answered_keys):
            if q.key not in seen_keys:
                all_questions.append(q)
                seen_keys.add(q.key)

    # Sort by priority
    return sorted(all_questions, key=lambda q: -q.priority)


def get_question_by_key(key: str) -> Optional[OnboardingQuestion]:
    """Get a question by its key."""
    # Check general questions
    for q in GENERAL_QUESTIONS:
        if q.key == key:
            return q

    # Check all integration questions
    for questions in INTEGRATION_QUESTIONS.values():
        for q in questions:
            if q.key == key:
                return q

    return None
