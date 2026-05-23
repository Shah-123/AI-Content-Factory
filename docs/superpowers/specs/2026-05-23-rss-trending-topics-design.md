# Design Spec: Live RSS Feed Aggregator for Trending Topics

## Goal
Replace the Tavily search dependency with a free, stable, real-time RSS Feed aggregator to suggest trending blog topics.

## Proposed Changes

### Backend

#### [MODIFY] [trending.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/trending.py)
- Replace `_fetch_headlines()` with `_fetch_rss_headlines()`.
- Use Python's standard `xml.etree.ElementTree` parser and the `requests` library to fetch and parse headlines from the following RSS feeds:
  - **Tech:** Hacker News Top Stories (`https://news.ycombinator.com/rss`)
  - **Business:** BBC News Business (`http://feeds.bbci.co.uk/news/business/rss.xml`)
  - **Science & Health:** BBC News Science & Environment (`http://feeds.bbci.co.uk/news/science_and_environment/rss.xml`)
  - **World & Culture:** BBC News World (`http://feeds.bbci.co.uk/news/world/rss.xml`)
- Parse up to 4 items per feed, fetching titles and using the feed category as the source.
- Update `get_trending_topics()` to pass these RSS headlines as the grounding context to the LLM.

## Verification Plan

### Manual Verification
1. Run backend server (`uvicorn main:app --reload` or equivalent).
2. Hit the endpoint `GET /api/trending?force=true`.
3. Verify that RSS feeds are queried, parsed, and used by the LLM to generate exactly 6 structured trending topic suggestions.
4. Verify fallback behavior by blocklisting/disabling internet access or inputting bad feed URLs, checking that the system falls back gracefully to hardcoded fallback topics.
