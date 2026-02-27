from __future__ import annotations

from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from app.config import Settings


class BirthdaysService:
    async def fetch_today(self, settings: Settings, day: date) -> dict:
        if day != datetime.now(settings.tzinfo).date():
            return {
                "provider": "eortologio.net",
                "day": str(day),
                "source_url": settings.birthdays_source_url,
                "names": [],
                "unavailable": False,
            }

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": "proino-briefing/1.0 (+personal-use)"},
                verify=_verify_config(settings),
                trust_env=True,
            ) as client:
                response = await client.get(settings.birthdays_source_url, timeout=20.0)
                response.raise_for_status()
        except Exception as exc:
            return {
                "provider": "eortologio.net",
                "day": str(day),
                "source_url": settings.birthdays_source_url,
                "names": [],
                "unavailable": True,
                "error": str(exc)[:280],
            }

        names = _extract_today_names(response.text, day.day)
        limited = names[: max(1, min(settings.birthdays_names_limit, 50))]
        return {
            "provider": "eortologio.net",
            "day": str(day),
            "source_url": settings.birthdays_source_url,
            "names": limited,
            "unavailable": not limited,
            "error": None if limited else "Δεν βρέθηκαν ονόματα για σήμερα.",
        }


def _extract_today_names(html: str, day_num: int) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table#table2 tr.row") + soup.select("table#table1 tr.row")
    fallback_row = None
    selected_row = None
    for row in rows:
        day_cell = row.find("td", attrs={"name": True})
        if day_cell is None:
            continue
        raw_day = str(day_cell.get("name", "")).strip()
        if not raw_day.isdigit() or int(raw_day) != day_num:
            continue
        if fallback_row is None:
            fallback_row = row
        week_day_cell = day_cell.find_next_sibling("td")
        if day_cell.find("b") or (week_day_cell and week_day_cell.find("b")):
            selected_row = row
            break

    target = selected_row or fallback_row
    if target is None:
        return []

    cells = target.find_all("td")
    if len(cells) < 3:
        return []
    names_cell = cells[2]
    anchors = names_cell.select("div.name a") or names_cell.select("a[href*='/pote_giortazei/']")
    seen: set[str] = set()
    names: list[str] = []
    for anchor in anchors:
        text = " ".join(anchor.get_text(" ", strip=True).split()).strip()
        if not text:
            continue
        text = text.rstrip("*").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        names.append(text)
    return names


def _verify_config(settings: Settings) -> bool | str:
    if settings.weather_ca_bundle:
        return settings.weather_ca_bundle
    return settings.weather_ssl_verify
