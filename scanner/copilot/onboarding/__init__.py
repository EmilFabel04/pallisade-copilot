"""
Copilot Onboarding System

Handles the onboarding flow where the LLM learns about the user's
data pipeline setup to avoid mid-task clarifying questions.
"""

from .questions import (
    GENERAL_QUESTIONS,
    DBT_QUESTIONS,
    BIGQUERY_QUESTIONS,
    SNOWFLAKE_QUESTIONS,
    AIRFLOW_QUESTIONS,
    FIVETRAN_QUESTIONS,
    get_questions_for_integration,
    get_all_pending_questions,
    get_question_by_key,
    QuestionCategory,
)

__all__ = [
    "GENERAL_QUESTIONS",
    "DBT_QUESTIONS",
    "BIGQUERY_QUESTIONS",
    "SNOWFLAKE_QUESTIONS",
    "AIRFLOW_QUESTIONS",
    "FIVETRAN_QUESTIONS",
    "get_questions_for_integration",
    "get_all_pending_questions",
    "get_question_by_key",
    "QuestionCategory",
]
