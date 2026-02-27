from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Source, SourceType

SEED_SOURCES = [
    {
        "name": "ΤΑ ΝΕΑ",
        "base_url": "https://www.tanea.gr",
        "type": SourceType.rss,
        "feed_url": "https://www.tanea.gr/feed/",
        "sitemap_url": None,
        "weight": 1.0,
    },
    {
        "name": "Ναυτεμπορική",
        "base_url": "https://www.naftemporiki.gr",
        "type": SourceType.rss,
        "feed_url": "https://www.naftemporiki.gr/feed/",
        "sitemap_url": None,
        "weight": 1.0,
    },
    {
        "name": "iefimerida",
        "base_url": "https://www.iefimerida.gr",
        "type": SourceType.rss,
        "feed_url": "https://www.iefimerida.gr/rss.xml",
        "sitemap_url": None,
        "weight": 1.0,
    },
    {
        "name": "News247",
        "base_url": "https://www.news247.gr",
        "type": SourceType.sitemap,
        "feed_url": None,
        "sitemap_url": "https://www.news247.gr/wp-json/wp/v2/posts?per_page=100&_fields=link,date_gmt,title,excerpt",
        "weight": 1.0,
    },
    {
        "name": "Newsbomb",
        "base_url": "https://www.newsbomb.gr",
        "type": SourceType.sitemap,
        "feed_url": None,
        "sitemap_url": "https://www.newsbomb.gr/google-news",
        "weight": 1.0,
    },
    {
        "name": "Πρώτο Θέμα",
        "base_url": "https://www.protothema.gr",
        "type": SourceType.rss,
        "feed_url": "https://www.protothema.gr/rss/",
        "sitemap_url": None,
        "weight": 1.0,
    },
]


async def seed() -> None:
    await init_db()
    async with SessionLocal() as session:
        kathimerini = (
            await session.execute(select(Source).where(Source.name == "Καθημερινή"))
        ).scalars().first()
        if kathimerini is not None:
            await session.delete(kathimerini)
            await session.commit()

        existing_sources = list((await session.execute(select(Source))).scalars().all())
        existing_by_name = {source.name: source for source in existing_sources}
        for item in SEED_SOURCES:
            existing_source = existing_by_name.get(item["name"])
            if existing_source is not None:
                changed = False
                if existing_source.base_url != item["base_url"]:
                    existing_source.base_url = item["base_url"]
                    changed = True
                if existing_source.type != item["type"]:
                    existing_source.type = item["type"]
                    changed = True
                if existing_source.feed_url != item["feed_url"]:
                    existing_source.feed_url = item["feed_url"]
                    changed = True
                if existing_source.sitemap_url != item["sitemap_url"]:
                    existing_source.sitemap_url = item["sitemap_url"]
                    changed = True
                if existing_source.weight != item["weight"]:
                    existing_source.weight = item["weight"]
                    changed = True
                if changed:
                    session.add(existing_source)
                continue
            session.add(
                Source(
                    name=item["name"],
                    base_url=item["base_url"],
                    type=item["type"],
                    feed_url=item["feed_url"],
                    sitemap_url=item["sitemap_url"],
                    enabled=True,
                    weight=item["weight"],
                )
            )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
