from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import smtplib
import ssl
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Briefing, EmailDeliveryConfig, EmailDeliveryLog
from app.services.briefing import BriefingService

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_TRANSPORTS = ("smtp", "resend_api")


class EmailDeliveryError(RuntimeError):
    pass


class EmailDeliveryService:
    async def get_or_create_config(self, session: AsyncSession) -> EmailDeliveryConfig:
        config = (
            await session.execute(select(EmailDeliveryConfig).order_by(EmailDeliveryConfig.id.asc()))
        ).scalars().first()
        if config is not None:
            if not config.transport:
                config.transport = "smtp"
                session.add(config)
                await session.commit()
                await session.refresh(config)
            return config

        config = EmailDeliveryConfig(transport="smtp", auto_send_enabled=False, recipient_emails=[])
        session.add(config)
        await session.commit()
        await session.refresh(config)
        return config

    async def get_settings_payload(self, session: AsyncSession, settings: Settings) -> dict[str, Any]:
        config = await self.get_or_create_config(session)
        transport = self.normalize_transport(config.transport)
        sender_address = self.resolve_sender_address(settings, transport=transport)
        readiness = self.get_transport_readiness(settings)
        return {
            "transport": transport,
            "available_transports": list(EMAIL_TRANSPORTS),
            "auto_send_enabled": config.auto_send_enabled,
            "recipient_emails": config.recipient_emails or [],
            "sender_address": sender_address,
            "sender_name": settings.email_from_name,
            "active_transport_ready": readiness[transport],
            "transport_readiness": readiness,
            "schedule_hour": settings.schedule_hour,
            "schedule_minute": settings.schedule_minute,
            "timezone": settings.timezone,
        }

    async def update_settings(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        transport: str,
        auto_send_enabled: bool,
        recipient_emails: list[str],
    ) -> dict[str, Any]:
        config = await self.get_or_create_config(session)
        config.transport = self.normalize_transport(transport)
        config.auto_send_enabled = auto_send_enabled
        config.recipient_emails = self.normalize_recipients(recipient_emails)
        session.add(config)
        await session.commit()
        await session.refresh(config)
        return await self.get_settings_payload(session, settings)

    async def send_scheduled_if_enabled(
        self,
        session: AsyncSession,
        settings: Settings,
        briefing_service: BriefingService,
        *,
        day: date,
    ) -> dict[str, Any]:
        config = await self.get_or_create_config(session)
        if not config.auto_send_enabled:
            return {
                "status": "skipped",
                "day": str(day),
                "reason": "auto-send-disabled",
                "recipient_count": 0,
            }

        if await self._already_sent(session, day, triggered_by="scheduled"):
            return {
                "status": "skipped",
                "day": str(day),
                "reason": "already-sent",
                "recipient_count": 0,
            }

        return await self.send_briefing(
            session,
            settings,
            briefing_service,
            day=day,
            recipient_emails=config.recipient_emails or [],
            triggered_by="scheduled",
        )

    async def send_briefing(
        self,
        session: AsyncSession,
        settings: Settings,
        briefing_service: BriefingService,
        *,
        day: date | None = None,
        recipient_emails: list[str] | None = None,
        triggered_by: str = "manual",
    ) -> dict[str, Any]:
        target_day = day or datetime.now(settings.tzinfo).date()
        config = await self.get_or_create_config(session)
        transport = self.normalize_transport(config.transport)
        recipients = self.normalize_recipients(recipient_emails or config.recipient_emails or [])
        sender_address = self.resolve_sender_address(settings, transport=transport)
        subject = self.build_subject(target_day)

        if not recipients:
            raise EmailDeliveryError("No recipient emails configured yet.")
        self.ensure_transport_configured(settings, transport=transport, sender_address=sender_address)

        payload = await self._load_payload(session, settings, briefing_service, target_day)
        html_report = self.render_html_report(payload, settings)
        text_report = self.render_text_report(payload)

        try:
            if transport == "smtp":
                await asyncio.to_thread(
                    self._send_smtp_message,
                    settings,
                    sender_address or "",
                    recipients,
                    subject,
                    text_report,
                    html_report,
                )
            elif transport == "resend_api":
                await self._send_resend_message(
                    settings,
                    sender_address or "",
                    recipients,
                    subject,
                    text_report,
                    html_report,
                    idempotency_key=self._build_resend_idempotency_key(target_day, triggered_by, recipients),
                )
            else:
                raise EmailDeliveryError(f"Unsupported email transport: {transport}")
        except Exception as exc:
            await self._log_attempt(
                session,
                day=target_day,
                triggered_by=triggered_by,
                status="failed",
                sender=sender_address or "",
                subject=subject,
                recipient_emails=recipients,
                error_message=str(exc),
            )
            raise EmailDeliveryError(f"Email delivery failed: {exc}") from exc

        await self._log_attempt(
            session,
            day=target_day,
            triggered_by=triggered_by,
            status="sent",
            sender=sender_address or "",
            subject=subject,
            recipient_emails=recipients,
            error_message=None,
        )
        logger.info(
            "Email delivered day=%s triggered_by=%s transport=%s recipients=%d sender=%s",
            target_day,
            triggered_by,
            transport,
            len(recipients),
            sender_address,
        )
        return {
            "status": "sent",
            "day": str(target_day),
            "sender": sender_address,
            "subject": subject,
            "recipients": recipients,
            "recipient_count": len(recipients),
            "transport": transport,
            "triggered_by": triggered_by,
        }

    def normalize_transport(self, value: str | None) -> str:
        normalized = (value or "smtp").strip().lower()
        if normalized not in EMAIL_TRANSPORTS:
            raise EmailDeliveryError(f"Unsupported email transport: {normalized}")
        return normalized

    def resolve_sender_address(self, settings: Settings, *, transport: str) -> str | None:
        if transport == "smtp":
            sender = (settings.email_from_address or settings.smtp_username or "").strip()
            return sender or None
        if transport == "resend_api":
            sender = (settings.resend_from_address or "").strip()
            return sender or None
        return None

    def get_transport_readiness(self, settings: Settings) -> dict[str, bool]:
        smtp_sender = self.resolve_sender_address(settings, transport="smtp")
        resend_sender = self.resolve_sender_address(settings, transport="resend_api")
        return {
            "smtp": bool(
                settings.smtp_host
                and smtp_sender
                and (not settings.smtp_username or settings.smtp_password)
            ),
            "resend_api": bool(settings.resend_api_key and resend_sender),
        }

    def ensure_transport_configured(self, settings: Settings, *, transport: str, sender_address: str | None) -> None:
        if not sender_address:
            if transport == "smtp":
                raise EmailDeliveryError("Sender address is not configured. Set EMAIL_FROM_ADDRESS or SMTP_USERNAME.")
            if transport == "resend_api":
                raise EmailDeliveryError("Sender address is not configured. Set EMAIL_FROM_ADDRESS in backend/.env.")

        if transport == "smtp":
            if not settings.smtp_host:
                raise EmailDeliveryError("SMTP host is not configured. Set SMTP_HOST in backend/.env.")
            if settings.smtp_username and not settings.smtp_password:
                raise EmailDeliveryError("SMTP_PASSWORD is required when SMTP_USERNAME is set.")
            return

        if transport == "resend_api":
            if not settings.resend_api_key:
                raise EmailDeliveryError("RESEND_API_KEY is not configured. Set it in backend/.env.")
            return

        raise EmailDeliveryError(f"Unsupported email transport: {transport}")

    def normalize_recipients(self, raw_values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            for chunk in re.split(r"[\n,;]+", raw_value):
                value = chunk.strip().lower()
                if not value:
                    continue
                if not EMAIL_RE.match(value):
                    raise EmailDeliveryError(f"Invalid email address: {value}")
                if value in seen:
                    continue
                seen.add(value)
                normalized.append(value)
        return normalized

    def build_subject(self, target_day: date) -> str:
        return f"Πρωινό Briefing | {target_day.isoformat()}"

    def _build_resend_idempotency_key(self, target_day: date, triggered_by: str, recipients: list[str]) -> str:
        digest = hashlib.sha1(",".join(sorted(recipients)).encode("utf-8")).hexdigest()[:12]
        return f"morning-brief:{target_day.isoformat()}:{triggered_by}:{digest}"

    async def _already_sent(self, session: AsyncSession, day: date, *, triggered_by: str) -> bool:
        existing = (
            await session.execute(
                select(EmailDeliveryLog)
                .where(
                    EmailDeliveryLog.day == day,
                    EmailDeliveryLog.triggered_by == triggered_by,
                    EmailDeliveryLog.status == "sent",
                )
                .order_by(EmailDeliveryLog.created_at.desc())
            )
        ).scalars().first()
        return existing is not None

    async def _load_payload(
        self,
        session: AsyncSession,
        settings: Settings,
        briefing_service: BriefingService,
        target_day: date,
    ) -> dict[str, Any]:
        payload = await briefing_service.get_payload(session, settings, target_day)
        if payload is None:
            await briefing_service.generate(session=session, settings=settings, day=target_day)
            payload = await briefing_service.get_payload(session, settings, target_day)

        if payload is None:
            raise EmailDeliveryError(f"Briefing for {target_day.isoformat()} could not be generated.")

        today = datetime.now(settings.tzinfo).date()
        if target_day == today:
            briefing_row = (await session.execute(select(Briefing).where(Briefing.day == today))).scalars().first()
            if briefing_row is not None:
                latest_weather = await briefing_service.weather_service.fetch_today(settings, today)
                briefing_row.weather_json = latest_weather
                session.add(briefing_row)
                await session.commit()
                payload["weather"] = latest_weather

        return payload

    async def _log_attempt(
        self,
        session: AsyncSession,
        *,
        day: date,
        triggered_by: str,
        status: str,
        sender: str,
        subject: str,
        recipient_emails: list[str],
        error_message: str | None,
    ) -> None:
        session.add(
            EmailDeliveryLog(
                day=day,
                triggered_by=triggered_by,
                status=status,
                sender=sender,
                subject=subject,
                recipient_emails=recipient_emails,
                error_message=error_message,
            )
        )
        await session.commit()

    def render_html_report(self, payload: dict[str, Any], settings: Settings) -> str:
        top_summary = "".join(
            f"<p style='margin:0 0 12px; line-height:1.65;'>{html.escape(paragraph)}</p>"
            for paragraph in _paragraphs(payload.get("top_summary_md"))
        ) or "<p style='margin:0; color:#61736a;'>Δεν υπάρχει σύνοψη κορυφαίων θεμάτων.</p>"

        strike_summary_items = "".join(
            f"<li style='margin:0 0 8px;'>{html.escape(item)}</li>"
            for item in _bullets(payload.get("strike_summary_md"))
        )
        strike_summary = (
            f"<ul style='margin:0; padding-left:18px; line-height:1.6;'>{strike_summary_items}</ul>"
            if strike_summary_items
            else "<p style='margin:0; color:#61736a;'>Δεν υπάρχει σύνοψη μετακινήσεων.</p>"
        )

        story_cards = self._render_cluster_cards(payload.get("top_stories") or [])
        strike_cards = self._render_cluster_cards(payload.get("strikes") or [])
        weather_block = self._render_weather(payload.get("weather"))
        birthdays_block = self._render_birthdays(payload.get("birthdays"))
        quote_block = self._render_quote(payload.get("quote_of_day"))
        sender_address = html.escape(self.resolve_sender_address(settings, transport="smtp") or "Μη ρυθμισμένο")
        sender_name = html.escape(settings.email_from_name)
        title_day = html.escape(payload.get("day") or "")

        return f"""<!DOCTYPE html>
<html lang="el">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Πρωινό Briefing</title>
  </head>
  <body style="margin:0; padding:24px 12px; background:#f4f7f2; color:#13211a; font-family:Arial, Helvetica, sans-serif;">
    <div style="max-width:760px; margin:0 auto; background:#ffffff; border:1px solid #d5e2d0; border-radius:20px; overflow:hidden;">
      <div style="padding:24px 28px; background:linear-gradient(135deg, #f7efe5 0%, #edf5ea 100%); border-bottom:1px solid #d5e2d0;">
        <p style="margin:0 0 10px; color:#55685f; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Daily Report</p>
        <h1 style="margin:0 0 8px; font-size:30px; line-height:1.1;">Πρωινό Briefing</h1>
        <p style="margin:0; color:#425349; line-height:1.6;">Αποστολή ημέρας {title_day} · From: {sender_name} &lt;{sender_address}&gt;</p>
      </div>

      <div style="padding:24px 28px 6px;">
        <h2 style="margin:0 0 12px; font-size:20px;">Με μια ματιά</h2>
        <div style="padding:16px 18px; border:1px solid #e2cbb5; border-radius:16px; background:#fff8f2;">{top_summary}</div>
      </div>

      <div style="padding:18px 28px 6px;">
        <h2 style="margin:0 0 12px; font-size:20px;">Καιρός · Εορτολόγιο · Απόφθεγμα</h2>
        <div style="display:block;">
          {weather_block}
          {birthdays_block}
          {quote_block}
        </div>
      </div>

      <div style="padding:18px 28px 6px;">
        <h2 style="margin:0 0 12px; font-size:20px;">Κορυφαία Θέματα</h2>
        {story_cards}
      </div>

      <div style="padding:18px 28px 6px;">
        <h2 style="margin:0 0 12px; font-size:20px;">Απεργίες / Μετακινήσεις</h2>
        <div style="padding:16px 18px; border:1px solid #c8d6eb; border-radius:16px; background:#f4f8ff; margin-bottom:14px;">{strike_summary}</div>
        {strike_cards}
      </div>

      <div style="padding:18px 28px 28px; color:#61736a; font-size:13px; line-height:1.6;">
        Το email δημιουργήθηκε από το stored briefing payload της εφαρμογής σε timezone {html.escape(settings.timezone)}.
      </div>
    </div>
  </body>
</html>"""

    def render_text_report(self, payload: dict[str, Any]) -> str:
        lines = [f"Πρωινό Briefing | {payload.get('day') or ''}", ""]

        lines.append("Με μια ματιά")
        top_summary = _paragraphs(payload.get("top_summary_md"))
        lines.extend(top_summary or ["Δεν υπάρχει σύνοψη κορυφαίων θεμάτων."])
        lines.append("")

        weather = payload.get("weather") or {}
        lines.append("Καιρός")
        if weather:
            city = weather.get("city") or "Αθήνα"
            current_temperature = _fmt_number(weather.get("current_temperature"), suffix="°C")
            current_condition = weather.get("current_condition") or "Χωρίς περιγραφή"
            lines.append(f"{city}: {current_temperature} · {current_condition}")
        else:
            lines.append("Μη διαθέσιμο")
        lines.append("")

        birthdays = payload.get("birthdays") or {}
        lines.append("Ποιοι γιορτάζουν σήμερα")
        if birthdays.get("names"):
            lines.append(", ".join(str(name) for name in birthdays["names"]))
        else:
            lines.append("Δεν βρέθηκαν ονόματα.")
        lines.append("")

        quote = payload.get("quote_of_day") or {}
        lines.append("Απόφθεγμα της ημέρας")
        if quote.get("quote"):
            lines.append(f"\"{quote['quote']}\"")
            if quote.get("author"):
                lines.append(f"- {quote['author']}")
        else:
            lines.append("Δεν βρέθηκε απόφθεγμα.")
        lines.append("")

        lines.append("Κορυφαία θέματα")
        top_stories = payload.get("top_stories") or []
        if not top_stories:
            lines.append("Δεν υπάρχουν θέματα.")
        for index, item in enumerate(top_stories, start=1):
            lines.append(f"{index}. {item.get('title') or 'Χωρίς τίτλο'}")
            lines.append(f"   Πηγή: {item.get('source') or 'Άγνωστη πηγή'}")
            lines.append(f"   Link: {item.get('url') or ''}")
        lines.append("")

        lines.append("Απεργίες / Μετακινήσεις")
        strike_summary = _bullets(payload.get("strike_summary_md"))
        lines.extend([f"- {item}" for item in strike_summary] or ["Δεν υπάρχει σύνοψη μετακινήσεων."])
        strikes = payload.get("strikes") or []
        if strikes:
            lines.append("")
            for index, item in enumerate(strikes, start=1):
                lines.append(f"{index}. {item.get('title') or 'Χωρίς τίτλο'}")
                lines.append(f"   Πηγή: {item.get('source') or 'Άγνωστη πηγή'}")
                lines.append(f"   Link: {item.get('url') or ''}")

        return "\n".join(lines).strip()

    def _render_cluster_cards(self, items: list[dict[str, Any]]) -> str:
        if not items:
            return "<p style='margin:0; color:#61736a;'>Δεν υπάρχουν διαθέσιμα θέματα.</p>"

        cards: list[str] = []
        for item in items:
            topics = item.get("topics") or []
            topics_html = ""
            if topics:
                topic_tags = "".join(
                    f"<span style='display:inline-block; margin:0 6px 6px 0; padding:4px 8px; border-radius:999px; background:#eef4eb; color:#385142; font-size:12px;'>{html.escape(str(topic))}</span>"
                    for topic in topics
                )
                topics_html = f"<div style='margin:10px 0 4px;'>{topic_tags}</div>"

            sources = item.get("sources") or []
            source_list = "".join(
                f"<li style='margin:0 0 6px;'><a href='{html.escape(source.get('url') or '')}' style='color:#1f5f97; text-decoration:none;'>{html.escape(source.get('source') or 'Άγνωστη πηγή')} · {html.escape(source.get('title') or 'Χωρίς τίτλο')}</a></li>"
                for source in sources
            )
            sources_html = (
                f"<div style='margin-top:12px;'><strong style='display:block; margin-bottom:6px; font-size:13px;'>Υποστηρικτικές πηγές</strong><ul style='margin:0; padding-left:18px; line-height:1.5;'>{source_list}</ul></div>"
                if source_list
                else ""
            )

            cards.append(
                f"""
<div style="margin:0 0 14px; padding:16px 18px; border:1px solid #d5e2d0; border-radius:16px; background:#ffffff;">
  <p style="margin:0 0 6px; color:#56685f; font-size:13px;">{html.escape(item.get('source') or 'Άγνωστη πηγή')}</p>
  <h3 style="margin:0 0 8px; font-size:18px; line-height:1.35;"><a href="{html.escape(item.get('url') or '')}" style="color:#13211a; text-decoration:none;">{html.escape(item.get('title') or 'Χωρίς τίτλο')}</a></h3>
  {topics_html}
  {sources_html}
</div>"""
            )
        return "".join(cards)

    def _render_weather(self, weather: dict[str, Any] | None) -> str:
        if not weather:
            return "<div style='margin:0 0 12px; padding:16px 18px; border:1px solid #d5e2d0; border-radius:16px; background:#f8fbf7;'>Ο καιρός δεν είναι διαθέσιμος.</div>"

        forecast_rows = "".join(
            f"<li style='margin:0 0 6px;'>{html.escape(str(day.get('day') or ''))}: {_fmt_number(day.get('temperature_min'), suffix='°C')} έως {_fmt_number(day.get('temperature_max'), suffix='°C')} · {html.escape(str(day.get('condition') or ''))}</li>"
            for day in (weather.get("forecast") or [])[:4]
        )
        forecast_html = (
            f"<ul style='margin:12px 0 0; padding-left:18px; line-height:1.5;'>{forecast_rows}</ul>"
            if forecast_rows
            else ""
        )
        current_temperature = _fmt_number(weather.get("current_temperature"), suffix="°C")
        current_condition = weather.get("current_condition") or "Χωρίς περιγραφή"
        city = weather.get("city") or "Αθήνα"
        return (
            "<div style='margin:0 0 12px; padding:16px 18px; border:1px solid #d5e2d0; border-radius:16px; background:#f8fbf7;'>"
            f"<strong style='display:block; margin-bottom:6px;'>{html.escape(str(city))}</strong>"
            f"<div style='line-height:1.6;'>{html.escape(current_temperature)} · {html.escape(str(current_condition))}</div>"
            f"{forecast_html}"
            "</div>"
        )

    def _render_birthdays(self, birthdays: dict[str, Any] | None) -> str:
        if not birthdays or birthdays.get("unavailable"):
            return "<div style='margin:0 0 12px; padding:16px 18px; border:1px solid #d5e2d0; border-radius:16px; background:#fffaf2;'>Το εορτολόγιο δεν είναι διαθέσιμο.</div>"

        names = birthdays.get("names") or []
        content = ", ".join(html.escape(str(name)) for name in names) if names else "Δεν βρέθηκαν ονόματα."
        return (
            "<div style='margin:0 0 12px; padding:16px 18px; border:1px solid #d5e2d0; border-radius:16px; background:#fffaf2;'>"
            "<strong style='display:block; margin-bottom:6px;'>Ποιοι γιορτάζουν σήμερα</strong>"
            f"<div style='line-height:1.6;'>{content}</div>"
            "</div>"
        )

    def _render_quote(self, quote: dict[str, Any] | None) -> str:
        if not quote or quote.get("unavailable") or not quote.get("quote"):
            return "<div style='margin:0 0 12px; padding:16px 18px; border:1px solid #d5e2d0; border-radius:16px; background:#f7f5ff;'>Δεν βρέθηκε απόφθεγμα ημέρας.</div>"

        author = quote.get("author")
        author_html = f"<div style='margin-top:8px; color:#56685f;'>- {html.escape(str(author))}</div>" if author else ""
        return (
            "<div style='margin:0 0 12px; padding:16px 18px; border:1px solid #d5e2d0; border-radius:16px; background:#f7f5ff;'>"
            "<strong style='display:block; margin-bottom:6px;'>Απόφθεγμα της ημέρας</strong>"
            f"<div style='line-height:1.7;'>«{html.escape(str(quote.get('quote') or ''))}»</div>"
            f"{author_html}"
            "</div>"
        )

    def _send_smtp_message(
        self,
        settings: Settings,
        sender_address: str,
        recipients: list[str],
        subject: str,
        text_report: str,
        html_report: str,
    ) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((settings.email_from_name, sender_address))
        message["To"] = ", ".join(recipients)
        message.set_content(text_report)
        message.add_alternative(html_report, subtype="html")

        smtp_timeout = max(5, settings.smtp_timeout_seconds)
        if settings.smtp_use_ssl:
            smtp_client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=smtp_timeout,
                context=ssl.create_default_context(),
            )
        else:
            smtp_client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=smtp_timeout)

        with smtp_client as client:
            client.ehlo()
            if not settings.smtp_use_ssl and settings.smtp_use_tls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password or "")
            client.send_message(message)

    async def _send_resend_message(
        self,
        settings: Settings,
        sender_address: str,
        recipients: list[str],
        subject: str,
        text_report: str,
        html_report: str,
        *,
        idempotency_key: str,
    ) -> None:
        payload = {
            "from": formataddr((settings.email_from_name, sender_address)),
            "to": recipients,
            "subject": subject,
            "html": html_report,
            "text": text_report,
        }
        headers = {
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Idempotency-Key": idempotency_key,
        }
        timeout = max(5, settings.resend_timeout_seconds)
        base_url = settings.resend_api_base_url.rstrip("/")
        verify_config = _resend_verify_config(settings)
        try:
            async with httpx.AsyncClient(base_url=base_url, timeout=timeout, verify=verify_config, trust_env=True) as client:
                response = await client.post("/emails", json=payload, headers=headers)
        except Exception as exc:
            if settings.resend_allow_insecure_fallback and _is_tls_error(exc):
                async with httpx.AsyncClient(base_url=base_url, timeout=timeout, verify=False, trust_env=True) as client:
                    response = await client.post("/emails", json=payload, headers=headers)
            else:
                raise

        if response.status_code >= 400:
            raise EmailDeliveryError(f"Resend API failed ({response.status_code}): {self._extract_resend_error(response)}")

    def _extract_resend_error(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            preview = response.text.strip()
            return preview[:180] or "Unknown error"

        if isinstance(payload, dict):
            for key in ("message", "error", "name"):
                value = payload.get(key)
                if value:
                    return str(value)
        return str(payload)


def _paragraphs(raw: Any) -> list[str]:
    if not isinstance(raw, str):
        return []
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", raw.strip()) if paragraph.strip()]


def _bullets(raw: Any) -> list[str]:
    if not isinstance(raw, str):
        return []
    return [
        re.sub(r"^[-*•]\s*", "", line.strip())
        for line in raw.splitlines()
        if re.sub(r"^[-*•]\s*", "", line.strip())
    ]


def _fmt_number(value: Any, *, suffix: str = "") -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.0f}{suffix}"
    except (TypeError, ValueError):
        return f"{value}{suffix}"


def _resend_verify_config(settings: Settings) -> bool | str:
    if settings.resend_ca_bundle:
        return settings.resend_ca_bundle
    return settings.resend_ssl_verify


def _is_tls_error(exc: Exception | None) -> bool:
    if exc is None:
        return False
    lowered = str(exc).lower()
    return "certificate verify failed" in lowered or "ssl" in lowered or "tls" in lowered
