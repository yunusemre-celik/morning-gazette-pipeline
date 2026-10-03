"""
Financial Market Data Fetchers.

Fetches data from:
1. Frankfurter API (USD/TRY, EUR/TRY currency exchange rates)
2. CoinGecko API (BTC/USD, ETH/USD real-time prices & 24h percentage changes)
"""

from __future__ import annotations

import asyncio
from typing import List
import httpx

from fetchers.base import BaseFetcher, CryptoPrice, FinanceSummary, FXRate


class FrankfurterFetcher(BaseFetcher):
    """Fetches foreign exchange rates (USD/TRY and EUR/TRY) from Frankfurter API."""

    USD_URL = "https://api.frankfurter.dev/v1/latest?from=USD&to=TRY"
    EUR_URL = "https://api.frankfurter.dev/v1/latest?from=EUR&to=TRY"

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(name="Frankfurter", timeout=timeout)

    async def fetch(self) -> List[FXRate]:
        rates: List[FXRate] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            resp_usd, resp_eur = await asyncio.gather(
                client.get(self.USD_URL),
                client.get(self.EUR_URL),
                return_exceptions=True,
            )

            if isinstance(resp_usd, httpx.Response) and resp_usd.status_code == 200:
                data = resp_usd.json()
                try_rate = data.get("rates", {}).get("TRY")
                if try_rate is not None:
                    rates.append(
                        FXRate(
                            base_currency="USD",
                            target_currency="TRY",
                            rate=float(try_rate),
                            date=data.get("date"),
                        )
                    )

            if isinstance(resp_eur, httpx.Response) and resp_eur.status_code == 200:
                data = resp_eur.json()
                try_rate = data.get("rates", {}).get("TRY")
                if try_rate is not None:
                    rates.append(
                        FXRate(
                            base_currency="EUR",
                            target_currency="TRY",
                            rate=float(try_rate),
                            date=data.get("date"),
                        )
                    )

        return rates


class CoinGeckoFetcher(BaseFetcher):
    """Fetches cryptocurrency spot prices and 24h changes from CoinGecko API."""

    API_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(name="CoinGecko", timeout=timeout)

    async def fetch(self) -> List[CryptoPrice]:
        crypto_prices: List[CryptoPrice] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            resp = await client.get(self.API_URL)

            if resp.status_code == 429:
                self.logger.warning(
                    "CoinGecko rate limit encountered (HTTP 429). Skipping crypto metrics gracefully."
                )
                return crypto_prices

            resp.raise_for_status()
            data = resp.json()

            # Bitcoin
            btc_data = data.get("bitcoin")
            if btc_data and "usd" in btc_data:
                crypto_prices.append(
                    CryptoPrice(
                        symbol="BTC",
                        name="Bitcoin",
                        price_usd=float(btc_data["usd"]),
                        change_24h=float(btc_data.get("usd_24h_change") or 0.0),
                    )
                )

            # Ethereum
            eth_data = data.get("ethereum")
            if eth_data and "usd" in eth_data:
                crypto_prices.append(
                    CryptoPrice(
                        symbol="ETH",
                        name="Ethereum",
                        price_usd=float(eth_data["usd"]),
                        change_24h=float(eth_data.get("usd_24h_change") or 0.0),
                    )
                )

        return crypto_prices


class FinanceAggregator:
    """Aggregates currency exchange and cryptocurrency prices concurrently."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.fx_fetcher = FrankfurterFetcher(timeout=timeout)
        self.crypto_fetcher = CoinGeckoFetcher(timeout=timeout)

    async def fetch_all(self) -> FinanceSummary:
        fx_task = self.fx_fetcher.safe_fetch(default_factory=list)
        crypto_task = self.crypto_fetcher.safe_fetch(default_factory=list)

        fx_rates, crypto_prices = await asyncio.gather(fx_task, crypto_task)

        return FinanceSummary(
            fx_rates=fx_rates if isinstance(fx_rates, list) else [],
            crypto_prices=crypto_prices if isinstance(crypto_prices, list) else [],
        )
