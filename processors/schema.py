"""
Pydantic Schema Module for Structured AI Editorial Summarization.

Defines the strict response schema required for Google Gemini API structured output
and subsequent Jinja2 newspaper email template rendering.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field
from fetchers.base import FinanceSummary


class HeadlineStory(BaseModel):
    """The premier front-page lead headline story."""
    kicker: str = Field(
        default="EXCLUSIVE LEAD",
        description="Category kicker / label (e.g. AI REVOLUTION, VENTURE CAPITAL, TECH SHIFT).",
    )
    title: str = Field(
        description="Compelling, editorial newspaper headline.",
    )
    lead_paragraph: str = Field(
        description="Opening summary with drop-cap editorial prose.",
    )
    detailed_analysis: str = Field(
        description="In-depth analytical breakdown of why this story matters to technologists and founders.",
    )
    source_name: str = Field(
        description="Original reporting source (e.g. TechCrunch, Hacker News, Lobsters).",
    )
    source_url: str = Field(
        description="Direct link to source article or discussion.",
    )


class TechStartupArticle(BaseModel):
    """Column article in the two-column tech & venture stream."""
    category: str = Field(
        default="TECH & VENTURE",
        description="Section category (e.g. SOFTWARE ARCHITECTURE, STARTUP ECOSYSTEM, CYBERSECURITY).",
    )
    title: str = Field(
        description="Sharp headline for the article.",
    )
    summary: str = Field(
        description="Concise 2-3 sentence overview.",
    )
    key_takeaway: str = Field(
        description="Actionable takeaway or strategic industry impact.",
    )
    source_name: str = Field(
        description="Source platform or publisher.",
    )
    source_url: str = Field(
        description="Direct link to article or thread.",
    )


class AIToolModel(BaseModel):
    """Featured AI repositories, research papers, or open models."""
    name: str = Field(
        description="Tool, library, repository, or paper title.",
    )
    category: str = Field(
        default="Open Source",
        description="Type: Model, Open Source Tool, Research Paper, Library.",
    )
    description: str = Field(
        description="What it does and core technical architecture.",
    )
    why_it_matters: str = Field(
        description="Why developers, engineers, and researchers should care.",
    )
    source_url: str = Field(
        description="GitHub, Hugging Face, or arXiv link.",
    )


class MarketInsight(BaseModel):
    """Macroeconomic briefing & market commentary."""
    market_summary: str = Field(
        description="General macro financial sentiment for the morning edition.",
    )
    fx_commentary: str = Field(
        description="Analysis of foreign exchange rates and currency dynamics.",
    )
    crypto_commentary: str = Field(
        description="Assessment of Bitcoin and Ethereum 24h market movements.",
    )
    editorial_take: str = Field(
        description="Strategic note for startup founders, CTOs, and investors.",
    )


class GazetteContent(BaseModel):
    """Root structured data container for the entire Morning Gazette issue."""
    edition_date: str = Field(
        description="Formatted issue dateline (e.g. 'Friday, October 2, 2026').",
    )
    edition_number: str = Field(
        default="No. 1,428",
        description="Gazette edition / issue number.",
    )
    headline: HeadlineStory = Field(
        description="Front-page premier headline story.",
    )
    tech_startup_stories: List[TechStartupArticle] = Field(
        default_factory=list,
        description="Curated list of 4-6 tech and venture capital stories.",
    )
    ai_tools: List[AIToolModel] = Field(
        default_factory=list,
        description="Curated list of 3-5 open-source AI tools and papers.",
    )
    market_insight: MarketInsight = Field(
        description="Financial commentary and market overview.",
    )
    raw_finance: Optional[FinanceSummary] = Field(
        default=None,
        description="Raw ticker data (USD/TRY, EUR/TRY, BTC, ETH) passed to the template.",
    )
    curator_note: Optional[str] = Field(
        default=None,
        description="Optional editorial signoff or publisher remark.",
    )
