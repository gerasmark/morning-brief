from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import SourceType
from app.runtime import bootstrap_data, configure_logging
from app.services.briefing import BriefingService, get_cluster_detail
from app.services.email_delivery import EmailDeliveryError, EmailDeliveryService
from app.services.ingestion import IngestionService
from app.services.scheduler import SchedulerService
from app.use_cases import (
    NotFoundError,
    fetch_live_strikes,
    generate_briefing_payload,
    get_email_delivery_settings_payload,
    get_briefing_payload,
    get_today_briefing_payload,
    list_articles as list_article_rows,
    list_briefings as list_briefing_rows,
    list_sources as list_source_rows,
    run_ingestion_pipeline,
    send_briefing_email_payload,
    update_email_delivery_settings_payload,
    update_source,
)


settings = get_settings()
configure_logging(settings)
briefing_service = BriefingService()
email_delivery_service = EmailDeliveryService()
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


class EmailDeliverySettingsPatch(BaseModel):
    transport: Literal["smtp", "resend_api"] = "smtp"
    auto_send_enabled: bool
    recipient_emails: list[str] = Field(default_factory=list)


class SendBriefingEmailRequest(BaseModel):
    day: date | None = None
    recipient_emails: list[str] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    await bootstrap_data()
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
    return await list_source_rows(session)


@app.get("/api/articles")
async def list_articles(
    source: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return await list_article_rows(session, source=source, limit=limit)


@app.patch("/api/sources/{source_id}")
async def patch_source(
    source_id: int,
    payload: SourcePatch,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        return await update_source(session, source_id, payload.model_dump(exclude_unset=True))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/run-ingestion")
async def run_ingestion(session: AsyncSession = Depends(get_session)) -> dict:
    return await run_ingestion_pipeline(session, settings, ingestion_service, briefing_service)


@app.post("/api/admin/generate-briefing")
async def generate_briefing(
    payload: GenerateRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await generate_briefing_payload(
        session,
        settings,
        briefing_service,
        day=payload.day if payload else None,
    )


@app.get("/api/admin/strikes/live")
async def preview_live_strikes(
    limit: int = Query(default=200, ge=1, le=1000),
    debug: bool = Query(default=False),
) -> dict:
    return await fetch_live_strikes(settings, briefing_service, limit=limit, debug=debug)


@app.post("/api/admin/send-briefing-email")
async def send_briefing_email(
    payload: SendBriefingEmailRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        return await send_briefing_email_payload(
            session,
            settings,
            briefing_service,
            email_delivery_service,
            day=payload.day if payload else None,
            recipient_emails=payload.recipient_emails if payload else None,
        )
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/briefings/today")
async def get_today_briefing(session: AsyncSession = Depends(get_session)) -> dict:
    return await get_today_briefing_payload(session, settings, briefing_service)


@app.get("/api/briefings")
async def list_briefings(session: AsyncSession = Depends(get_session)) -> list[dict]:
    return await list_briefing_rows(session)


@app.get("/api/briefings/{day}")
async def get_briefing(day: date, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        return await get_briefing_payload(session, settings, briefing_service, day)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/delivery/email-settings")
async def get_email_delivery_settings(session: AsyncSession = Depends(get_session)) -> dict:
    return await get_email_delivery_settings_payload(session, settings, email_delivery_service)


@app.put("/api/delivery/email-settings")
async def update_email_delivery_settings(
    payload: EmailDeliverySettingsPatch,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        return await update_email_delivery_settings_payload(
            session,
            settings,
            email_delivery_service,
            transport=payload.transport,
            auto_send_enabled=payload.auto_send_enabled,
            recipient_emails=payload.recipient_emails,
        )
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/clusters/{cluster_id}")
async def cluster_detail(cluster_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    payload = await get_cluster_detail(session, settings, cluster_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return payload
