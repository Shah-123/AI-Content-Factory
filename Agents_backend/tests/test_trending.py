import pytest
from unittest.mock import patch, MagicMock
import xml.etree.ElementTree as ET

from Graph.agents.trending import _fetch_rss_headlines, get_trending_topics, TrendingTopic, TrendingTopicsResponse

# Sample XML matching standard RSS format
MOCK_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Mock RSS Feed</title>
    <link>http://example.com</link>
    <item>
      <title>AI Agents Reshaping Tech Industry</title>
      <link>http://example.com/ai-agents</link>
    </item>
    <item>
      <title>New Economy Shifts Under Inflation</title>
      <link>http://example.com/economy-inflation</link>
    </item>
  </channel>
</rss>
"""

class TestTrendingRSS:
    @patch("requests.get")
    def test_fetch_rss_headlines_success(self, mock_get):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = MOCK_RSS_XML.encode("utf-8")
        mock_get.return_value = mock_response

        headlines = _fetch_rss_headlines()
        assert "AI Agents Reshaping Tech Industry" in headlines
        assert "New Economy Shifts Under Inflation" in headlines

    @patch("requests.get")
    def test_fetch_rss_headlines_failure(self, mock_get):
        # Simulate request error
        mock_get.side_effect = Exception("Connection timed out")
        
        headlines = _fetch_rss_headlines()
        assert headlines == ""

    @patch("requests.get")
    def test_fetch_rss_headlines_malformed_xml(self, mock_get):
        # Setup mock response with bad xml
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<invalid><xml>"
        mock_get.return_value = mock_response

        headlines = _fetch_rss_headlines()
        assert headlines == ""

    @patch("Graph.agents.trending._fetch_rss_headlines")
    @patch("Graph.agents.trending.llm_fast")
    def test_get_trending_topics_success(self, mock_llm, mock_fetch):
        mock_fetch.return_value = "RECENT RSS HEADLINES:\n- AI Agents Reshaping Tech Industry (Tech)"
        
        # Setup mock structured output
        mock_suggester = MagicMock()
        mock_response_obj = TrendingTopicsResponse(topics=[
            TrendingTopic(
                title="AI Agents in Action",
                category="Tech",
                tone_hint="professional",
                why_trending="AI agents are taking over software tasks."
            )
        ] * 6)
        mock_suggester.invoke.return_value = mock_response_obj
        mock_llm.with_structured_output.return_value = mock_suggester

        topics = get_trending_topics()
        assert len(topics) == 6
        assert topics[0]["title"] == "AI Agents in Action"
        assert topics[0]["category"] == "Tech"

    @patch("Graph.agents.trending._fetch_rss_headlines")
    def test_get_trending_topics_fallback(self, mock_fetch):
        # If fetch or LLM fails, we fall back to hardcoded topics
        mock_fetch.side_effect = Exception("System breakdown")
        topics = get_trending_topics()
        assert len(topics) == 6
        assert topics[0]["title"] == "AI Agents Reshaping Knowledge Work"
