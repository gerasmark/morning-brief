from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import Article, Briefing, Cluster, ClusterArticle, Source
from app.services.birthdays import BirthdaysService
from app.services.dedupe import build_daily_clusters
from app.services.quote_of_day import QuoteOfDayService
from app.services.ranking import rank_clusters
from app.services.strike_feed import StrikeFeedService
from app.services.summarizer import (
    ensure_daily_strike_summary,
    ensure_daily_top_summary,
    fetch_daily_strike_summary,
    fetch_daily_top_summary,
)
from app.services.weather import WeatherService

logger = logging.getLogger(__name__)


class BriefingService:
    def __init__(self) -> None:
        self.weather_service = WeatherService()
        self.birthdays_service = BirthdaysService()
        self.quote_of_day_service = QuoteOfDayService()
        self.strike_feed_service = StrikeFeedService()
        self._payload_cache: dict[str, tuple[float, dict]] = {}
        self._payload_cache_ttl_seconds = 300

    async def generate(self, session: AsyncSession, settings: Settings, day: date | None = None) -> Briefing:
        now_athens = datetime.now(settings.tzinfo)
        if day is None:
            day = now_athens.date()
        logger.info("Briefing generation start day=%s", day)
        top_source_ids = await _resolve_top_source_ids(session, settings)

        cluster_result = await build_daily_clusters(
            session=session,
            day=day,
            now_athens=now_athens,
            tz=settings.tzinfo,
            source_ids=top_source_ids if top_source_ids else None,
        )

        ranking = rank_clusters(
            clusters=cluster_result.clusters,
            articles_by_cluster_id=cluster_result.articles_by_cluster_id,
            now_utc=now_athens.astimezone(timezone.utc),
            max_items=15,
        )

        for cluster in ranking.ordered_clusters:
            session.add(cluster)
        await session.commit()

        await ensure_daily_top_summary(
            session=session,
            settings=settings,
            day=day,
            clusters=ranking.ordered_clusters,
            articles_by_cluster_id=cluster_result.articles_by_cluster_id,
        )
        logger.info(
            "Briefing generation clusters day=%s top_clusters=%d strike_clusters=%d",
            day,
            len(ranking.ordered_clusters),
            len(ranking.strike_clusters),
        )
        strike_items = await self._live_strike_items(settings=settings, day=day)
        await ensure_daily_strike_summary(
            session=session,
            settings=settings,
            day=day,
            strike_items=strike_items,
        )

        weather_json = await self.weather_service.fetch_today(settings, day)

        briefing = (await session.execute(select(Briefing).where(Briefing.day == day))).scalars().first()
        if briefing is None:
            briefing = Briefing(
                day=day,
                weather_json=weather_json,
                top_cluster_ids=[cluster.id for cluster in ranking.ordered_clusters],
                strike_cluster_ids=[cluster.id for cluster in ranking.strike_clusters],
            )
            session.add(briefing)
        else:
            briefing.weather_json = weather_json
            briefing.top_cluster_ids = [cluster.id for cluster in ranking.ordered_clusters]
            briefing.strike_cluster_ids = [cluster.id for cluster in ranking.strike_clusters]

        await session.commit()
        await session.refresh(briefing)
        self._payload_cache.pop(day.isoformat(), None)
        logger.info("Briefing generation complete day=%s briefing_id=%s", day, briefing.id)
        return briefing

    async def get_payload(self, session: AsyncSession, settings: Settings, day: date) -> dict | None:
        cache_key = day.isoformat()
        cached = self._payload_cache.get(cache_key)
        now = time.time()
        if cached and cached[0] > now:
            return cached[1]

        briefing = (await session.execute(select(Briefing).where(Briefing.day == day))).scalars().first()
        if briefing is None:
            return None

        top_items = await self._serialize_clusters(session, settings, briefing.top_cluster_ids)
        top_summary = await fetch_daily_top_summary(session, day)
        if top_summary is None and briefing.top_cluster_ids:
            top_summary = await self._backfill_top_summary(session, settings, day, briefing.top_cluster_ids)

        strike_summary = await fetch_daily_strike_summary(session, day)
        strike_items = await self._live_strike_items(settings=settings, day=day) if strike_summary else []
        if strike_summary is None and strike_items:
            strike_summary = await ensure_daily_strike_summary(
                session=session,
                settings=settings,
                day=day,
                strike_items=strike_items,
            )

        birthdays_json = await self.birthdays_service.fetch_today(settings, day)
        quote_of_day_json = await self.quote_of_day_service.fetch_for_day(settings, day)
        logger.info(
            "Briefing payload ready day=%s birthdays_unavailable=%s quote_unavailable=%s quote_author=%s",
            day,
            bool((birthdays_json or {}).get("unavailable")),
            bool((quote_of_day_json or {}).get("unavailable")),
            (quote_of_day_json or {}).get("author") or "-",
        )

        payload = {
            "id": briefing.id,
            "day": str(briefing.day),
            "created_at": briefing.created_at.isoformat() if briefing.created_at else None,
            "weather": briefing.weather_json,
            "birthdays": birthdays_json,
            "quote_of_day": quote_of_day_json,
            "top_summary_md": top_summary.summary_md if top_summary else None,
            "strike_summary_md": strike_summary.summary_md if strike_summary else None,
            "top_stories": top_items,
            "strikes": strike_items,
        }
        self._payload_cache[cache_key] = (now + self._payload_cache_ttl_seconds, payload)
        return payload

    async def _backfill_top_summary(
        self,
        session: AsyncSession,
        settings: Settings,
        day: date,
        cluster_ids: list[str],
    ):
        stmt = (
            select(Cluster)
            .options(
                selectinload(Cluster.cluster_articles)
                .selectinload(ClusterArticle.article)
                .selectinload(Article.source),
            )
            .where(Cluster.id.in_(cluster_ids))
        )
        rows = list((await session.execute(stmt)).scalars().all())
        by_id = {row.id: row for row in rows}
        ordered_clusters = [by_id[cluster_id] for cluster_id in cluster_ids if cluster_id in by_id]
        articles_by_cluster_id = {
            cluster.id: [ca.article for ca in cluster.cluster_articles if ca.article] for cluster in ordered_clusters
        }

        return await ensure_daily_top_summary(
            session=session,
            settings=settings,
            day=day,
            clusters=ordered_clusters,
            articles_by_cluster_id=articles_by_cluster_id,
        )

    async def _serialize_clusters(self, session: AsyncSession, settings: Settings, cluster_ids: list[str]) -> list[dict]:
        if not cluster_ids:
            return []

        stmt = (
            select(Cluster)
            .options(
                selectinload(Cluster.representative_source),
                selectinload(Cluster.cluster_articles)
                .selectinload(ClusterArticle.article)
                .selectinload(Article.source),
            )
            .where(Cluster.id.in_(cluster_ids))
        )
        rows = list((await session.execute(stmt)).scalars().all())
        by_id = {row.id: row for row in rows}

        serialized: list[dict] = []
        for cluster_id in cluster_ids:
            cluster = by_id.get(cluster_id)
            if cluster is None:
                continue

            sources = []
            for ca in cluster.cluster_articles:
                if not ca.article:
                    continue
                sources.append(
                    {
                        "article_id": ca.article.id,
                        "title": ca.article.title,
                        "url": ca.article.url,
                        "source": ca.article.source.name if ca.article.source else "Άγνωστη πηγή",
                        "published_at": ca.article.published_at.isoformat() if ca.article.published_at else None,
                    }
                )

            serialized.append(
                {
                    "id": cluster.id,
                    "score": cluster.score,
                    "title": cluster.representative_title,
                    "url": cluster.representative_url,
                    "source": cluster.representative_source.name if cluster.representative_source else "Άγνωστη πηγή",
                    "topics": cluster.topics or [],
                    "is_strike_related": cluster.is_strike_related,
                    "summary_md": "",
                    "sources": sources,
                }
            )

        return serialized

    async def _live_strike_items(self, settings: Settings, day: date) -> list[dict]:
        today = datetime.now(settings.tzinfo).date()
        if day != today:
            return []
        try:
            return await self.strike_feed_service.fetch_cards(settings=settings)
        except Exception as exc:
            logger.warning("Live strike items failed day=%s error=%s", day, exc)
            return []


