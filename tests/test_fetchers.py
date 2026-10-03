"""
Unit and Mock Tests for Data Fetchers.

Ensures complete error isolation and graceful degradation across all external APIs.
"""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from fetchers.base import (
    BaseFetcher,
    CryptoPrice,
    FinanceSummary,
    FXRate,
    PaperItem,
    RepoItem,
    TechStory,
)
from fetchers.finance import CoinGeckoFetcher, FinanceAggregator, FrankfurterFetcher
from fetchers.github import AIAggregator, GitHubFetcher, HuggingFaceFetcher
from fetchers.tech import (
    HackerNewsFetcher,
    LobstersFetcher,
    TechAggregator,
    TechCrunchFetcher,
)
from fetchers import collect_all_data


# ------------------------------------------------------------------------------
# 1. Tech Fetchers Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hacker_news_fetcher_success(monkeypatch):
    """Test successful Hacker News Algolia API response."""
    mock_payload = {
        "hits": [
            {
                "title": "Show HN: Modern AI Framework",
                "url": "https://example.com/show-hn",
                "points": 250,
                "num_comments": 85,
                "author": "techfounder",
                "objectID": "123456",
                "created_at": "2026-10-02T10:00:00Z",
            }
        ]
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload
    mock_resp.raise_for_status = MagicMock()

    async def mock_get(*args, **kwargs):
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = HackerNewsFetcher(timeout=5.0)
        stories = await fetcher.fetch()

        assert len(stories) == 1
        assert stories[0].title == "Show HN: Modern AI Framework"
        assert stories[0].score == 250
        assert stories[0].comments == 85
        assert stories[0].source == "Hacker News"


@pytest.mark.asyncio
async def test_hacker_news_fetcher_error_isolation():
    """Verify HackerNews safe_fetch returns empty list upon network exception."""
    async def mock_error(*args, **kwargs):
        raise httpx.ConnectError("Connection refused by test mock")

    with patch.object(httpx.AsyncClient, "get", new=mock_error):
        fetcher = HackerNewsFetcher(timeout=5.0)
        stories = await fetcher.safe_fetch(default_factory=list)
        assert stories == []


@pytest.mark.asyncio
async def test_lobsters_fetcher_success():
    """Test successful Lobsters API response."""
    mock_payload = [
        {
            "title": "Rust vs C++: Systems in 2026",
            "url": "https://lobste.rs/s/xyz123",
            "score": 42,
            "comment_count": 18,
            "submitter_user": {"username": "rustacean"},
            "created_at": "2026-10-02T08:00:00Z",
        }
    ]

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload
    mock_resp.raise_for_status = MagicMock()

    async def mock_get(*args, **kwargs):
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = LobstersFetcher(timeout=5.0)
        stories = await fetcher.fetch()

        assert len(stories) == 1
        assert stories[0].title == "Rust vs C++: Systems in 2026"
        assert stories[0].author == "rustacean"
        assert stories[0].score == 42


@pytest.mark.asyncio
async def test_techcrunch_rss_fetcher_success():
    """Test TechCrunch RSS feed XML parsing and HTML sanitization."""
    mock_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <channel>
        <title>TechCrunch</title>
        <item>
          <title>Startup Raises $50M Series B for Autonomous Robotics</title>
          <link>https://techcrunch.com/2026/10/02/robotics-series-b/</link>
          <description>&lt;p&gt;A promising robotics venture has closed its round.&lt;/p&gt;</description>
          <pubDate>Fri, 02 Oct 2026 09:30:00 +0000</pubDate>
          <dc:creator>Jane Doe</dc:creator>
        </item>
      </channel>
    </rss>"""

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.content = mock_xml
    mock_resp.raise_for_status = MagicMock()

    async def mock_get(*args, **kwargs):
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = TechCrunchFetcher(timeout=5.0)
        stories = await fetcher.fetch()

        assert len(stories) == 1
        assert "Autonomous Robotics" in stories[0].title
        assert stories[0].author == "Jane Doe"
        assert "<p>" not in stories[0].summary


# ------------------------------------------------------------------------------
# 2. GitHub & Hugging Face Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_github_fetcher_rate_limit_graceful():
    """Test that GitHub API 403 rate limit returns empty list without raising exception."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 403

    async def mock_get(*args, **kwargs):
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = GitHubFetcher(timeout=5.0)
        repos = await fetcher.fetch()
        assert repos == []


@pytest.mark.asyncio
async def test_github_fetcher_success():
    """Test successful GitHub repository parsing."""
    mock_payload = {
        "items": [
            {
                "name": "autonomous-agent",
                "full_name": "ai-labs/autonomous-agent",
                "html_url": "https://github.com/ai-labs/autonomous-agent",
                "description": "High performance agent runtime",
                "stargazers_count": 8500,
                "forks_count": 420,
                "language": "Python",
                "topics": ["ai", "agents", "llm"],
            }
        ]
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload
    mock_resp.raise_for_status = MagicMock()

    async def mock_get(*args, **kwargs):
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = GitHubFetcher(timeout=5.0)
        repos = await fetcher.fetch()

        assert len(repos) == 1
        assert repos[0].name == "autonomous-agent"
        assert repos[0].stars == 8500


@pytest.mark.asyncio
async def test_huggingface_fetcher_success():
    """Test Hugging Face daily papers extraction."""
    mock_papers_payload = [
        {
            "paper": {
                "id": "2610.12345",
                "title": "Scaling Laws for Reasoning Models",
                "summary": "We investigate parameter efficiency in post-training reasoning models.",
                "upvotes": 45,
                "publishedAt": "2026-10-01T12:00:00Z",
                "authors": [{"name": "Dr. Turing"}],
            }
        }
    ]

    async def mock_get(self_client, url, *args, **kwargs):
        mock_resp = MagicMock(spec=httpx.Response)
        if "daily_papers" in str(url):
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_papers_payload
        else:
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = HuggingFaceFetcher(timeout=5.0)
        papers = await fetcher.fetch()

        assert len(papers) == 1
        assert "Scaling Laws" in papers[0].title
        assert papers[0].upvotes == 45
        assert "2610.12345" in papers[0].url


# ------------------------------------------------------------------------------
# 3. Finance Fetchers Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_frankfurter_fetcher_success():
    """Test Frankfurter currency rate fetching."""
    async def mock_get(self_client, url, *args, **kwargs):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        if "from=USD" in str(url):
            mock_resp.json.return_value = {"base": "USD", "rates": {"TRY": 49.25}, "date": "2026-10-02"}
        else:
            mock_resp.json.return_value = {"base": "EUR", "rates": {"TRY": 55.40}, "date": "2026-10-02"}
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = FrankfurterFetcher(timeout=5.0)
        rates = await fetcher.fetch()

        assert len(rates) == 2
        usd_rate = next(r for r in rates if r.base_currency == "USD")
        assert usd_rate.rate == 49.25


@pytest.mark.asyncio
async def test_coingecko_fetcher_rate_limit_graceful():
    """Verify CoinGecko 429 returns empty list safely."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 429

    async def mock_get(*args, **kwargs):
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = CoinGeckoFetcher(timeout=5.0)
        prices = await fetcher.fetch()
        assert prices == []


@pytest.mark.asyncio
async def test_coingecko_fetcher_success():
    """Test CoinGecko BTC and ETH price parsing."""
    mock_payload = {
        "bitcoin": {"usd": 86500.0, "usd_24h_change": 2.75},
        "ethereum": {"usd": 2750.0, "usd_24h_change": -1.20},
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload
    mock_resp.raise_for_status = MagicMock()

    async def mock_get(*args, **kwargs):
        return mock_resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        fetcher = CoinGeckoFetcher(timeout=5.0)
        prices = await fetcher.fetch()

        assert len(prices) == 2
        btc = next(p for p in prices if p.symbol == "BTC")
        assert btc.price_usd == 86500.0
        assert btc.change_24h == 2.75


# ------------------------------------------------------------------------------
# 4. Aggregators & collect_all_data
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collect_all_data_integration():
    """Verify collect_all_data coordinates all fetchers into AggregatedRawData."""
    with patch.object(TechAggregator, "fetch_all", new_callable=AsyncMock) as mock_tech, \
         patch.object(AIAggregator, "fetch_all", new_callable=AsyncMock) as mock_ai, \
         patch.object(FinanceAggregator, "fetch_all", new_callable=AsyncMock) as mock_fin:

        mock_tech.return_value = [
            TechStory(title="Headline A", url="https://a.com", source="Hacker News", score=100)
        ]
        mock_ai.return_value = (
            [RepoItem(name="repo-1", full_name="user/repo-1", html_url="https://github.com/user/repo-1")],
            [PaperItem(title="paper-1", summary="summary", url="https://hf.co/paper-1")],
        )
        mock_fin.return_value = FinanceSummary(
            fx_rates=[FXRate(base_currency="USD", target_currency="TRY", rate=49.0)],
            crypto_prices=[CryptoPrice(symbol="BTC", name="Bitcoin", price_usd=86000.0)],
        )

        data = await collect_all_data(timeout=5.0)

        assert len(data.tech_stories) == 1
        assert len(data.repositories) == 1
        assert len(data.papers) == 1
        assert len(data.finance.fx_rates) == 1
        assert len(data.finance.crypto_prices) == 1
