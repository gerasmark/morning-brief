from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from xml.etree import ElementTree

import feedparser
import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from dateutil.parser import isoparse


@dataclass
class RawItem:
    title: str
    url: str
    published_at: datetime | None
    snippet: str | None
    raw: dict[str, Any] | None = None


class RSSFetcher:
    async def fetch(self, client: httpx.AsyncClient, feed_url: str) -> list[RawItem]:
        response = await client.get(feed_url, timeout=20.0)
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
        items: list[RawItem] = []
        for entry in parsed.entries:
            title = str(entry.get("title", "")).strip()
            link = str(entry.get("link", "")).strip()
            if not title or not link:
                continue
            published = _parse_feed_datetime(entry)
            snippet = entry.get("summary") or entry.get("description")
            items.append(
                RawItem(
                    title=title,
                    url=link,
                    published_at=published,
                    snippet=str(snippet).strip() if snippet else None,
                    raw={
                        "id": entry.get("id"),
                        "tags": [t.get("term") for t in entry.get("tags", []) if isinstance(t, dict)],
                    },
                )
            )
        return items


class NaftemporikiMainFeedFetcher:
    def __init__(self, rss_fetcher: RSSFetcher | None = None) -> None:
        self.rss_fetcher = rss_fetcher or RSSFetcher()

    async def fetch(
        self,
        client: httpx.AsyncClient,
        homepage_url: str,
        feed_url: str,
        feed_limit: int = 10,
    ) -> list[RawItem]:
        homepage_items = await self._fetch_homepage_main_items(client, homepage_url)
        feed_items = await self.rss_fetcher.fetch(client, feed_url)
        limited_feed = [_mark_naft_feed_item(item) for item in feed_items[: max(feed_limit, 0)]]
        return _merge_raw_items(homepage_items, limited_feed)

    async def _fetch_homepage_main_items(
        self, client: httpx.AsyncClient, homepage_url: str
    ) -> list[RawItem]:
        response = await client.get(homepage_url, timeout=20.0)
        response.raise_for_status()
        return _parse_naftemporiki_homepage_main(response.text, homepage_url)


class SitemapFetcher:
    async def fetch(self, client: httpx.AsyncClient, sitemap_url: str) -> list[RawItem]:
        visited: set[str] = set()
        url_queue = [sitemap_url]
        items: list[RawItem] = []
        while url_queue:
            current = url_queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            response = await client.get(current, timeout=20.0)
            response.raise_for_status()
            if _looks_like_json(response):
                posts, next_pages = _parse_wp_json_posts(response.text, current, response.headers)
                items.extend(posts)
                for next_page in next_pages:
                    if next_page not in visited:
                        url_queue.append(next_page)
                continue

            root = ElementTree.fromstring(response.content)
            ns = _namespaces(root)
            tag = _local_name(root.tag)
            if tag == "sitemapindex":
                for node in root.findall("sm:sitemap", ns) or root.findall("sitemap"):
                    loc = _find_text(node, ["sm:loc", "loc"], ns)
                    if loc:
                        url_queue.append(loc)
                continue

            for node in root.findall("sm:url", ns) or root.findall("url"):
                loc = _find_text(node, ["sm:loc", "loc"], ns)
                if not loc:
                    continue
                title = _find_text(node, ["news:news/news:title"], ns) or loc
                pub = _find_text(node, ["news:news/news:publication_date", "sm:lastmod", "lastmod"], ns)
                published_at = _parse_datetime(pub)
                items.append(
                    RawItem(
                        title=title.strip(),
                        url=loc.strip(),
                        published_at=published_at,
                        snippet=None,
                        raw={"lastmod": _find_text(node, ["sm:lastmod", "lastmod"], ns)},
                    )
                )
        return items


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _namespaces(root: ElementTree.Element) -> dict[str, str]:
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
    }
    if root.tag.startswith("{"):
        default_ns = root.tag.split("}", 1)[0].strip("{")
        ns.setdefault("default", default_ns)
    return ns


