"""
trending.py — Trending Topics Suggester
========================================
Standalone helper (not a graph node) that returns 4 fresh blog-topic
ideas for the empty-state dashboard. Uses the existing fast LLM and
the `TRENDING_TOPICS_SYSTEM` prompt that was previously dead.

Exposed via `GET /api/trending` so the frontend can render quick-pick
chips when no job has been created yet.
"""

from datetime import date
from typing import List
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from Graph.templates import TRENDING_TOPICS_SYSTEM
from .utils import logger, llm_fast


class TrendingTopics(BaseModel):
    """Output schema — exactly 4 short topic strings."""
    topics: List[str] = Field(
        description="Exactly 4 trending blog topic ideas, each under 8 words"
    )


def get_trending_topics() -> List[str]:
    """
    Returns 4 trending blog-topic suggestions.

    Falls back to a hardcoded list on LLM failure so the frontend
    never sees an empty dashboard.
    """
    fallback = [
        "AI agents in 2026",
        "Building scalable RAG systems",
        "Multi-modal LLMs explained",
        "The future of voice AI",
    ]

    try:
        suggester = llm_fast.with_structured_output(TrendingTopics)
        today = date.today().isoformat()
        result: TrendingTopics = suggester.invoke([
            SystemMessage(content=TRENDING_TOPICS_SYSTEM),
            HumanMessage(content=f"Today's date: {today}. Suggest 4 trending blog topics."),
        ])

        # Clamp to exactly 4 entries, strip whitespace, drop empties
        topics = [t.strip() for t in (result.topics or []) if t and t.strip()][:4]
        if len(topics) < 4:
            # Pad from fallback if the LLM under-delivered
            topics.extend(fallback[len(topics):])
        return topics

    except Exception as e:
        logger.warning(f"Trending topics LLM call failed: {e}. Using fallback.")
        return fallback
