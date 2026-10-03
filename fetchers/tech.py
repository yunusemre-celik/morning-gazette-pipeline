"""
Technology and Startup News Fetchers.

Fetches data from:
1. Hacker News (via Algolia API)
2. Lobsters (via official JSON API)
3. TechCrunch (via RSS feed)
"""

from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from typing import List, Optional
import httpx

from fetchers.base import BaseFetcher, TechStory


class HackerNewsFetcher(BaseFetcher):
    """Fetches top front-page stories from Hacker News via Algolia API."""

    API_URL = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=15"

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(name="HackerNews", timeout=timeout)

    async def fetch(self) -> List[TechStory]:
        stories: List[TechStory] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            resp = await client.get(self.API_URL)
            resp.raise_for_status()
            data = resp.json()

            hits = data.get("hits", [])
            for item in hits:
                title = item.get("title") or item.get("story_title")
                if not title:
                    continue

                object_id = item.get("objectID")
                url = item.get("url") or item.get("story_url")
                if not url and object_id:
                    url = f"https://news.ycombinator.com/item?id={object_id}"

                stories.append(
                    TechStory(
                        title=title.strip(),
                        url=url or "https://news.ycombinator.com",
                        source="Hacker News",
                        score=int(item.get("points") or 0),
                        comments=int(item.get("num_comments") or 0),
                        author=item.get("author"),
                        published_at=item.get("created_at"),
                    )
                )

        return stories


class LobstersFetcher(BaseFetcher):
    """Fetches hottest stories from Lobsters technical community."""

    API_URL = "https://lobste.rs/hottest.json"

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(name="Lobsters", timeout=timeout)

    async def fetch(self) -> List[TechStory]:
        stories: List[TechStory] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            resp = await client.get(self.API_URL)
            resp.raise_for_status()
            items = resp.json()

            for item in items[:15]:
                title = item.get("title")
                if not title:
                    continue

                url = item.get("url") or item.get("short_id_url")
                submitter = item.get("submitter_user") or {}
                author = submitter.get("username") if isinstance(submitter, dict) else str(submitter)

                stories.append(
                    TechStory(
                        title=title.strip(),
                        url=url or "https://lobste.rs",
                        source="Lobsters",
                        score=int(item.get("score") or 0),
                        comments=int(item.get("comment_count") or 0),
                        author=author,
                        published_at=item.get("created_at"),
                    )
                )

        return stories


class TechCrunchFetcher(BaseFetcher):
    """Fetches latest venture, startup, and tech news from TechCrunch RSS."""

    RSS_URL = "https://techcrunch.com/feed/"

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(name="TechCrunch", timeout=timeout)

    @staticmethod
    def _clean_html(raw_html: Optional[str]) -> str:
        """Strip HTML tags and unescape entities."""
        if not raw_html:
            return ""
        clean = re.sub(r"<[^>]+>", "", raw_html)
        return html.unescape(clean).strip()

    async def fetch(self) -> List[TechStory]:
        stories: List[TechStory] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            resp = await client.get(self.RSS_URL)
            resp.raise_for_status()
            content = resp.content

            root = ET.fromstring(content)
            channel = root.find("channel")
            if channel is None:
                return stories

            items = channel.findall("item")
            for item in items[:15]:
                title_elem = item.find("title")
                link_elem = item.find("link")
                desc_elem = item.find("description")
                pub_date_elem = item.find("pubDate")
                creator_elem = item.find("{http://purl.org/dc/elements/1.1/}creator")

                title = title_elem.text.strip() if (title_elem is not None and title_elem.text) else None
                link = link_elem.text.strip() if (link_elem is not None and link_elem.text) else None
                desc = self._clean_html(desc_elem.text) if (desc_elem is not None and desc_elem.text) else ""
                pub_date = pub_date_elem.text.strip() if (pub_date_elem is not None and pub_date_elem.text) else None
                author = creator_elem.text.strip() if (creator_elem is not None and creator_elem.text) else None

                if title and link:
                    stories.append(
                        TechStory(
                            title=title,
                            url=link,
                            source="TechCrunch",
                            score=0,
                            comments=0,
                            author=author,
                            summary=desc[:240] + ("..." if len(desc) > 240 else ""),
                            published_at=pub_date,
                        )
                    )

        return stories


class TechAggregator:
    """Aggregates all technology and startup sources concurrently with fault isolation."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.fetchers = [
            HackerNewsFetcher(timeout=timeout),
            LobstersFetcher(timeout=timeout),
            TechCrunchFetcher(timeout=timeout),
        ]

    async def fetch_all(self) -> List[TechStory]:
        tasks = [f.safe_fetch(default_factory=list) for f in self.fetchers]
        results = await asyncio.gather(*tasks)

        all_stories: List[TechStory] = []
        for batch in results:
            if isinstance(batch, list):
                all_stories.extend(batch)

        return all_stories
