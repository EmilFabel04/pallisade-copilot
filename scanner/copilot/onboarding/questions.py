"""
Onboarding Question Registry

Defines all questions the LLM should ask during onboarding to learn
about the user's business context — things that can't be derived from
the connected integrations, monitors, or lineage views.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from enum import Enum


class QuestionCategory(str, Enum):
    """Categories of onboarding questions."""
    BUSINESS = "business"           # Company, industry, purpose
    STAKEHOLDERS = "stakeholders"   # Who uses the data, who to escalate to
    CRITICALITY = "criticality"     # SLAs, impact, compliance
    TEAM = "team"                   # Team structure, ownership
    WORKFLOW = "workflow"           # How work gets done day-to-day
    CONVENTIONS = "conventions"     # Naming, terminology, domain language


@dataclass
class OnboardingQuestion:
    """Definition of an onboarding question."""
    key: str                        # Unique identifier
    text: str                       # The question text
    category: QuestionCategory
    integration_type: Optional[str] # None = general question
    priority: int = 5               # Higher = ask first (1-10)
    required: bool = False          # Must be answered
    follow_up_keys: List[str] = field(default_factory=list)
    example_answers: List[str] = field(default_factory=list)


# ============================================
# GENERAL QUESTIONS (business context)
# ============================================

GENERAL_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="company_industry",
        text="What kind of company is this? What industry are you in?",
        category=QuestionCategory.BUSINESS,
        integration_type=None,
        priority=10,
        required=True,
        example_answers=["fintech startup", "e-commerce, B2C", "healthcare SaaS", "ad-tech"],
    ),
    OnboardingQuestion(
        key="pipeline_purpose",
        text="What is this data pipeline for? What product, app, or business function does it serve?",
        category=QuestionCategory.BUSINESS,
        integration_type=None,
        priority=10,
        required=True,
        example_answers=[
            "powers our analytics dashboards for the finance team",
            "feeds our recommendation engine",
            "ETL for our customer-facing reporting product",
            "internal BI — marketing and product analytics",
        ],
    ),
    OnboardingQuestion(
        key="pipeline_environment",
        text="Is this a production pipeline, a dev/staging environment, or something else?",
        category=QuestionCategory.BUSINESS,
        integration_type=None,
        priority=9,
        required=True,
        example_answers=["production", "dev and prod — this one is prod", "staging for now, going to prod soon"],
    ),
    OnboardingQuestion(
        key="data_consumers",
        text="Who are the main consumers of this data? (e.g., exec dashboards, product team, ML models, external customers)",
        category=QuestionCategory.STAKEHOLDERS,
        integration_type=None,
        priority=9,
        required=True,
        example_answers=[
            "CFO and finance team use Looker dashboards",
            "product managers and data scientists",
            "external clients via our API",
            "marketing team for campaign targeting",
        ],
    ),
    OnboardingQuestion(
        key="business_impact",
        text="What happens to the business when this pipeline breaks or data is late? Who feels the pain?",
        category=QuestionCategory.CRITICALITY,
        integration_type=None,
        priority=9,
        required=False,
        example_answers=[
            "customers see stale data in their dashboards — support tickets spike",
            "finance can't close the books — CFO escalates",
            "recommendation engine serves bad results — revenue drops",
            "internal only, people just wait",
        ],
    ),
    OnboardingQuestion(
        key="key_metrics",
        text="What are the key business metrics that depend on this pipeline? (e.g., revenue, conversion rate, churn)",
        category=QuestionCategory.BUSINESS,
        integration_type=None,
        priority=8,
        required=False,
        example_answers=[
            "MRR, churn rate, LTV",
            "conversion funnel metrics — visitor to purchase",
            "daily active users, feature adoption",
            "GMV, take rate, seller metrics",
        ],
    ),
    OnboardingQuestion(
        key="data_freshness_expectations",
        text="How fresh does the data need to be for your stakeholders? (real-time, hourly, daily, weekly?)",
        category=QuestionCategory.CRITICALITY,
        integration_type=None,
        priority=8,
        required=False,
        example_answers=[
            "dashboards need yesterday's data by 9am",
            "near real-time for the product, daily for BI",
            "weekly is fine for most reports",
            "hourly for operational metrics, daily for everything else",
        ],
    ),
    OnboardingQuestion(
        key="team_structure",
        text="How large is the data/engineering team working on this pipeline, and how is ownership split?",
        category=QuestionCategory.TEAM,
        integration_type=None,
        priority=7,
        required=False,
        example_answers=[
            "3 data engineers, 2 analysts — engineers own the pipeline, analysts own the models",
            "just me, I do everything",
            "team of 8 — split by domain (finance, marketing, product)",
            "5 people, but only 2 touch the pipeline regularly",
        ],
    ),
    OnboardingQuestion(
        key="compliance_sensitivity",
        text="Does this pipeline handle sensitive data? Any compliance requirements? (PII, GDPR, HIPAA, SOC2, etc.)",
        category=QuestionCategory.CRITICALITY,
        integration_type=None,
        priority=7,
        required=False,
        example_answers=[
            "yes, PII — we hash emails and phone numbers",
            "HIPAA compliant — PHI in separate dataset with restricted access",
            "SOC2 — audit logs required for all data access",
            "no sensitive data, all internal analytics",
        ],
    ),
    OnboardingQuestion(
        key="incident_process",
        text="When something breaks, how does your team find out and respond? (Slack alerts, PagerDuty, someone notices a dashboard is wrong?)",
        category=QuestionCategory.WORKFLOW,
        integration_type=None,
        priority=6,
        required=False,
        example_answers=[
            "alerts go to #data-alerts Slack channel, on-call engineer picks it up",
            "usually someone notices a dashboard looks wrong and pings us",
            "PagerDuty for critical pipelines, Slack for the rest",
            "I check Airflow every morning",
        ],
    ),
    OnboardingQuestion(
        key="domain_terminology",
        text="Any important domain-specific terms I should know? (e.g., what you call certain entities, business logic, or internal jargon)",
        category=QuestionCategory.CONVENTIONS,
        integration_type=None,
        priority=5,
        required=False,
        example_answers=[
            "'merchant' = seller on our platform, 'take rate' = our commission percentage",
            "'activation' means a user completes their first transaction",
            "we call our customers 'members', not 'users'",
            "nothing special, standard e-commerce terms",
        ],
    ),
]


# ============================================
# WAREHOUSE QUESTIONS (business context only)
# ============================================

BIGQUERY_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="bq_critical_datasets",
        text="Which BigQuery datasets or tables are most business-critical? Which ones would cause the biggest problem if they went stale or had bad data?",
        category=QuestionCategory.CRITICALITY,
        integration_type="BIGQUERY",
        priority=8,
        required=False,
        example_answers=[
            "analytics.orders and analytics.revenue — executive dashboards read from these",
            "the customer_360 table — our product depends on it",
            "everything in the reporting dataset — that's what clients see",
        ],
    ),
]

SNOWFLAKE_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="sf_critical_datasets",
        text="Which Snowflake databases or schemas are most business-critical? Which ones would cause the biggest problem if they went stale?",
        category=QuestionCategory.CRITICALITY,
        integration_type="SNOWFLAKE",
        priority=8,
        required=False,
        example_answers=[
            "ANALYTICS.CORE — powers all Looker dashboards",
            "REPORTING database — client-facing",
            "the FINANCE schema — month-end close depends on it",
        ],
    ),
]


# ============================================
# TRANSFORMATION QUESTIONS (business context)
# ============================================

DBT_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="dbt_important_models",
        text="Which dbt models are the most important to your business? The ones stakeholders actually care about?",
        category=QuestionCategory.CRITICALITY,
        integration_type="DBT_CORE",
        priority=8,
        required=False,
        example_answers=[
            "fct_orders and dim_customers — everything downstream depends on these",
            "the mart models — finance_summary, marketing_attribution",
            "anything in the reporting/ folder",
        ],
    ),
]


# ============================================
# ORCHESTRATION QUESTIONS (business context)
# ============================================

AIRFLOW_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="airflow_critical_dags",
        text="Which Airflow DAGs are the most business-critical? Are there any with strict deadlines (e.g., must finish by 9am)?",
        category=QuestionCategory.CRITICALITY,
        integration_type="AIRFLOW",
        priority=8,
        required=False,
        example_answers=[
            "daily_etl must finish by 8am — finance team starts their day then",
            "the hourly_metrics DAG — product dashboard goes stale if it fails",
            "none have hard deadlines, but the nightly refresh should be done by morning",
        ],
    ),
]

DAGSTER_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="dagster_critical_jobs",
        text="Which Dagster jobs or asset groups are most business-critical? Any strict timing requirements?",
        category=QuestionCategory.CRITICALITY,
        integration_type="DAGSTER",
        priority=8,
        required=False,
        example_answers=[
            "the reporting_assets group — client dashboards depend on it by 9am",
            "the ML feature pipeline — model retraining fails without it",
        ],
    ),
]


# ============================================
# INGESTION QUESTIONS (business context)
# ============================================

FIVETRAN_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="fivetran_critical_sources",
        text="Which Fivetran connectors/sources are most critical to your business? Which ones would you want to know about immediately if they stopped syncing?",
        category=QuestionCategory.CRITICALITY,
        integration_type="FIVETRAN",
        priority=8,
        required=False,
        example_answers=[
            "Stripe and Shopify — revenue data stops flowing",
            "Salesforce — sales team can't see pipeline metrics",
            "all of them honestly, but HubSpot is the most fragile",
        ],
    ),
]


# ============================================
# VERSION CONTROL QUESTIONS (business context)
# ============================================

GITHUB_QUESTIONS: List[OnboardingQuestion] = [
    OnboardingQuestion(
        key="github_change_process",
        text="How do data pipeline changes typically get made? (e.g., analyst opens PR, engineer reviews, auto-deploys on merge?)",
        category=QuestionCategory.WORKFLOW,
        integration_type="GITHUB",
        priority=7,
        required=False,
        example_answers=[
            "analyst writes SQL, engineer reviews, merges to main, auto-deploys",
            "I push directly to main — no review process yet",
            "PR required, CI runs dbt test, then manual deploy",
        ],
    ),
]


# ============================================
# QUESTION LOOKUP FUNCTIONS
# ============================================

INTEGRATION_QUESTIONS: Dict[str, List[OnboardingQuestion]] = {
    "DBT_CORE": DBT_QUESTIONS,
    "DBT_CLOUD": DBT_QUESTIONS,
    "BIGQUERY": BIGQUERY_QUESTIONS,
    "SNOWFLAKE": SNOWFLAKE_QUESTIONS,
    "AIRFLOW": AIRFLOW_QUESTIONS,
    "FIVETRAN": FIVETRAN_QUESTIONS,
    "GITHUB": GITHUB_QUESTIONS,
    "DAGSTER": DAGSTER_QUESTIONS,
    "PREFECT": DAGSTER_QUESTIONS,
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

    return sorted(all_questions, key=lambda q: -q.priority)


def get_question_by_key(key: str) -> Optional[OnboardingQuestion]:
    """Get a question by its key."""
    for q in GENERAL_QUESTIONS:
        if q.key == key:
            return q

    for questions in INTEGRATION_QUESTIONS.values():
        for q in questions:
            if q.key == key:
                return q

    return None
