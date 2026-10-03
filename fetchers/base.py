"""
Base Fetcher Module.

Defines the abstract BaseFetcher interface, shared data models, and safe execution
wrappers to ensure total fault isolation across all external data sources.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, List, Optional
from pydantic import BaseModel, Field


# ------------------------------------------------------------------------------
# Data Models for Raw Ingested Data
# ------------------------------------------------------------------------------

class TechStory(BaseModel):
    """Represents a tech, startup, or general engineering news item."""
    title: str
    url: str
    source: str = Field(description="e.g. Hacker News, Lobsters, TechCrunch")
    score: int = 0
    comments: int = 0
    author: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[str] = None


class RepoItem(BaseModel):
    """Represents an open-source software / AI repository."""
    name: str
    full_name: str
    html_url: str
    description: Optional[str] = None
    stars: int = 0
    forks: int = 0
    language: Optional[str] = None
    topics: List[str] = Field(default_factory=list)


class PaperItem(BaseModel):
    """Represents an AI research paper or model card."""
    title: str
    summary: str
    url: str
    upvotes: int = 0
    published_at: Optional[str] = None
    authors: List[str] = Field(default_factory=list)


class FXRate(BaseModel):
    """Represents a foreign exchange rate."""
    base_currency: str
    target_currency: str
    rate: float
    date: Optional[str] = None


class CryptoPrice(BaseModel):
    """Represents cryptocurrency pricing and 24h change."""
    symbol: str
    name: str
    price_usd: float
    change_24h: float = 0.0


class FinanceSummary(BaseModel):
    """Consolidated financial market data."""
    fx_rates: List[FXRate] = Field(default_factory=list)
    crypto_prices: List[CryptoPrice] = Field(default_factory=list)


class AggregatedRawData(BaseModel):
    """Container for all ingested raw data from independent fetchers."""
    tech_stories: List[TechStory] = Field(default_factory=list)
    repositories: List[RepoItem] = Field(default_factory=list)
    papers: List[PaperItem] = Field(default_factory=list)
    finance: FinanceSummary = Field(default_factory=FinanceSummary)


# ------------------------------------------------------------------------------
# Abstract Base Fetcher
# ------------------------------------------------------------------------------

class BaseFetcher(abc.ABC):
    """
    Abstract Base Class for all external API fetchers.

    Guarantees:
    1. Maximum timeout of 10 seconds.
    2. Total fault isolation: safe_fetch() catches all network / parsing errors.
    3. Proper User-Agent header to avoid bot-blocking.
    """

    DEFAULT_USER_AGENT = "MorningGazette/1.0 (+https://github.com/morning-gazette; educational tech digest)"

    def __init__(self, name: str, timeout: float = 10.0) -> None:
        self.name = name
        self.timeout = min(timeout, 10.0)
        self.logger = logging.getLogger(f"fetchers.{name}")

    @property
    def headers(self) -> dict[str, str]:
        """Standard HTTP headers for polite API consumption."""
        return {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "application/json, application/xml, text/xml, */*",
        }

    @abc.abstractmethod
    async def fetch(self) -> Any:
        """Fetch and return data from the external source."""
        pass

    async def safe_fetch(self, default_factory: Any = list) -> Any:
        """
        Execute fetch with complete error isolation.

        Never propagates exceptions: logs the failure and returns a safe fallback.
        """
        try:
            self.logger.info("Starting data collection from %s...", self.name)
            result = await self.fetch()
            self.logger.info("Successfully fetched data from %s.", self.name)
            return result
        except Exception as exc:
            self.logger.error(
                "Error collecting data from %s: %s. Graceful fallback activated.",
                self.name,
                exc,
                exc_info=True,
            )
            if callable(default_factory):
                return default_factory()
            return default_factory
