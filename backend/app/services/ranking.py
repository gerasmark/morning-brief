from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from app.models import Article, Cluster


@dataclass
class RankingResult:
    ordered_clusters: list[Cluster]
    strike_clusters: list[Cluster]


@dataclass
class _ClusterSignals:
    unique_source_count: int
    article_count: int
    latest_age_hours: float
    recent_90m_count: int
    avg_source_weight: float
    impact_score: float
    homepage_prominence: float


_IMPACT_SIGNAL_GROUPS: list[tuple[float, tuple[str, ...]]] = [
    (
        0.45,
        (
            "σεισμ",
            "πυρκαγ",
            "φωτι",
            "πλημμυρ",
            "εκκένω",
            "θύμα",
            "νεκρ",
            "τραυματ",
            "έκρηξ",
            "κακοκαιρ",
            "ανεμοστρόβι",
            "κατολίσθησ",
        ),
    ),
    (
        0.30,
        (
            "απεργ",
            "στάση εργασ",
            "διακοπή ρεύμα",
            "μπλακ άουτ",
            "μπλακάουτ",
            "κυκλοφορ",
            "κλειστό",
            "καθυστέρησ",
            "αναστολή",
            "ακυρώσ",
        ),
    ),
    (
        0.25,
        (
            "κυβέρνησ",
            "υπουργ",
            "βουλή",
            "νομοσχέδι",
            "εκλογ",
            "παραίτησ",
            "εισαγγελέ",
            "δικαστ",
            "σκάνδαλ",
        ),
    ),
    (
        0.25,
        (
            "πληθωρισ",
            "επιτόκ",
            "φόρ",
            "ακρίβ",
            "μισθ",
            "συντάξ",
            "ανεργ",
            "χρηματιστήρ",
            "ευρωζών",
        ),
    ),
    (
        0.20,
        (
            "πόλεμ",
            "επίθεσ",
            "εκεχειρί",
            "διπλωματ",
            "σύνοδο",
            "κυρώσ",
            "nato",
            "νατο",
        ),
    ),
]
_URGENCY_TERMS = (
    "έκτακτο",
    "τώρα",
    "alert",
    "σοκ",
    "breaking",
)
_SCORE_WEIGHTS = {
    "coverage": 0.18,
    "volume": 0.13,
    "recency": 0.16,
    "relative_spike": 0.18,
    "impact": 0.20,
    "source_quality": 0.09,
    "prominence": 0.06,
}
_SPIKE_WINDOW_MINUTES = 90
_COVERAGE_SATURATION = 4
_VOLUME_SATURATION = 10


def _safe_published_at(value: datetime | None, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _tags_from_raw(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return []
    tags = raw.get("tags")
    if not isinstance(tags, list):
        return []

    values: list[str] = []
    for tag in tags:
        if isinstance(tag, str):
            normalized = tag.strip()
            if normalized:
                values.append(normalized)
    return values


def _article_payload(article: Article) -> str:
    tags = " ".join(_tags_from_raw(article.raw))
    return f"{article.title} {article.snippet or ''} {tags}".lower()


def _impact_score(articles: list[Article]) -> float:
    payload = " ".join(_article_payload(article) for article in articles)

    score = 0.0
    for weight, terms in _IMPACT_SIGNAL_GROUPS:
        if any(term in payload for term in terms):
            score += weight

    if any(term in payload for term in _URGENCY_TERMS):
        score += 0.1

    return max(0.0, min(score, 1.0))


def _homepage_prominence(articles: list[Article]) -> float:
    best = 0.0
    for article in articles:
        if not isinstance(article.raw, dict):
            continue
        position = article.raw.get("position")
        if not isinstance(position, int) or position <= 0:
            continue
        prominence = 1.0 / (1.0 + 0.15 * (position - 1))
        if prominence > best:
            best = prominence
    return best


def _source_quality(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return max(0.0, min(value / max_value, 1.0))


def _cluster_signals(articles: list[Article], now_utc: datetime) -> _ClusterSignals:
    if not articles:
        return _ClusterSignals(
            unique_source_count=0,
            article_count=0,
            latest_age_hours=9999.0,
            recent_90m_count=0,
            avg_source_weight=0.0,
            impact_score=0.0,
            homepage_prominence=0.0,
        )

    unique_source_count = len({item.source_id for item in articles})
    article_count = len(articles)

    published = [_safe_published_at(item.published_at, now_utc) for item in articles]
    latest_pub = max(published, default=now_utc)
    latest_age_hours = max((now_utc - latest_pub).total_seconds() / 3600.0, 0.0)

    recent_cutoff = now_utc - timedelta(minutes=_SPIKE_WINDOW_MINUTES)
    recent_90m_count = sum(1 for value in published if value >= recent_cutoff)

    source_weights = [(item.source.weight if item.source else 1.0) for item in articles]
    avg_source_weight = sum(source_weights) / len(source_weights)

    return _ClusterSignals(
        unique_source_count=unique_source_count,
        article_count=article_count,
        latest_age_hours=latest_age_hours,
        recent_90m_count=recent_90m_count,
        avg_source_weight=avg_source_weight,
        impact_score=_impact_score(articles),
        homepage_prominence=_homepage_prominence(articles),
    )


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

    signals_by_cluster_id = {
        cluster.id: _cluster_signals(articles_by_cluster_id.get(cluster.id, []), now_utc)
        for cluster in clusters
    }
    recent_counts = [signals.recent_90m_count for signals in signals_by_cluster_id.values()]
    median_recent_90m = float(median(recent_counts)) if recent_counts else 0.0
    max_avg_source_weight = max(
        (signals.avg_source_weight for signals in signals_by_cluster_id.values()),
        default=1.0,
    )

    for cluster in clusters:
        signals = signals_by_cluster_id.get(cluster.id)
        if signals is None or signals.article_count == 0:
            cluster.score = 0.0
            continue

        coverage = min(signals.unique_source_count / _COVERAGE_SATURATION, 1.0)
        volume = min(math.log1p(signals.article_count) / math.log1p(_VOLUME_SATURATION), 1.0)
        recency = math.exp(-signals.latest_age_hours / 10.0)

        spike_baseline = max(median_recent_90m, 1.0)
        relative_spike = min((signals.recent_90m_count / spike_baseline) / 3.0, 1.0)

        source_quality = _source_quality(signals.avg_source_weight, max_avg_source_weight)
        impact = signals.impact_score
        prominence = signals.homepage_prominence

        cluster.score = (
            _SCORE_WEIGHTS["coverage"] * coverage
            + _SCORE_WEIGHTS["volume"] * volume
            + _SCORE_WEIGHTS["recency"] * recency
            + _SCORE_WEIGHTS["relative_spike"] * relative_spike
            + _SCORE_WEIGHTS["impact"] * impact
            + _SCORE_WEIGHTS["source_quality"] * source_quality
            + _SCORE_WEIGHTS["prominence"] * prominence
        )

    ordered = sorted(clusters, key=lambda item: item.score, reverse=True)[:max_items]
    strike = [cluster for cluster in ordered if cluster.is_strike_related]
    return RankingResult(ordered_clusters=ordered, strike_clusters=strike)
