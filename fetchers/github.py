"""
Artificial Intelligence & Software Fetchers.

Fetches data from:
1. GitHub Search API (high-star AI & software repositories)
2. Hugging Face API (Daily Papers & Trending Models)
"""

from __future__ import annotations

import asyncio
from typing import Any, List
import httpx

from fetchers.base import BaseFetcher, PaperItem, RepoItem


class GitHubFetcher(BaseFetcher):
    """
    Fetches high-star and trending AI / software repositories from GitHub Search API.

    Implements explicit rate limit detection and graceful handling.
    """

    SEARCH_URL = "https://api.github.com/search/repositories"

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(name="GitHub", timeout=timeout)

    @property
    def headers(self) -> dict[str, str]:
        base = super().headers
        base["Accept"] = "application/vnd.github.v3+json"
        return base

    async def fetch(self) -> List[RepoItem]:
        repos: List[RepoItem] = []
        params = {
            "q": "topic:artificial-intelligence stars:>100",
            "sort": "stars",
            "order": "desc",
            "per_page": 10,
        }

        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            resp = await client.get(self.SEARCH_URL, params=params)

            if resp.status_code == 403:
                self.logger.warning(
                    "GitHub API rate limit encountered (HTTP 403). Gracefully skipping GitHub items."
                )
                return repos

            resp.raise_for_status()
            data = resp.json()

            for item in data.get("items", []):
                repos.append(
                    RepoItem(
                        name=item.get("name", "Unknown"),
                        full_name=item.get("full_name", ""),
                        html_url=item.get("html_url", "https://github.com"),
                        description=item.get("description"),
                        stars=int(item.get("stargazers_count") or 0),
                        forks=int(item.get("forks_count") or 0),
                        language=item.get("language"),
                        topics=item.get("topics", [])[:5],
                    )
                )

        return repos


class HuggingFaceFetcher(BaseFetcher):
    """Fetches Hugging Face daily AI research papers and spotlighted models."""

    DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
    TRENDING_MODELS_URL = "https://huggingface.co/api/models?sort=likes&direction=-1&limit=8"

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(name="HuggingFace", timeout=timeout)

    async def fetch(self) -> List[PaperItem]:
        papers: List[PaperItem] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            # 1. Fetch Daily Papers
            try:
                resp = await client.get(self.DAILY_PAPERS_URL)
                if resp.status_code == 200:
                    data = resp.json()
                    for entry in data[:10]:
                        p = entry.get("paper", {}) if isinstance(entry.get("paper"), dict) else {}
                        paper_id = p.get("id") or entry.get("id")
                        title = p.get("title") or entry.get("title")
                        summary = p.get("summary") or entry.get("summary") or ""
                        upvotes = int(p.get("upvotes") or 0)
                        pub_date = entry.get("publishedAt") or p.get("publishedAt")

                        authors_raw = p.get("authors", [])
                        authors: List[str] = []
                        if isinstance(authors_raw, list):
                            for a in authors_raw[:3]:
                                if isinstance(a, dict):
                                    authors.append(a.get("name", ""))
                                elif isinstance(a, str):
                                    authors.append(a)

                        if title and paper_id:
                            url = f"https://huggingface.co/papers/{paper_id}"
                            papers.append(
                                PaperItem(
                                    title=title.strip(),
                                    summary=summary[:280].strip() + ("..." if len(summary) > 280 else ""),
                                    url=url,
                                    upvotes=upvotes,
                                    published_at=pub_date,
                                    authors=[a for a in authors if a],
                                )
                            )
            except Exception as exc:
                self.logger.warning("Failed to parse Hugging Face daily papers: %s", exc)

            # 2. Fetch Trending Models as complementary AI items
            try:
                m_resp = await client.get(self.TRENDING_MODELS_URL)
                if m_resp.status_code == 200:
                    models = m_resp.json()
                    for m in models[:5]:
                        model_id = m.get("id")
                        if not model_id:
                            continue
                        tag = m.get("pipeline_tag") or "AI Model"
                        likes = int(m.get("likes") or 0)
                        downloads = int(m.get("downloads") or 0)
                        papers.append(
                            PaperItem(
                                title=f"{model_id} ({tag})",
                                summary=f"Trending open-weight AI model on Hugging Face. {likes} likes, {downloads} downloads.",
                                url=f"https://huggingface.co/{model_id}",
                                upvotes=likes,
                                published_at=None,
                                authors=[model_id.split("/")[0]] if "/" in model_id else [],
                            )
                        )
            except Exception as exc:
                self.logger.warning("Failed to parse Hugging Face trending models: %s", exc)

        return papers


class AIAggregator:
    """Aggregates GitHub repositories and Hugging Face papers concurrently."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.github_fetcher = GitHubFetcher(timeout=timeout)
        self.hf_fetcher = HuggingFaceFetcher(timeout=timeout)

    async def fetch_all(self) -> tuple[List[RepoItem], List[PaperItem]]:
        t_repos = self.github_fetcher.safe_fetch(default_factory=list)
        t_papers = self.hf_fetcher.safe_fetch(default_factory=list)

        repos, papers = await asyncio.gather(t_repos, t_papers)
        return (repos if isinstance(repos, list) else [], papers if isinstance(papers, list) else [])
