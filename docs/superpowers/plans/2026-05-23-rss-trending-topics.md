# Live RSS Feed Aggregator for Trending Topics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Tavily-based search for trending topics with a free, stable, real-time RSS Feed aggregator to suggest trending blog topics.

**Architecture:** Fetch XML content from four public RSS news feeds (Tech, Business, Science, World) with strict timeouts, parse them using Python's standard `xml.etree.ElementTree`, and feed the resulting headlines to the LangChain LLM to generate exactly six categorized, blog-ready topic suggestions. Provide graceful fallback handling.

**Tech Stack:** Python 3.12, `requests`, `xml.etree.ElementTree`, `pytest`, `unittest.mock`.

---

### Task 1: Create Unit Tests for RSS Fetching and Topic Generation

**Files:**
- Create: `Agents_backend/tests/test_trending.py`

- [ ] **Step 1: Write unit tests for RSS fetching and trending topics**
  Write tests covering:
  1. Successful parsing of RSS XML content from mocked HTTP requests.
  2. Graceful exception handling returning an empty string when network calls fail or return malformed XML.
  3. Integration within `get_trending_topics()` to verify the LLM is called with parsed headlines and returns structured trending topics.
  4. Graceful degradation where a total failure returns the hardcoded fallback topics.

  Create `Agents_backend/tests/test_trending.py` with the following content:
  ```python
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
          assert "Hacker News" in headlines or "BBC" in headlines or "Tech" in headlines

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
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `virtual_env\Scripts\python.exe -m pytest Agents_backend/tests/test_trending.py`
  Expected: FAIL (with ImportError or ModuleNotFoundError since functions/variables do not exist yet).

---

### Task 2: Implement RSS Fetching and update Trending Agent

**Files:**
- Modify: `Agents_backend/Graph/agents/trending.py`

- [ ] **Step 1: Replace Tavily search with RSS Feed parser**
  Update the imports to include `xml.etree.ElementTree` and delete the Tavily imports/queries if no longer used.
  Add `_RSS_FEEDS` definition:
  ```python
  _RSS_FEEDS = {
      "Tech": "https://news.ycombinator.com/rss",
      "Business": "http://feeds.bbci.co.uk/news/business/rss.xml",
      "Science & Health": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
      "World & Culture": "http://feeds.bbci.co.uk/news/world/rss.xml",
  }
  ```

  Implement the new helper function `_fetch_rss_headlines() -> str`:
  ```python
  def _fetch_rss_headlines() -> str:
      """
      Fetches XML RSS feeds from top categories and extracts titles.
      Returns a formatted string of recent headlines.
      Falls back gracefully to an empty string on network failure.
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
                          # Simple sanitization of CDATA or extra characters
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
  ```

  Modify `get_trending_topics()` to use `_fetch_rss_headlines()`:
  - Replace `headline_context = _fetch_headlines()` with `headline_context = _fetch_rss_headlines()`.
  - Ensure the fallback padding and exception catching works exactly as before.

- [ ] **Step 2: Run unit tests to verify they pass**
  Run: `virtual_env\Scripts\python.exe -m pytest Agents_backend/tests/test_trending.py`
  Expected: PASS

- [ ] **Step 3: Run all unit tests to verify no regressions**
  Run: `virtual_env\Scripts\python.exe -m pytest Agents_backend/tests`
  Expected: PASS (All 85 passed)

- [ ] **Step 4: Commit changes**
  Run:
  ```bash
  git add Agents_backend/tests/test_trending.py Agents_backend/Graph/agents/trending.py docs/superpowers/plans/2026-05-23-rss-trending-topics.md docs/superpowers/specs/2026-05-23-rss-trending-topics-design.md
  git commit -m "feat: replace Tavily-based trending topics with a live RSS Feed aggregator"
  ```
