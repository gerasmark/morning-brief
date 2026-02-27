from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Article, Source, SourceType
from app.services.fetchers import NaftemporikiMainFeedFetcher, RSSFetcher, RawItem, SitemapFetcher
from app.utils.text import canonicalize_url, fingerprint_from, truncate_snippet


@dataclass
class IngestionResult:
    fetched: int
    inserted: int
    failed_sources: list[str]


class IngestionService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.rss_fetcher = RSSFetcher()
        self.naftemporiki_fetcher = NaftemporikiMainFeedFetcher(self.rss_fetcher)
        self.sitemap_fetcher = SitemapFetcher()

    async def run(self, session: AsyncSession) -> IngestionResult:
        sources = list((await session.execute(select(Source).where(Source.enabled.is_(True)))).scalars().all())
        if not sources:
            return IngestionResult(fetched=0, inserted=0, failed_sources=[])

        fetched = 0
        inserted = 0
        failed_sources: list[str] = []

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "proino-briefing/1.0 (+personal-use)"},
            verify=self._verify_config(),
            trust_env=True,
        ) as client:
            tasks = [self._fetch_source(client, source) for source in sources]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for source, outcome in zip(sources, outcomes, strict=True):
            if isinstance(outcome, Exception):
                failed_sources.append(source.name)
                continue

            rows: list[dict[str, Any]] = []
            for raw_item in outcome:
                normalized = self._normalize_item(source.id, raw_item)
                if normalized is None:
                    continue
                rows.append(normalized)

            fetched += len(rows)
            if not rows:
                continue

            stmt = sqlite_insert(Article).values(rows).prefix_with("OR IGNORE")
            result = await session.execute(stmt)
            inserted += result.rowcount or 0

        await session.commit()
        return IngestionResult(fetched=fetched, inserted=inserted, failed_sources=failed_sources)

    def _verify_config(self) -> bool | str:
        if self.settings.weather_ca_bundle:
            return self.settings.weather_ca_bundle
        return self.settings.weather_ssl_verify

    async def _fetch_source(self, client: httpx.AsyncClient, source: Source) -> list[RawItem]:
        if source.type == SourceType.rss and source.feed_url:
            if _is_naftemporiki_source(source.base_url):
                return await self.naftemporiki_fetcher.fetch(
                    client=client,
                    homepage_url=source.base_url,
                    feed_url=source.feed_url,
                    feed_limit=10,
                )
            return await self.rss_fetcher.fetch(client, source.feed_url)
        if source.type == SourceType.sitemap and source.sitemap_url:
            return await self.sitemap_fetcher.fetch(client, source.sitemap_url)
        return []

    def _normalize_item(self, source_id: int, item: RawItem) -> dict[str, Any] | None:
        title = (item.title or "").strip()
        url = (item.url or "").strip()
        if not title or not url:
            return None

        canonical_url = canonicalize_url(url)
        published_at = item.published_at
        if published_at is None:
            published_at = datetime.now(timezone.utc)
        elif published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        return {
            "source_id": source_id,
            "title": title,
            "url": canonical_url,
            "published_at": published_at,
            "snippet": truncate_snippet(item.snippet, max_len=500),
            "raw": item.raw,
            "fingerprint": fingerprint_from(title, canonical_url),
            "created_at": datetime.now(timezone.utc),
        }


def _is_naftemporiki_source(base_url: str) -> bool:
    host = urlparse(base_url).netloc.lower().replace("www.", "")
    return host == "naftemporiki.gr"
