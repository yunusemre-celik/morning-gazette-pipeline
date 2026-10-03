"""
Unit and Mock Tests for Summarizer and Schema Validation.

Tests Pydantic models, Gemini API structured outputs, exponential backoff retries,
and the emergency FallbackSummarizer.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError
from google.genai.errors import APIError

from config import Settings
from fetchers.base import (
    AggregatedRawData,
    CryptoPrice,
    FinanceSummary,
    FXRate,
    PaperItem,
    RepoItem,
    TechStory,
)
from processors.schema import (
    AIToolModel,
    GazetteContent,
    HeadlineStory,
    MarketInsight,
    TechStartupArticle,
)
from processors.summarizer import (
    FallbackSummarizer,
    GeminiSummarizer,
    format_turkish_date,
)


# ------------------------------------------------------------------------------
# 1. Pydantic Schema Validation Tests
# ------------------------------------------------------------------------------

def test_pydantic_schema_valid_construction():
    """Verify GazetteContent can be constructed and validated with correct types."""
    headline = HeadlineStory(
        kicker="YAPAY ZEKA DEVRİMİ",
        title="Otonom Sistemler Endüstriyi Dönüştürüyor",
        lead_paragraph="Günün en kritik gelişmesi yeni otonom yazılım mimarilerinin duyurulması oldu.",
        detailed_analysis="Uzmanlar bu atılımın operasyonel maliyetleri yüzde 70 düşüreceğini öngörüyor.",
        source_name="TechCrunch",
        source_url="https://techcrunch.com/sample",
    )

    article = TechStartupArticle(
        category="GİRİŞİM",
        title="Erken Aşama Girişim 10M Dolar Yatırım Aldı",
        summary="Fintech girişimi yeni tohum turunu başarıyla tamamladı.",
        key_takeaway="Girişim sermayesi B2B dikeyine odaklanıyor.",
        source_name="Hacker News",
        source_url="https://news.ycombinator.com",
    )

    tool = AIToolModel(
        name="FastLLM-Core",
        category="Açık Kaynak Araç",
        description="CPU üzerinde düşük gecikmeli çıkarım kütüphanesi.",
        why_it_matters="Yerel modelleri sunucu maliyeti olmadan koşturmayı sağlıyor.",
        source_url="https://github.com/sample/fastllm",
    )

    market = MarketInsight(
        market_summary="Piyasalar haftayı pozitif kapattı.",
        fx_commentary="Dolar/TL yatay seyrediyor.",
        crypto_commentary="Bitcoin 85 bin dolar üzerinde tutunuyor.",
        editorial_take="Döviz pozisyonlarını korumak önem taşıyor.",
    )

    content = GazetteContent(
        edition_date="2 Ekim 2026, Cuma",
        edition_number="No. 100",
        headline=headline,
        tech_startup_stories=[article],
        ai_tools=[tool],
        market_insight=market,
    )

    assert content.headline.title == "Otonom Sistemler Endüstriyi Dönüştürüyor"
    assert len(content.tech_startup_stories) == 1
    assert len(content.ai_tools) == 1
    assert content.market_insight.editorial_take.startswith("Döviz")


def test_pydantic_schema_missing_fields_raises_validation_error():
    """Verify validation error when required fields are missing."""
    with pytest.raises(ValidationError):
        # Missing title, lead_paragraph, detailed_analysis, source_name, source_url
        HeadlineStory()


# ------------------------------------------------------------------------------
# 2. FallbackSummarizer Tests
# ------------------------------------------------------------------------------

def test_fallback_summarizer_with_rich_data():
    """Verify FallbackSummarizer generates valid GazetteContent from raw data without LLM."""
    raw_data = AggregatedRawData(
        tech_stories=[
            TechStory(title="Top Headline Story", url="https://hn.com/1", source="Hacker News", score=500, comments=120),
            TechStory(title="Secondary Story", url="https://tc.com/2", source="TechCrunch", score=50),
        ],
        repositories=[
            RepoItem(name="super-agent", full_name="user/super-agent", html_url="https://github.com/user/super-agent", stars=1200),
        ],
        papers=[
            PaperItem(title="Attention in 2026", summary="Novel attention mechanism", url="https://hf.co/papers/123", upvotes=80),
        ],
        finance=FinanceSummary(
            fx_rates=[FXRate(base_currency="USD", target_currency="TRY", rate=49.0)],
            crypto_prices=[CryptoPrice(symbol="BTC", name="Bitcoin", price_usd=86000.0, change_24h=3.5)],
        ),
    )

    content = FallbackSummarizer.synthesize(raw_data)

    assert isinstance(content, GazetteContent)
    assert content.headline.title == "Top Headline Story"
    assert content.headline.source_name == "Hacker News"
    assert len(content.tech_startup_stories) >= 1
    assert len(content.ai_tools) >= 2
    assert "49.00" in content.market_insight.fx_commentary or "Dolar/TL" in content.market_insight.fx_commentary
    assert content.raw_finance is not None


def test_fallback_summarizer_with_empty_data():
    """Verify FallbackSummarizer functions gracefully even with completely empty ingested data."""
    raw_data = AggregatedRawData()
    content = FallbackSummarizer.synthesize(raw_data)

    assert isinstance(content, GazetteContent)
    assert content.headline.title is not None
    assert content.market_insight is not None


# ------------------------------------------------------------------------------
# 3. GeminiSummarizer Tests (Mocked API & Exponential Backoff)
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_summarizer_without_api_key_activates_fallback():
    """Verify that an empty or placeholder API key immediately activates FallbackSummarizer."""
    settings = Settings(GEMINI_API_KEY="")
    summarizer = GeminiSummarizer(settings=settings)

    raw_data = AggregatedRawData(
        tech_stories=[TechStory(title="Offline Story", url="https://offline.com", source="Offline", score=10)]
    )

    content = await summarizer.summarize(raw_data)
    assert isinstance(content, GazetteContent)
    assert content.headline.title == "Offline Story"


@pytest.mark.asyncio
async def test_gemini_summarizer_success_mock():
    """Verify Gemini API successful structured JSON parsing."""
    settings = Settings(GEMINI_API_KEY="test-api-key", MAX_RETRIES=2)
    summarizer = GeminiSummarizer(settings=settings)

    mock_gazette_json = {
        "edition_date": "2 Ekim 2026, Cuma",
        "edition_number": "No. 1,428",
        "headline": {
            "kicker": "ÖZEL HABER",
            "title": "Gemini Tarafından Sentezlenen Manşet",
            "lead_paragraph": "Yapay zeka modelleri yeni nesil gazete bültenlerini otonom üretiyor.",
            "detailed_analysis": "Derinlemesine mimari analiz ve stratejik değerlendirmeler.",
            "source_name": "Google DeepMind",
            "source_url": "https://deepmind.google",
        },
        "tech_startup_stories": [],
        "ai_tools": [],
        "market_insight": {
            "market_summary": "Piyasalar dengeli.",
            "fx_commentary": "Kurlar takip ediliyor.",
            "crypto_commentary": "BTC yükselişte.",
            "editorial_take": "Stratejik büyüme odaklı kalın.",
        },
    }

    mock_response = MagicMock()
    mock_response.text = json.dumps(mock_gazette_json)

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = mock_response

        raw_data = AggregatedRawData()
        content = await summarizer.summarize(raw_data)

        assert content.headline.title == "Gemini Tarafından Sentezlenen Manşet"
        assert content.headline.source_name == "Google DeepMind"


@pytest.mark.asyncio
async def test_gemini_summarizer_retry_and_fallback_on_consecutive_errors():
    """Verify that 3 transient errors trigger backoff retries and then fallback to FallbackSummarizer."""
    settings = Settings(GEMINI_API_KEY="test-api-key", MAX_RETRIES=3)
    summarizer = GeminiSummarizer(settings=settings)

    with patch("google.genai.Client") as mock_client_cls, \
         patch("asyncio.sleep") as mock_sleep:

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Simulate 429 Quota Exceeded error on all 3 attempts
        error_429 = APIError(429, {"message": "Resource exhausted: Rate limit exceeded (429)"})
        mock_client.models.generate_content.side_effect = [error_429, error_429, error_429]

        raw_data = AggregatedRawData(
            tech_stories=[TechStory(title="Resilience Test", url="https://resilience.com", source="TechCrunch", score=99)]
        )

        content = await summarizer.summarize(raw_data)

        # Ensure retries happened
        assert mock_client.models.generate_content.call_count == 3
        # Ensure sleep was called for backoff
        assert mock_sleep.call_count == 2  # after attempt 1 and 2

        # Ensure graceful fallback returned a valid content object
        assert isinstance(content, GazetteContent)
        assert content.headline.title == "Resilience Test"
