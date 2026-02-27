from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import Article, Cluster
from app.services.keywords import PUBLIC_SAFETY_KEYWORDS


@dataclass
class RankingResult:
    ordered_clusters: list[Cluster]
    strike_clusters: list[Cluster]


def _keyword_boost(articles: list[Article]) -> float:
    payload = " ".join((a.title + " " + (a.snippet or "")).lower() for a in articles)
    if any(keyword in payload for keyword in PUBLIC_SAFETY_KEYWORDS):
        return 0.1
    return 0.0


def rank_clusters(
    clusters: list[Cluster],
    articles_by_cluster_id: dict[str, list[Article]],
    now_utc: datetime,
    max_items: int = 15,
) -> RankingResult:
    if max_items < 10:
        max_items = 10
    if max_items > 20:
        max_items = 20

    for cluster in clusters:
        articles = articles_by_cluster_id.get(cluster.id, [])
        if not articles:
            cluster.score = 0.0
            continue

        unique_source_count = len({a.source_id for a in articles})
        coverage = math.log1p(unique_source_count)

        latest_pub = max([a.published_at for a in articles if a.published_at], default=now_utc)
        if latest_pub.tzinfo is None:
            latest_pub = latest_pub.replace(tzinfo=timezone.utc)
        hours_since_pub = max((now_utc - latest_pub).total_seconds() / 3600, 0)
        recency = math.exp(-hours_since_pub / 12)

        source_weight = max([(a.source.weight if a.source else 1.0) for a in articles], default=1.0)
        boost = _keyword_boost(articles)

        cluster.score = 0.5 * coverage + 0.4 * recency + 0.1 * source_weight + boost

    ordered = sorted(clusters, key=lambda item: item.score, reverse=True)[:max_items]
    strike = [cluster for cluster in ordered if cluster.is_strike_related]
    return RankingResult(ordered_clusters=ordered, strike_clusters=strike)
