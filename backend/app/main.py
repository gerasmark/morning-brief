from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session, init_db
from app.models import Article, Briefing, Source, SourceType
from app.seed_sources import seed as seed_sources
from app.services.briefing import BriefingService, get_cluster_detail
from app.services.ingestion import IngestionService
from app.services.scheduler import SchedulerService

settings = get_settings()
briefing_service = BriefingService()
ingestion_service = IngestionService()
scheduler_service = SchedulerService(settings)


class SourcePatch(BaseModel):
    enabled: bool | None = None
    weight: float | None = Field(default=None, ge=0.0, le=5.0)
    feed_url: str | None = None
    sitemap_url: str | None = None
    type: SourceType | None = None


class GenerateRequest(BaseModel):
    day: date | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await seed_sources()
    scheduler_service.start()
    yield
    await scheduler_service.stop()


app = FastAPI(title="Πρωινό Briefing API", lifespan=lifespan)

origins = [item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()]
if not origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/sources")
async def list_sources(session: AsyncSession = Depends(get_session)) -> list[dict]:
    sources = list((await session.execute(select(Source).order_by(Source.name.asc()))).scalars().all())
    return [
        {
            "id": source.id,
            "name": source.name,
            "base_url": source.base_url,
            "type": source.type,
            "feed_url": source.feed_url,
            "sitemap_url": source.sitemap_url,
            "enabled": source.enabled,
            "weight": source.weight,
        }
        for source in sources
    ]


@app.get("/api/articles")
async def list_articles(
    source: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
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

    stmt = stmt.limit(limit)

    rows = list((await session.execute(stmt)).all())
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


def _is_naftemporiki_source(source_name: str) -> bool:
    normalized = source_name.strip().casefold()
    return normalized in {"ναυτεμπορική", "naftemporiki"}


@app.patch("/api/sources/{source_id}")
async def patch_source(
    source_id: int,
    payload: SourcePatch,
    session: AsyncSession = Depends(get_session),
) -> dict:
    source = (await session.execute(select(Source).where(Source.id == source_id))).scalars().first()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(source, field, value)

    session.add(source)
    await session.commit()
    await session.refresh(source)
    return {
        "id": source.id,
        "name": source.name,
        "base_url": source.base_url,
        "type": source.type,
        "feed_url": source.feed_url,
        "sitemap_url": source.sitemap_url,
        "enabled": source.enabled,
        "weight": source.weight,
    }


@app.post("/api/admin/run-ingestion")
async def run_ingestion(session: AsyncSession = Depends(get_session)) -> dict:
    result = await ingestion_service.run(session)
    return {
        "status": "ok",
        "fetched": result.fetched,
        "inserted": result.inserted,
        "failed_sources": result.failed_sources,
    }


@app.post("/api/admin/generate-briefing")
async def generate_briefing(
    payload: GenerateRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    briefing = await briefing_service.generate(session=session, settings=settings, day=payload.day if payload else None)
    response = await briefing_service.get_payload(session, settings, briefing.day)
    return {
        "status": "ok",
        "briefing": response,
    }


@app.get("/api/admin/strikes/live")
async def preview_live_strikes(
    limit: int = Query(default=200, ge=1, le=1000),
    debug: bool = Query(default=False),
) -> dict:
    if debug:
        return await briefing_service.strike_feed_service.fetch_debug(settings=settings, limit=limit)
    rows = await briefing_service.strike_feed_service.fetch_cards(settings=settings, limit=limit)
    return {"status": "ok", "count": len(rows), "items": rows}


@app.get("/api/briefings/today")
async def get_today_briefing(session: AsyncSession = Depends(get_session)) -> dict:
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
    return payload or {"day": str(today), "weather": None, "birthdays": None, "top_stories": [], "strikes": []}


@app.get("/api/briefings")
async def list_briefings(session: AsyncSession = Depends(get_session)) -> list[dict]:
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


@app.get("/api/briefings/{day}")
async def get_briefing(day: date, session: AsyncSession = Depends(get_session)) -> dict:
    payload = await briefing_service.get_payload(session, settings, day)
    if payload is None:
        raise HTTPException(status_code=404, detail="Briefing not found")
    return payload


@app.get("/api/clusters/{cluster_id}")
async def cluster_detail(cluster_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    payload = await get_cluster_detail(session, settings, cluster_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return payload