def _find_text(node: ElementTree.Element, paths: list[str], namespaces: dict[str, str]) -> str | None:
    for path in paths:
        found = node.find(path, namespaces)
        if found is not None and found.text:
            return found.text
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = isoparse(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (TypeError, ValueError):
            return None


def _parse_feed_datetime(entry: Any) -> datetime | None:
    for field in ("published", "updated"):
        raw = entry.get(field)
        parsed = _parse_datetime(raw)
        if parsed:
            return parsed

    for field in ("published_parsed", "updated_parsed"):
        structured = entry.get(field)
        if structured:
            try:
                return datetime(*structured[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def _looks_like_json(response: httpx.Response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        return True
    stripped = response.text.lstrip()
    return stripped.startswith("[") or stripped.startswith("{")


def _parse_wp_json_posts(
    payload: str, current_url: str, headers: httpx.Headers
) -> tuple[list[RawItem], list[str]]:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        return [], []
    if not isinstance(raw, list):
        return [], []

    items: list[RawItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        link = str(entry.get("link") or "").strip()
        title_obj = entry.get("title")
        excerpt_obj = entry.get("excerpt")
        if isinstance(title_obj, dict):
            title = str(title_obj.get("rendered") or "").strip()
        else:
            title = str(title_obj or "").strip()
        if isinstance(excerpt_obj, dict):
            snippet = _strip_html(excerpt_obj.get("rendered"))
        else:
            snippet = _strip_html(excerpt_obj)
        if not title or not link:
            continue

        published_at = _parse_datetime(
            str(entry.get("date_gmt") or entry.get("date") or "").strip() or None
        )
        items.append(
            RawItem(
                title=title,
                url=link,
                published_at=published_at,
                snippet=snippet,
                raw={"id": entry.get("id"), "source": "wp-json"},
            )
        )

    total_pages_raw = headers.get("x-wp-totalpages")
    next_pages: list[str] = []
    if total_pages_raw and total_pages_raw.isdigit():
        total_pages = min(max(int(total_pages_raw), 1), 5)
        current_page = _query_page(current_url)
        for page in range(current_page + 1, total_pages + 1):
            next_pages.append(_with_query_page(current_url, page))
    return items, next_pages


def _strip_html(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = unescape(text)
    text = " ".join(text.split())
    return text or None


def _query_page(url: str) -> int:
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    page = params.get("page")
    if page and page.isdigit():
        return max(int(page), 1)
    return 1


def _with_query_page(url: str, page: int) -> str:
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["page"] = str(page)
    query = urlencode(params, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


def _parse_naftemporiki_homepage_main(html: str, homepage_url: str) -> list[RawItem]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if main is None:
        return []

    target_count = 20
    items: list[RawItem] = []
    seen_keys: set[str] = set()
    newsroom_heading: Tag | None = None
    for heading in main.find_all(["h1", "h2", "h3", "h4"]):
        title = " ".join(heading.get_text(" ", strip=True).split())
        if not title:
            continue
        if title.casefold() == "newsroom":
            newsroom_heading = heading
            break

        anchor = heading.find("a", href=True)
        if anchor is None and heading.parent is not None:
            anchor = heading.parent.find("a", href=True)
        if anchor is None:
            continue

        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(homepage_url, href)
        url_key = _article_url_key(url)
        if url_key is None or url_key in seen_keys:
            continue

        seen_keys.add(url_key)
        items.append(
            RawItem(
                title=title,
                url=url,
                published_at=datetime.now(timezone.utc),
                snippet=None,
                raw={"source": "naftemporiki-homepage-main", "position": len(items) + 1},
            )
        )
        if len(items) >= target_count:
            return items

    for node in main.descendants:
        if node is newsroom_heading:
            break
        if not isinstance(node, Tag) or node.name != "a":
            continue
        href = str(node.get("href") or "").strip()
        if not href:
            continue
        title = " ".join(node.get_text(" ", strip=True).split())
        if not title:
            continue
        url = urljoin(homepage_url, href)
        url_key = _article_url_key(url)
        if url_key is None or url_key in seen_keys:
            continue

        seen_keys.add(url_key)
        items.append(
            RawItem(
                title=title,
                url=url,
                published_at=datetime.now(timezone.utc),
                snippet=None,
                raw={"source": "naftemporiki-homepage-main", "position": len(items) + 1},
            )
        )
        if len(items) >= target_count:
            break
    return items


def _article_url_key(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    if host != "naftemporiki.gr":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    normalized_path = "/" + "/".join(parts)
    return f"{host}{normalized_path}"


def _merge_raw_items(primary: list[RawItem], secondary: list[RawItem]) -> list[RawItem]:
    merged: dict[str, RawItem] = {}
    order: list[str] = []
    for item in [*primary, *secondary]:
        key = _article_url_key(item.url)
        if key is None:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            order.append(key)
            continue
        existing_source = _raw_source(existing)
        new_source = _raw_source(item)
        if existing_source == "naftemporiki-homepage-main" and new_source == "naftemporiki-feed":
            # Track overlap so consumers can prioritize "homepage-only" stories first.
            if _raw_item_richness(item) > _raw_item_richness(existing):
                combined_raw = dict(item.raw or {})
                combined_raw["also_on_homepage"] = True
                homepage_position = (existing.raw or {}).get("position")
                if isinstance(homepage_position, int):
                    combined_raw["homepage_position"] = homepage_position
                merged[key] = RawItem(
                    title=item.title,
                    url=item.url,
                    published_at=item.published_at,
                    snippet=item.snippet,
                    raw=combined_raw,
                )
            else:
                combined_raw = dict(existing.raw or {})
                combined_raw["also_in_feed"] = True
                merged[key] = RawItem(
                    title=existing.title,
                    url=existing.url,
                    published_at=existing.published_at,
                    snippet=existing.snippet,
                    raw=combined_raw,
                )
            continue
        if _raw_item_richness(item) > _raw_item_richness(existing):
            merged[key] = item
    return [merged[key] for key in order]


def _mark_naft_feed_item(item: RawItem) -> RawItem:
    raw = dict(item.raw or {})
    raw["source"] = "naftemporiki-feed"
    return RawItem(
        title=item.title,
        url=item.url,
        published_at=item.published_at,
        snippet=item.snippet,
        raw=raw,
    )


def _raw_source(item: RawItem) -> str | None:
    if not item.raw:
        return None
    raw_source = item.raw.get("source")
    if isinstance(raw_source, str) and raw_source:
        return raw_source
    return None


def _raw_item_richness(item: RawItem) -> int:
    score = 0
    if item.published_at is not None:
        score += 2
    if item.snippet:
        score += 1
    if item.raw:
        score += 1
    return score
