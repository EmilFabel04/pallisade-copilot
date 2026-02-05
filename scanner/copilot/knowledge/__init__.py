"""
Pallisade Co-Pilot Knowledge Base

Curated knowledge about data pipeline tools — troubleshooting, best practices,
comparisons, and how-to guides. Uses TF-IDF search for fast, local retrieval.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set
from enum import Enum

logger = logging.getLogger(__name__)


class KnowledgeCategory(Enum):
    TROUBLESHOOTING = "troubleshooting"
    BEST_PRACTICES = "best_practices"
    COMPARISON = "comparison"
    HOW_TO = "how_to"
    ARCHITECTURE = "architecture"
    MIGRATION = "migration"


@dataclass
class KnowledgeArticle:
    """A single knowledge article."""
    id: str
    title: str
    category: KnowledgeCategory
    tags: List[str]
    tools: List[str]  # e.g. ["DBT_CLOUD", "DBT_CORE"]
    content: str
    summary: str
    related_articles: List[str] = field(default_factory=list)

    @property
    def searchable_text(self) -> str:
        """Combined text for TF-IDF indexing."""
        return f"{self.title} {self.summary} {' '.join(self.tags)} {self.content}"


class KnowledgeBase:
    """
    TF-IDF powered knowledge base for data pipeline expertise.

    Loads all articles at startup and builds a search index.
    Corpus is small (< 200 articles), so cosine similarity is instant.
    """

    def __init__(self):
        self._articles: Dict[str, KnowledgeArticle] = {}
        self._vectorizer = None  # TfidfVectorizer (lazy import)
        self._tfidf_matrix = None
        self._article_ids: List[str] = []
        self._loaded = False

    def load(self):
        """Load all articles and build search index."""
        if self._loaded:
            return

        from .articles import (
            dbt, snowflake, bigquery, postgres,
            airflow, dagster, prefect,
            fivetran, airbyte, kafka,
            looker, general, comparisons,
        )

        all_article_lists = [
            dbt.DBT_ARTICLES,
            snowflake.SNOWFLAKE_ARTICLES,
            bigquery.BIGQUERY_ARTICLES,
            postgres.POSTGRES_ARTICLES,
            airflow.AIRFLOW_ARTICLES,
            dagster.DAGSTER_ARTICLES,
            prefect.PREFECT_ARTICLES,
            fivetran.FIVETRAN_ARTICLES,
            airbyte.AIRBYTE_ARTICLES,
            kafka.KAFKA_ARTICLES,
            looker.LOOKER_ARTICLES,
            general.GENERAL_ARTICLES,
            comparisons.COMPARISON_ARTICLES,
        ]

        for article_list in all_article_lists:
            for article in article_list:
                self._articles[article.id] = article

        # Build TF-IDF index
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._article_ids = list(self._articles.keys())
        corpus = [self._articles[aid].searchable_text for aid in self._article_ids]

        self._vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words="english",
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(corpus)
        self._loaded = True

        logger.info(
            f"Knowledge base loaded: {len(self._articles)} articles, "
            f"{self._tfidf_matrix.shape[1]} features"
        )

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.05,
        tool_filter: Optional[List[str]] = None,
        category_filter: Optional[KnowledgeCategory] = None,
    ) -> List[Dict[str, Any]]:
        """Search the knowledge base by query."""
        if not self._loaded:
            self.load()

        from sklearn.metrics.pairwise import cosine_similarity

        query_vec = self._vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        results = []
        for idx, score in enumerate(similarities):
            if score < min_score:
                continue

            article = self._articles[self._article_ids[idx]]

            if tool_filter:
                upper_filter = {t.upper() for t in tool_filter}
                if not any(t.upper() in upper_filter for t in article.tools):
                    continue

            if category_filter and article.category != category_filter:
                continue

            results.append({
                "article_id": article.id,
                "title": article.title,
                "category": article.category.value,
                "tags": article.tags,
                "tools": article.tools,
                "summary": article.summary,
                "content": article.content,
                "score": round(float(score), 4),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_article(self, article_id: str) -> Optional[KnowledgeArticle]:
        """Get a specific article by ID."""
        if not self._loaded:
            self.load()
        return self._articles.get(article_id)

    def get_context_hints(
        self,
        query: str,
        user_tools: Set[str],
    ) -> Optional[str]:
        """
        Get a lightweight context hint for the system prompt.

        Returns a short string (< 100 tokens) if the query matches
        knowledge topics, or None if no relevant match.
        """
        if not self._loaded:
            self.load()

        results = self.search(query, top_k=3, min_score=0.10)
        if not results:
            return None

        lines = [
            "\n## Relevant Knowledge Available",
            "The knowledge base has articles relevant to this question. "
            "Use `search_knowledge_base` to get detailed guidance:",
        ]
        for r in results[:3]:
            lines.append(f"- **{r['title']}**: {r['summary']}")

        return "\n".join(lines)


# Global singleton
_knowledge_base: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """Get the global knowledge base instance (lazy loaded)."""
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = KnowledgeBase()
        _knowledge_base.load()
    return _knowledge_base
