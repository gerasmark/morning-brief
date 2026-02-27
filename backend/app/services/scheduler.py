from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.db import SessionLocal
from app.services.briefing import BriefingService
from app.services.ingestion import IngestionService


class SchedulerService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self.briefing_service = BriefingService()
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
            await self.briefing_service.generate(session, self.settings)
