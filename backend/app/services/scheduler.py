from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.db import SessionLocal
from app.services.briefing import BriefingService
from app.services.email_delivery import EmailDeliveryError, EmailDeliveryService
from app.services.ingestion import IngestionService

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self.briefing_service = BriefingService()
        self.email_delivery_service = EmailDeliveryService()
        self.ingestion_service = IngestionService()
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        trigger = CronTrigger(hour=self.settings.schedule_hour, minute=self.settings.schedule_minute)
        self.scheduler.add_job(self.run_daily_pipeline, trigger=trigger, id="daily-briefing", replace_existing=True)
        self.scheduler.start()
        self.started = True

    async def stop(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False

    async def run_daily_pipeline(self) -> None:
        async with SessionLocal() as session:
            await self.ingestion_service.run(session)
            briefing = await self.briefing_service.generate(session, self.settings)
            try:
                await self.email_delivery_service.send_scheduled_if_enabled(
                    session,
                    self.settings,
                    self.briefing_service,
                    day=briefing.day,
                )
            except EmailDeliveryError as exc:
                logger.warning("Scheduled email delivery failed day=%s error=%s", briefing.day, exc)
