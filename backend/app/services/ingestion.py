from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Article, Source, SourceType
from app.services.fetchers import NaftemporikiMainFeedFetcher, RSSFetcher, RawItem, SitemapFetcher
from app.utils.text import canonicalize_url, fingerprint_from, truncate_snippet

logger = logging.getLogger(__name__)


@dataclass
class SourceIngestionStats:
    source_id: int
    source_name: str
    status: str
    fetched: int
    inserted: int
    http_requests: int
    http_non_200: int
    http_statuses: dict[int, int]
    total_articles: int
    last_24h_articles: int


@dataclass
class IngestionResult:
    fetched: int
    inserted: int
    failed_sources: list[str]
    source_stats: list[SourceIngestionStats]


@dataclass
class _HostHttpStats:
    total: int = 0
    non_200: int = 0
    by_status: dict[int, int] = field(default_factory=dict)


class _HttpRequestTracker:
    def __init__(self) -> None:
        self._stats_by_host: dict[str, _HostHttpStats] = {}

    async def on_response(self, response: httpx.Response) -> None:
        host = _normalized_host(response.request.url.host or "")
        if not host:
            return
        current = self._stats_by_host.setdefault(host, _HostHttpStats())
        current.total += 1
        status = int(response.status_code)
        current.by_status[status] = current.by_status.get(status, 0) + 1
        if status != 200:
            current.non_200 += 1

    def for_source(self, source: Source) -> _HostHttpStats:
        host = _normalized_host(urlparse(source.base_url).netloc)
        return self._stats_by_host.get(host, _HostHttpStats())


class IngestionService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.rss_fetcher = RSSFetcher()
        self.naftemporiki_fetcher = NaftemporikiMainFeedFetcher(self.rss_fetcher)
        self.sitemap_fetcher = SitemapFetcher()

    async def run(self, session: AsyncSession) -> IngestionResult:
        sources = list((await session.execute(select(Source).where(Source.enabled.is_(True)))).scalars().all())
        if not sources:
            return IngestionResult(fetched=0, inserted=0, failed_sources=[], source_stats=[])

        fetched = 0
        inserted = 0
        failed_sources: list[str] = []
        request_tracker = _HttpRequestTracker()
        source_stats_map: dict[int, SourceIngestionStats] = {
            source.id: SourceIngestionStats(
                source_id=source.id,
                source_name=source.name,
                status="ok",
                fetched=0,
                inserted=0,
                http_requests=0,
                http_non_200=0,
                http_statuses={},
                total_articles=0,
                last_24h_articles=0,
            )
            for source in sources
        }

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "proino-briefing/1.0 (+personal-use)"},
            verify=self._verify_config(),
            trust_env=True,
            event_hooks={"response": [request_tracker.on_response]},
        ) as client:
            tasks = [self._fetch_source(client, source) for source in sources]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for source, outcome in zip(sources, outcomes, strict=True):
            current = source_stats_map[source.id]
            if isinstance(outcome, Exception):
                failed_sources.append(source.name)
                current.status = "failed"
                logger.warning("Ingestion source fetch failed source=%s error=%s", source.name, outcome)
                continue

            rows: list[dict[str, Any]] = []
            for raw_item in outcome:
                normalized = self._normalize_item(source.id, raw_item)
                if normalized is None:
                    continue
                rows.append(normalized)

            current.fetched = len(rows)
            fetched += current.fetched
            if not rows:
                continue

            stmt = sqlite_insert(Article).values(rows).prefix_with("OR IGNORE")
            result = await session.execute(stmt)
            current.inserted = result.rowcount or 0
            inserted += current.inserted

        await session.commit()
        total_counts = await self._count_articles_by_source(session)
        recent_counts = await self._count_articles_by_source(
            session,
            published_since=datetime.now(timezone.utc) - timedelta(hours=24),
        )

        source_by_id = {source.id: source for source in sources}
        source_stats = sorted(source_stats_map.values(), key=lambda item: item.source_name.casefold())
        all_http_requests = 0
        all_http_non_200 = 0
        for item in source_stats:
            source_row = source_by_id.get(item.source_id)
            host_stats = request_tracker.for_source(source_row) if source_row is not None else _HostHttpStats()
            item.http_requests = host_stats.total
            item.http_non_200 = host_stats.non_200
            item.http_statuses = dict(sorted(host_stats.by_status.items()))
            item.total_articles = total_counts.get(item.source_id, 0)
            item.last_24h_articles = recent_counts.get(item.source_id, 0)
            all_http_requests += item.http_requests
            all_http_non_200 += item.http_non_200

            status_preview = ",".join(f"{status}:{count}" for status, count in item.http_statuses.items()) or "-"
            if item.http_non_200 > 0:
                logger.warning(
                    "Ingestion source stats source=%s status=%s fetched=%d inserted=%d http_requests=%d http_non_200=%d http_statuses=%s total=%d last24h=%d",
                    item.source_name,
                    item.status,
                    item.fetched,
                    item.inserted,
                    item.http_requests,
                    item.http_non_200,
                    status_preview,
                    item.total_articles,
                    item.last_24h_articles,
                )
            else:
                logger.info(
                    "Ingestion source stats source=%s status=%s fetched=%d inserted=%d http_requests=%d http_statuses=%s total=%d last24h=%d",
                    item.source_name,
                    item.status,
                    item.fetched,
                    item.inserted,
                    item.http_requests,
                    status_preview,
                    item.total_articles,
                    item.last_24h_articles,
                )

        if all_http_non_200 == 0:
            logger.info(
                "Ingestion complete sources=%d fetched=%d inserted=%d failed=%d http_requests=%d all_http_200=true",
                len(sources),
                fetched,
                inserted,
                len(failed_sources),
                all_http_requests,
            )
        else:
            logger.warning(
                "Ingestion complete sources=%d fetched=%d inserted=%d failed=%d http_requests=%d http_non_200=%d",
                len(sources),
                fetched,
                inserted,
                len(failed_sources),
                all_http_requests,
                all_http_non_200,
            )
        return IngestionResult(
            fetched=fetched,
            inserted=inserted,
            failed_sources=failed_sources,
            source_stats=source_stats,
        )

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

    async def _count_articles_by_source(
        self,
        session: AsyncSession,
        published_since: datetime | None = None,
    ) -> dict[int, int]:
        stmt = select(Article.source_id, func.count(Article.id)).group_by(Article.source_id)
        if published_since is not None:
            stmt = stmt.where(Article.published_at >= published_since)

        rows = (await session.execute(stmt)).all()
        return {int(source_id): int(count) for source_id, count in rows}


def _is_naftemporiki_source(base_url: str) -> bool:
    host = _normalized_host(urlparse(base_url).netloc)
    return host == "naftemporiki.gr"


def _normalized_host(value: str) -> str:
    return value.lower().replace("www.", "").strip()