async def get_cluster_detail(session: AsyncSession, settings: Settings, cluster_id: str) -> dict | None:
    stmt = (
        select(Cluster)
        .options(
            selectinload(Cluster.representative_source),
            selectinload(Cluster.cluster_articles)
            .selectinload(ClusterArticle.article)
            .selectinload(Article.source),
        )
        .where(Cluster.id == cluster_id)
    )
    cluster = (await session.execute(stmt)).scalars().first()
    if cluster is None:
        return None

    return {
        "id": cluster.id,
        "day": str(cluster.day),
        "title": cluster.representative_title,
        "url": cluster.representative_url,
        "source": cluster.representative_source.name if cluster.representative_source else "Άγνωστη πηγή",
        "score": cluster.score,
        "summary_md": "",
        "is_strike_related": cluster.is_strike_related,
        "articles": [
            {
                "id": ca.article.id,
                "title": ca.article.title,
                "url": ca.article.url,
                "snippet": ca.article.snippet,
                "source": ca.article.source.name if ca.article.source else "Άγνωστη πηγή",
                "published_at": ca.article.published_at.isoformat() if ca.article.published_at else None,
            }
            for ca in cluster.cluster_articles
            if ca.article
        ],
    }


async def _resolve_top_source_ids(session: AsyncSession, settings: Settings) -> list[int]:
    raw = settings.top_news_sites.strip()
    target_domains = _domains_from_urls(raw if raw else settings.strike_tag_urls)
    if not target_domains:
        return []
    sources = list((await session.execute(select(Source).where(Source.enabled.is_(True)))).scalars().all())
    matched: list[int] = []
    for source in sources:
        host = urlparse(source.base_url).netloc.lower().replace("www.", "")
        if host in target_domains:
            matched.append(source.id)
    return matched


def _domains_from_urls(url_csv: str) -> set[str]:
    domains: set[str] = set()
    for raw in [item.strip() for item in url_csv.split(",") if item.strip()]:
        value = raw.replace("https://https://", "https://").replace("http://http://", "http://")
        if not value.startswith(("http://", "https://")):
            value = "https://" + value.lstrip("/")
        host = urlparse(value).netloc.lower().replace("www.", "")
        if host:
            domains.add(host)
    return domains
