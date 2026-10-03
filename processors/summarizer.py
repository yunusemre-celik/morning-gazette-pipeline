"""
Summarizer Module powered by Google Gemini API with Graceful Degradation.

Implements:
1. Google Gemini Flash with structured JSON output.
2. 3-step Exponential Backoff for 429/500 errors.
3. FallbackSummarizer for offline, missing-key, or emergency resilience scenarios.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError

from config import Settings, get_settings
from fetchers.base import AggregatedRawData, FinanceSummary
from processors.schema import (
    AIToolModel,
    GazetteContent,
    HeadlineStory,
    MarketInsight,
    TechStartupArticle,
)

logger = logging.getLogger("processors.summarizer")


def format_gazette_date(dt: Optional[datetime.datetime] = None) -> str:
    """Format datetime into standard English newspaper dateline (e.g. 'Friday, October 2, 2026')."""
    if dt is None:
        dt = datetime.datetime.now()
    return dt.strftime("%A, %B %d, %Y")


# Backward compatibility alias
format_turkish_date = format_gazette_date


class FallbackSummarizer:
    """
    Emergency rule-based summarizer.

    Activated when Gemini API key is missing or when all network/API retries fail.
    Guarantees zero-crash delivery of The Morning Gazette by synthesizing
    raw headlines, repositories, and financial data into the schema.
    """

    @classmethod
    def synthesize(cls, raw_data: AggregatedRawData) -> GazetteContent:
        logger.info("Executing Emergency Fallback Summarizer (Offline / Graceful Mode)...")
        date_str = format_gazette_date()

        # 1. Headline Story: Pick highest score or first tech story
        stories = list(raw_data.tech_stories)
        if stories:
            top_story = max(stories, key=lambda s: s.score)
            stories.remove(top_story)
            headline = HeadlineStory(
                kicker="FRONT PAGE LEAD",
                title=top_story.title,
                lead_paragraph=(
                    f"Leading discussions across {top_story.source}, this pivotal technological development "
                    f"is sending ripples across the global software and startup ecosystem."
                ),
                detailed_analysis=(
                    f"Garnering {top_story.score} community points and {top_story.comments} discussions, "
                    f"industry observers highlight that this breakthrough signals a critical inflection point "
                    f"in infrastructure scalability and modern software engineering paradigms."
                ),
                source_name=top_story.source,
                source_url=top_story.url,
            )
        else:
            headline = HeadlineStory(
                kicker="FRONT PAGE LEAD",
                title="Next-Generation Autonomous Systems Surge Across Developer Ecosystems",
                lead_paragraph="The global open-source community continues to accelerate autonomous tooling and frontier AI agents.",
                detailed_analysis="Software architectures are undergoing a fundamental transformation toward lightweight, modular local models.",
                source_name="The Morning Gazette Editorial Desk",
                source_url="https://github.com",
            )

        # 2. Tech & Startup Stories: 4-6 articles
        tech_articles: list[TechStartupArticle] = []
        for s in stories[:6]:
            summary_text = s.summary or f"Trending on {s.source} with {s.score} points and {s.comments} community responses."
            tech_articles.append(
                TechStartupArticle(
                    category=s.source.upper(),
                    title=s.title,
                    summary=summary_text,
                    key_takeaway="Signals emerging architectural patterns and operational efficiencies for agile engineering teams.",
                    source_name=s.source,
                    source_url=s.url,
                )
            )

        # 3. AI Tools & Models: from GitHub repos & Hugging Face papers
        ai_tools: list[AIToolModel] = []
        for repo in raw_data.repositories[:3]:
            ai_tools.append(
                AIToolModel(
                    name=repo.name,
                    category="Open Source Repository",
                    description=repo.description or "Trending open-source artificial intelligence and developer tooling.",
                    why_it_matters=f"Backed by the developer community with {repo.stars:,} GitHub stars.",
                    source_url=repo.html_url,
                )
            )

        for paper in raw_data.papers[:3]:
            ai_tools.append(
                AIToolModel(
                    name=paper.title,
                    category="Research Paper / Model",
                    description=paper.summary or "Spotlight research publication featured on Hugging Face.",
                    why_it_matters=f"Earned {paper.upvotes} community upvotes for advancing frontier machine intelligence.",
                    source_url=paper.url,
                )
            )

        # 4. Market Insight
        fx_rates = {f.base_currency: f.rate for f in raw_data.finance.fx_rates}
        usd_rate = fx_rates.get("USD", 0.0)
        eur_rate = fx_rates.get("EUR", 0.0)

        crypto_map = {c.symbol: c for c in raw_data.finance.crypto_prices}
        btc = crypto_map.get("BTC")
        eth = crypto_map.get("ETH")

        fx_desc = f"USD/TRY trading near {usd_rate:.2f} TL and EUR/TRY near {eur_rate:.2f} TL." if usd_rate else "FX pairs holding steady."
        crypto_desc = ""
        if btc:
            crypto_desc += f"Bitcoin is at ${btc.price_usd:,.0f} ({btc.change_24h:+.2f}%) "
        if eth:
            crypto_desc += f"with Ethereum at ${eth.price_usd:,.0f} ({eth.change_24h:+.2f}%)."

        market_insight = MarketInsight(
            market_summary="Global markets demonstrate measured momentum as technology bellwethers prepare for upcoming earnings and central bank commentary.",
            fx_commentary=fx_desc,
            crypto_commentary=crypto_desc or "Digital asset markets maintain disciplined consolidation within key technical ranges.",
            editorial_take="For startup founders and operators, capital efficiency, hedging currency exposures, and runway preservation remain paramount.",
        )

        return GazetteContent(
            edition_date=date_str,
            edition_number=f"No. {datetime.datetime.now().strftime('%y%j')}",
            headline=headline,
            tech_startup_stories=tech_articles,
            ai_tools=ai_tools,
            market_insight=market_insight,
            raw_finance=raw_data.finance,
            curator_note="This edition was autonomously generated by The Morning Gazette Data Pipeline.",
        )


class GeminiSummarizer:
    """
    Main AI Editorial Summarizer using Google Gemini API.

    Features:
    - Structured JSON generation via response_schema.
    - 3-step exponential backoff for transient 429/500 errors.
    - Automatic graceful degradation to FallbackSummarizer if unresolvable.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.api_key = self.settings.GEMINI_API_KEY
        self.model = self.settings.GEMINI_MODEL or "gemini-3.8-flash"
        self.max_retries = max(1, self.settings.MAX_RETRIES)

    def _prepare_prompt(self, raw_data: AggregatedRawData) -> str:
        """Compose context payload for Gemini."""
        tech_context = [
            f"- [{s.source}] {s.title} (Score: {s.score}, Comments: {s.comments}) Link: {s.url}\n  Summary: {s.summary or ''}"
            for s in raw_data.tech_stories[:25]
        ]
        repo_context = [
            f"- [GitHub] {r.full_name}: {r.description} (Stars: {r.stars}) Link: {r.html_url}"
            for r in raw_data.repositories[:10]
        ]
        paper_context = [
            f"- [HuggingFace] {p.title}: {p.summary[:200]} (Upvotes: {p.upvotes}) Link: {p.url}"
            for p in raw_data.papers[:8]
        ]
        fx_context = [
            f"- {f.base_currency}/{f.target_currency}: {f.rate}"
            for f in raw_data.finance.fx_rates
        ]
        crypto_context = [
            f"- {c.name} ({c.symbol}): ${c.price_usd:,.2f} (24h: {c.change_24h:+.2f}%)"
            for c in raw_data.finance.crypto_prices
        ]

        return f"""
You are the Editor-in-Chief of 'The Morning Gazette', a prestigious daily technology and financial newspaper.
Analyze the following raw intelligence collected across tech news, open-source repositories, AI research, and financial markets.
Produce a structured, intellectually rigorous, executive-level newspaper digest in English.

### EDITORIAL GUIDELINES:
1. 'headline' (Lead Story): Select the single most transformative, globally impactful tech story. Craft an authoritative, compelling headline, a sophisticated lead paragraph (lead_paragraph), and an in-depth analytical breakdown (detailed_analysis).
2. 'tech_startup_stories': Curate 4 to 6 distinct, high-signal technology and venture capital developments. Provide a summary and a sharp 'key_takeaway' for each.
3. 'ai_tools': Highlight 3 to 5 premier open-source tools, repositories, or research papers. Articulate clearly what they do and 'why_it_matters' to software engineers and tech leaders.
4. 'market_insight': Synthesize the macroeconomic environment, currency exchange rates (USD/TRY, EUR/TRY), and crypto assets (BTC, ETH). Provide a tactical 'editorial_take' for startup founders and investors.
5. 'edition_date': Format today's date (e.g. '{format_gazette_date()}').

### RAW INGESTED DATA:
**Technology & Startup Feeds:**
{chr(10).join(tech_context)}

**Open Source Repositories (GitHub):**
{chr(10).join(repo_context)}

**AI Research Papers & Models (Hugging Face):**
{chr(10).join(paper_context)}

**Financial Markets (FX & Crypto):**
FX Rates: {", ".join(fx_context) if fx_context else "Data unavailable"}
Crypto Assets: {", ".join(crypto_context) if crypto_context else "Data unavailable"}
"""

    async def summarize(self, raw_data: AggregatedRawData) -> GazetteContent:
        """
        Produce structured GazetteContent using Gemini API with retry and fallback.
        """
        if not self.api_key or self.api_key in ("your_gemini_api_key_here", ""):
            logger.warning("GEMINI_API_KEY is not configured. Switching to FallbackSummarizer.")
            return FallbackSummarizer.synthesize(raw_data)

        prompt = self._prepare_prompt(raw_data)
        client = genai.Client(api_key=self.api_key)

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GazetteContent,
            temperature=0.3,
        )

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "Sending structured synthesis request to Gemini (%s, attempt %d/%d)...",
                    self.model,
                    attempt,
                    self.max_retries,
                )

                # Execute synchronous client call in worker thread to prevent event loop blocking
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=self.model,
                    contents=prompt,
                    config=config,
                )

                if response and response.text:
                    parsed_json = json.loads(response.text)
                    content = GazetteContent.model_validate(parsed_json)
                    content.raw_finance = raw_data.finance
                    logger.info("Successfully synthesized Morning Gazette with Gemini!")
                    return content
                else:
                    raise ValueError("Gemini returned empty response.")

            except Exception as exc:
                is_transient = False
                error_str = str(exc)

                if isinstance(exc, APIError):
                    if exc.code in (429, 500, 503, 504):
                        is_transient = True
                elif "429" in error_str or "500" in error_str or "quota" in error_str.lower() or "timeout" in error_str.lower():
                    is_transient = True

                backoff_delay = 2 ** (attempt - 1)
                logger.warning(
                    "Gemini API attempt %d failed: %s. Transient=%s. Backoff: %ds",
                    attempt,
                    exc,
                    is_transient,
                    backoff_delay,
                )

                if attempt < self.max_retries and is_transient:
                    await asyncio.sleep(backoff_delay)
                elif attempt >= self.max_retries:
                    logger.error(
                        "All %d Gemini API retries exhausted. Activating Graceful FallbackSummarizer.",
                        self.max_retries,
                    )
                    break

        return FallbackSummarizer.synthesize(raw_data)
