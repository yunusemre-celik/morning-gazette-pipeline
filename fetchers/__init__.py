"""
Fetchers Package Initialization.

Provides a unified interface to collect all raw data concurrently with total fault isolation.
"""

from __future__ import annotations

import asyncio
import logging
from fetchers.base import (
    AggregatedRawData,
    BaseFetcher,
    CryptoPrice,
    FinanceSummary,
    FXRate,
    PaperItem,
    RepoItem,
    TechStory,
)
from fetchers.finance import (
    CoinGeckoFetcher,
    FinanceAggregator,
    FrankfurterFetcher,
)
from fetchers.github import (
    AIAggregator,
    GitHubFetcher,
    HuggingFaceFetcher,
)
from fetchers.tech import (
    HackerNewsFetcher,
    LobstersFetcher,
    TechAggregator,
    TechCrunchFetcher,
)

logger = logging.getLogger("fetchers.collector")


async def collect_all_data(timeout: float = 10.0) -> AggregatedRawData:
    """
    Collects raw data across Tech, AI, and Finance concurrently.

    No single failure can crash the aggregator.
    """
    logger.info("Initiating concurrent data collection across all sources...")

    tech_aggregator = TechAggregator(timeout=timeout)
    ai_aggregator = AIAggregator(timeout=timeout)
    finance_aggregator = FinanceAggregator(timeout=timeout)

    tech_task = tech_aggregator.fetch_all()
    ai_task = ai_aggregator.fetch_all()
    finance_task = finance_aggregator.fetch_all()

    tech_stories, (repos, papers), finance_data = await asyncio.gather(
        tech_task, ai_task, finance_task
    )

    logger.info(
        "Data collection completed: %d tech stories, %d repos, %d papers, %d FX rates, %d crypto prices.",
        len(tech_stories),
        len(repos),
        len(papers),
        len(finance_data.fx_rates),
        len(finance_data.crypto_prices),
    )

    return AggregatedRawData(
        tech_stories=tech_stories,
        repositories=repos,
        papers=papers,
        finance=finance_data,
    )


__all__ = [
    "BaseFetcher",
    "TechStory",
    "RepoItem",
    "PaperItem",
    "FXRate",
    "CryptoPrice",
    "FinanceSummary",
    "AggregatedRawData",
    "HackerNewsFetcher",
    "LobstersFetcher",
    "TechCrunchFetcher",
    "TechAggregator",
    "GitHubFetcher",
    "HuggingFaceFetcher",
    "AIAggregator",
    "FrankfurterFetcher",
    "CoinGeckoFetcher",
    "FinanceAggregator",
    "collect_all_data",
]
