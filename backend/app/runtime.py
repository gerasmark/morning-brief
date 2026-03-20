from __future__ import annotations

import logging

from app.config import Settings
from app.seed_sources import seed as seed_sources


def _resolve_log_level(value: str, fallback: int) -> int:
    parsed = getattr(logging, value.strip().upper(), None)
    if isinstance(parsed, int):
        return parsed
    return fallback


def configure_logging(settings: Settings) -> None:
    root_level = _resolve_log_level(settings.log_level, logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=root_level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    logging.getLogger().setLevel(root_level)
    logging.getLogger("app").setLevel(_resolve_log_level(settings.app_log_level, root_level))

    httpx_level = _resolve_log_level(settings.httpx_log_level, logging.WARNING)
    logging.getLogger("httpx").setLevel(httpx_level)
    logging.getLogger("httpcore").setLevel(httpx_level)
    logging.getLogger("h11").setLevel(httpx_level)
    logging.getLogger("uvicorn.access").setLevel(
        _resolve_log_level(settings.uvicorn_access_log_level, logging.WARNING)
    )


async def bootstrap_data() -> None:
    await seed_sources()
