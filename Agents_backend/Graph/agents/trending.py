"""
trending.py — Real-Time Trending Topics Suggester
===================================================
Fetches fresh headlines from Tavily across Tech, Business, and Science/Culture
domains, then uses the LLM to reformulate them into compelling blog topic ideas.

Each topic is returned as a rich object:
  { title, category, tone_hint, why_trending }

Exposed via `GET /api/trending` so the frontend can render quick-pick
chips when no job has been created yet.
"""

from __future__ import annotations

import os
from datetime import date
from typing import List, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from Graph.templates import TRENDING_TOPICS_SYSTEM
from .utils import logger, llm_fast


# ── Pydantic output schema ────────────────────────────────────────────────────

class TrendingTopic(BaseModel):
    """A single grounded trending blog topic."""
    title: str = Field(description="Blog-ready topic title, under 10 words")
    category: str = Field(
        description='One of: "Tech", "Business", "Science", "Culture", "Health"'
    )
    tone_hint: str = Field(
        description="Ideal tone: professional | conversational | technical | educational | persuasive"
    )
    why_trending: str = Field(
        description="One sentence (≤12 words) explaining why this is hot right now"
    )


class TrendingTopicsResponse(BaseModel):
    """Root output schema — 6 grounded topic objects."""
    topics: List[TrendingTopic] = Field(
        description="Exactly 6 trending blog topic suggestions derived from real headlines"
    )


# ── RSS Feeds and Fetching ───────────────────────────────────────────────────

_RSS_FEEDS = {
    "Tech": "https://news.ycombinator.com/rss",
    "Business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "Science & Health": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "World & Culture": "http://feeds.bbci.co.uk/news/world/rss.xml",
}


def _fetch_rss_headlines() -> str:
    """
    Fetches XML RSS feeds from top categories and extracts titles.
    Returns a formatted string of recent headlines.
    Falls back gracefully to an empty string on network failure or XML malformation.
    """
    import requests
    import xml.etree.ElementTree as ET

    headlines: List[str] = []
    for feed_name, url in _RSS_FEEDS.items():
        try:
            response = requests.get(url, timeout=5.0)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                items = root.findall(".//item")
                count = 0
                for item in items:
                    title_elem = item.find("title")
                    if title_elem is not None and title_elem.text:
                        title_text = title_elem.text.strip()
                        if title_text:
                            headlines.append(f"- {title_text} ({feed_name})")
                            count += 1
                            if count >= 4:  # Max 4 items per feed
                                break
        except Exception as exc:
            logger.warning(f"RSS fetch failed for '{feed_name}' feed: {exc}")

    if not headlines:
        return ""

    return "RECENT HEADLINES:\n" + "\n".join(headlines[:16])


# ── Main function ─────────────────────────────────────────────────────────────

def get_trending_topics() -> List[dict]:
    """
    Returns up to 6 Tavily-grounded trending blog topic objects.

    Each object: { title, category, tone_hint, why_trending }

    Falls back gracefully:
      - If Tavily unavailable → LLM generates without grounding context.
      - If LLM fails → hardcoded fallback list.
    """
    fallback = [
        {"title": "AI Agents Reshaping Knowledge Work", "category": "Tech",
         "tone_hint": "professional", "why_trending": "Agentic AI is transforming how professionals research and write."},
        {"title": "The Quiet Rise of Edge Computing", "category": "Tech",
         "tone_hint": "technical", "why_trending": "Latency demands are pushing compute to the network edge."},
        {"title": "Why Central Banks Fear Stablecoins", "category": "Business",
         "tone_hint": "professional", "why_trending": "Stablecoin regulation is now a G20 priority."},
        {"title": "CRISPR Gene Editing Goes Clinical", "category": "Science",
         "tone_hint": "educational", "why_trending": "First approved CRISPR therapies reached patients in 2025."},
        {"title": "Mental Health Apps Under the Microscope", "category": "Health",
         "tone_hint": "conversational", "why_trending": "FDA scrutiny of wellness apps intensified this year."},
        {"title": "Open-Source LLMs Challenge Big Tech", "category": "Tech",
         "tone_hint": "persuasive", "why_trending": "Meta and Mistral models now rival GPT-4 on benchmarks."},
    ]

    try:
        # Step 1: fetch real headlines from RSS feeds
        headline_context = _fetch_rss_headlines()
        today = date.today().isoformat()

        human_content = f"Today: {today}.\n\n{headline_context}\n\nGenerate 6 trending blog topics."

        # Step 2: LLM reformulates headlines → structured topics
        suggester = llm_fast.with_structured_output(TrendingTopicsResponse)
        result: TrendingTopicsResponse = suggester.invoke([
            SystemMessage(content=TRENDING_TOPICS_SYSTEM),
            HumanMessage(content=human_content),
        ])

        topics = result.topics or []

        # Ensure exactly 6 (pad from fallback if LLM under-delivered)
        if len(topics) < 6:
            pad_count = 6 - len(topics)
            logger.warning(f"LLM returned {len(topics)} topics — padding {pad_count} from fallback.")
            for fb_topic in fallback[len(topics):len(topics) + pad_count]:
                topics.append(TrendingTopic(**fb_topic))

        return [t.model_dump() for t in topics[:6]]

    except Exception as exc:
        logger.warning(f"Trending topics generation failed: {exc}. Using fallback.")
        return fallback
