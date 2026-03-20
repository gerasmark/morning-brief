from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Article, Briefing, Source
from app.services.briefing import BriefingService
from app.services.email_delivery import EmailDeliveryService
from app.services.ingestion import IngestionService


class NotFoundError(LookupError):
    pass


def _serialize_source(source: Source) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "base_url": source.base_url,
        "type": source.type.value,
        "feed_url": source.feed_url,
        "sitemap_url": source.sitemap_url,
        "enabled": source.enabled,
        "weight": source.weight,
    }


def _is_naftemporiki_source(source_name: str) -> bool:
    normalized = source_name.strip().casefold()
    return normalized in {"ναυτεμπορική", "naftemporiki"}


async def list_sources(session: AsyncSession) -> list[dict[str, Any]]:
    sources = list((await session.execute(select(Source).order_by(Source.name.asc()))).scalars().all())
    return [_serialize_source(source) for source in sources]


async def resolve_source(session: AsyncSession, identifier: str) -> Source | None:
    stripped = identifier.strip()
    if stripped.isdigit():
        return (await session.execute(select(Source).where(Source.id == int(stripped)))).scalars().first()
    return (await session.execute(select(Source).where(Source.name == stripped))).scalars().first()


async def list_articles(
    session: AsyncSession,
    source: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    stmt = select(
        Article.id,
        Article.title,
        Article.url,
        Article.snippet,
        Article.published_at,
        Article.created_at,
        Source.name,
    ).join(Source, Source.id == Article.source_id)

    if source:
        stmt = stmt.where(Source.name == source)
        if _is_naftemporiki_source(source):
            raw_source = func.json_extract(Article.raw, "$.source")
            raw_also_in_feed = func.coalesce(func.json_extract(Article.raw, "$.also_in_feed"), 0)
            homepage_priority = case(
                (
                    and_(raw_source == "naftemporiki-homepage-main", raw_also_in_feed == 0),
                    0,
                ),
                else_=1,
            )
            homepage_position = func.coalesce(func.json_extract(Article.raw, "$.position"), 9999)
            stmt = stmt.order_by(
                homepage_priority.asc(),
                homepage_position.asc(),
                Article.published_at.desc(),
                Article.created_at.desc(),
            )
        else:
            stmt = stmt.order_by(Article.published_at.desc(), Article.created_at.desc())
    else:
        stmt = stmt.order_by(Article.published_at.desc(), Article.created_at.desc())

    rows = list((await session.execute(stmt.limit(limit))).all())
    return [
        {
            "id": row[0],
            "title": row[1],
            "url": row[2],
            "snippet": row[3],
            "published_at": row[4].isoformat() if row[4] else None,
            "created_at": row[5].isoformat() if row[5] else None,
            "source": row[6],
        }
        for row in rows
    ]


async def update_source(session: AsyncSession, source_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    source = (await session.execute(select(Source).where(Source.id == source_id))).scalars().first()
    if source is None:
        raise NotFoundError("Source not found")

    for field, value in updates.items():
        setattr(source, field, value)

    session.add(source)
    await session.commit()
    await session.refresh(source)
    return _serialize_source(source)


async def run_ingestion_pipeline(
    session: AsyncSession,
    settings: Settings,
    ingestion_service: IngestionService,
    briefing_service: BriefingService,
) -> dict[str, Any]:
    result = await ingestion_service.run(session)
    await briefing_service.generate(session=session, settings=settings)
    return {
        "status": "ok",
        "fetched": result.fetched,
        "inserted": result.inserted,
        "failed_sources": result.failed_sources,
        "source_stats": [
            {
                "source": item.source_name,
                "status": item.status,
                "fetched": item.fetched,
                "inserted": item.inserted,
                "http_requests": item.http_requests,
                "http_non_200": item.http_non_200,
                "http_statuses": item.http_statuses,
                "total_articles": item.total_articles,
                "last_24h_articles": item.last_24h_articles,
            }
            for item in result.source_stats
        ],
    }


async def generate_briefing_payload(
    session: AsyncSession,
    settings: Settings,
    briefing_service: BriefingService,
    day: date | None = None,
) -> dict[str, Any]:
    briefing = await briefing_service.generate(session=session, settings=settings, day=day)
    response = await briefing_service.get_payload(session, settings, briefing.day)
    return {
        "status": "ok",
        "briefing": response,
    }


async def fetch_live_strikes(
    settings: Settings,
    briefing_service: BriefingService,
    limit: int = 200,
    debug: bool = False,
) -> dict[str, Any]:
    if debug:
        return await briefing_service.strike_feed_service.fetch_debug(settings=settings, limit=limit)
    rows = await briefing_service.strike_feed_service.fetch_cards(settings=settings, limit=limit)
    return {"status": "ok", "count": len(rows), "items": rows}


async def get_today_briefing_payload(
    session: AsyncSession,
    settings: Settings,
    briefing_service: BriefingService,
) -> dict[str, Any]:
    today = datetime.now(settings.tzinfo).date()
    payload = await briefing_service.get_payload(session, settings, today)
    if payload is None:
        await briefing_service.generate(session=session, settings=settings, day=today)
        payload = await briefing_service.get_payload(session, settings, today)
    else:
        briefing_row = (await session.execute(select(Briefing).where(Briefing.day == today))).scalars().first()
        if briefing_row is not None:
            latest_weather = await briefing_service.weather_service.fetch_today(settings, today)
            briefing_row.weather_json = latest_weather
            session.add(briefing_row)
            await session.commit()
            payload["weather"] = latest_weather

    return payload or {
        "day": str(today),
        "weather": None,
        "birthdays": None,
        "quote_of_day": None,
        "top_summary_md": None,
        "strike_summary_md": None,
        "top_stories": [],
        "strikes": [],
    }


async def list_briefings(session: AsyncSession) -> list[dict[str, Any]]:
    briefings = list((await session.execute(select(Briefing).order_by(Briefing.day.desc()))).scalars().all())
    return [
        {
            "id": briefing.id,
            "day": str(briefing.day),
            "created_at": briefing.created_at.isoformat() if briefing.created_at else None,
            "top_count": len(briefing.top_cluster_ids or []),
            "strike_count": len(briefing.strike_cluster_ids or []),
        }
        for briefing in briefings
    ]


async def get_briefing_payload(
    session: AsyncSession,
    settings: Settings,
    briefing_service: BriefingService,
    day: date,
) -> dict[str, Any]:
    payload = await briefing_service.get_payload(session, settings, day)
    if payload is None:
        raise NotFoundError("Briefing not found")
    return payload


async def get_email_delivery_settings_payload(
    session: AsyncSession,
    settings: Settings,
    email_delivery_service: EmailDeliveryService,
) -> dict[str, Any]:
    return await email_delivery_service.get_settings_payload(session, settings)


async def update_email_delivery_settings_payload(
    session: AsyncSession,
    settings: Settings,
    email_delivery_service: EmailDeliveryService,
    *,
    transport: str,
    auto_send_enabled: bool,
    recipient_emails: list[str],
) -> dict[str, Any]:
    return await email_delivery_service.update_settings(
        session,
        settings,
        transport=transport,
        auto_send_enabled=auto_send_enabled,
        recipient_emails=recipient_emails,
    )


async def send_briefing_email_payload(
    session: AsyncSession,
    settings: Settings,
    briefing_service: BriefingService,
    email_delivery_service: EmailDeliveryService,
    *,
    day: date | None = None,
    recipient_emails: list[str] | None = None,
) -> dict[str, Any]:
    return await email_delivery_service.send_briefing(
        session,
        settings,
        briefing_service,
        day=day,
        recipient_emails=recipient_emails,
        triggered_by="manual",
    )
