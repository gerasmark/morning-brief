from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Article, Cluster, ClusterArticle
from app.services.keywords import BIRTHDAY_NEWS_KEYWORDS, STRIKE_KEYWORDS
from app.utils.text import cluster_key, normalize_title, token_set

logger = logging.getLogger(__name__)


@dataclass
class TempCluster:
    normalized_title: str
    tokens: set[str]
    articles: list[Article] = field(default_factory=list)


@dataclass
class ClusterBuildResult:
    clusters: list[Cluster]
    articles_by_cluster_id: dict[str, list[Article]]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_strike_related(articles: list[Article]) -> bool:
    payload = " ".join(filter(None, [a.title + " " + (a.snippet or "") for a in articles])).lower()
    return any(keyword in payload for keyword in STRIKE_KEYWORDS)


def _is_birthday_story(article: Article) -> bool:
    payload = f"{article.title} {article.snippet or ''}".lower()
    return any(keyword in payload for keyword in BIRTHDAY_NEWS_KEYWORDS)


def _pick_representative(articles: list[Article]) -> Article:
    def sort_key(item: Article) -> tuple[float, datetime]:
        source_weight = item.source.weight if item.source else 1.0
        published = item.published_at or datetime.now(timezone.utc)
        return (source_weight, published)

    return max(articles, key=sort_key)


def _day_window(day: date, now_athens: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    if day == now_athens.date():
        end = now_athens
    else:
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    start = end - timedelta(hours=24)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def build_daily_clusters(
    session: AsyncSession,
    day: date,
    now_athens: datetime,
    tz: ZoneInfo,
    source_ids: list[int] | None = None,
) -> ClusterBuildResult:
    window_start, window_end = _day_window(day, now_athens, tz)

    stmt = select(Article).options(selectinload(Article.source)).where(
        Article.published_at >= window_start,
        Article.published_at <= window_end,
    )
    if source_ids:
        stmt = stmt.where(Article.source_id.in_(source_ids))
    stmt = stmt.order_by(Article.published_at.desc())
    articles = list((await session.execute(stmt)).scalars().all())
    if not articles:
        # Fallback for cases where source timestamps are stale/missing timezone:
        # keep briefing useful by using latest ingested items.
        fallback_stmt = select(Article).options(selectinload(Article.source))
        if source_ids:
            fallback_stmt = fallback_stmt.where(Article.source_id.in_(source_ids))
        fallback_stmt = fallback_stmt.order_by(Article.published_at.desc(), Article.created_at.desc()).limit(400)
        articles = list((await session.execute(fallback_stmt)).scalars().all())

    original_count = len(articles)
    articles = [article for article in articles if not _is_birthday_story(article)]
    filtered_count = original_count - len(articles)
    if filtered_count > 0:
        logger.info("Top news filter removed birthday stories count=%d day=%s", filtered_count, day)

    temp_clusters: list[TempCluster] = []

    for article in articles:
        normalized = normalize_title(article.title)
        article_tokens = token_set(article.title)
        assigned = False

        for cluster in temp_clusters:
            sim = fuzz.token_set_ratio(normalized, cluster.normalized_title)
            jac = _jaccard(article_tokens, cluster.tokens)
            if sim >= 85 or jac >= 0.5:
                cluster.articles.append(article)
                cluster.tokens |= article_tokens
                assigned = True
                break

        if not assigned:
            temp_clusters.append(
                TempCluster(
                    normalized_title=normalized,
                    tokens=article_tokens,
                    articles=[article],
                )
            )

    existing_clusters = list((await session.execute(select(Cluster).where(Cluster.day == day))).scalars().all())
    existing_by_key = {item.key: item for item in existing_clusters}

    persisted: list[Cluster] = []
    articles_by_cluster_id: dict[str, list[Article]] = {}
    seen_ids: set[str] = set()

    for temp in temp_clusters:
        representative = _pick_representative(temp.articles)
        key = cluster_key([item.fingerprint for item in temp.articles])

        cluster = existing_by_key.get(key)
        if cluster is None:
            cluster = Cluster(
                day=day,
                key=key,
                representative_title=representative.title,
                representative_url=representative.url,
                representative_source_id=representative.source_id,
                topics=None,
                is_strike_related=_is_strike_related(temp.articles),
                score=0.0,
            )
            session.add(cluster)
            await session.flush()
        else:
            cluster.representative_title = representative.title
            cluster.representative_url = representative.url
            cluster.representative_source_id = representative.source_id
            cluster.is_strike_related = _is_strike_related(temp.articles)
            cluster.topics = None

        await session.execute(delete(ClusterArticle).where(ClusterArticle.cluster_id == cluster.id))
        for article in temp.articles:
            session.add(ClusterArticle(cluster_id=cluster.id, article_id=article.id))

        seen_ids.add(cluster.id)
        persisted.append(cluster)
        articles_by_cluster_id[cluster.id] = temp.articles

    for cluster in existing_clusters:
        if cluster.id not in seen_ids:
            await session.delete(cluster)

    await session.commit()

    refreshed = list((await session.execute(select(Cluster).where(Cluster.day == day))).scalars().all())
    refreshed_by_id = {item.id: item for item in refreshed}
    final_clusters = [refreshed_by_id[item.id] for item in persisted if item.id in refreshed_by_id]
    return ClusterBuildResult(clusters=final_clusters, articles_by_cluster_id=articles_by_cluster_id)
