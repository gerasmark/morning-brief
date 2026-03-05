from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil.parser import isoparse

from app.config import Settings
from app.llm.router import get_provider
from app.utils.text import canonicalize_url, truncate_snippet


@dataclass
class StrikeTagSource:
    name: str
    tag_url: str


@dataclass
class StrikeCandidate:
    id: str
    source: str
    source_tag_url: str
    title: str
    url: str
    snippet: str | None
    published_at: datetime | None
    score: float
    summary_md: str


def _source_name_for_domain(domain: str) -> str:
    host = domain.lower().replace("www.", "")
    mapping = {
        "naftemporiki.gr": "Ναυτεμπορική",
        "newsbomb.gr": "Newsbomb",
        "kathimerini.gr": "Καθημερινή",
        "protothema.gr": "Πρώτο Θέμα",
        "tanea.gr": "ΤΑ ΝΕΑ",
        "iefimerida.gr": "iefimerida",
        "news247.gr": "News247",
    }
    for key, value in mapping.items():
        if host.endswith(key):
            return value
    return host


def _candidate_id(url: str) -> str:
    return f"strike-feed:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}"


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


def _relevance_score(title: str, snippet: str | None) -> float:
    payload = f"{title} {snippet or ''}".lower()
    score = 0.3
    if "απεργ" in payload:
        score += 0.6
    if any(item in payload for item in ["μετρό", "λεωφορεί", "τραμ", "πλο", "προαστια"]):
        score += 0.2
    if any(item in payload for item in ["στάση εργασίας", "κινητοποίηση", "γσεε", "αδεδυ"]):
        score += 0.2
    return min(score, 1.0)


def _default_summary(title: str, source: str) -> str:
    return f"{title}\nΠηγές: {source}"


def _build_tag_sources(settings: Settings) -> list[StrikeTagSource]:
    urls = [item.strip() for item in settings.strike_tag_urls.split(",") if item.strip()]
    sources: list[StrikeTagSource] = []
    for raw_url in urls:
        url = _normalize_tag_url(raw_url)
        if not url:
            continue
        domain = urlparse(url).netloc
        sources.append(StrikeTagSource(name=_source_name_for_domain(domain), tag_url=url))
    return sources


class StrikeFeedService:
    async def fetch_cards(self, settings: Settings, limit: int | None = None) -> list[dict]:
        sources = _build_tag_sources(settings)
        if not sources:
            return []

        candidates: list[StrikeCandidate] = []
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "proino-briefing/1.0 (+personal-use)"},
            verify=_verify_config(settings),
            trust_env=True,
        ) as client:
            for source in sources:
                rows, _ = await self._fetch_source_with_retry(client, source, settings)
                candidates.extend(rows)

        normalized = self._normalize_candidates(candidates)
        if settings.strike_feed_use_llm and normalized:
            await self._apply_llm_summaries(settings, normalized)

        effective_limit = limit if limit is not None else settings.strike_feed_limit
        ordered = sorted(
            normalized,
            key=lambda item: (
                item.published_at or datetime.min.replace(tzinfo=timezone.utc),
                item.score,
            ),
            reverse=True,
        )
        selected = _select_diverse_by_source(ordered, effective_limit)
        return [self._to_card(item) for item in selected]

    async def fetch_debug(self, settings: Settings, limit: int = 200) -> dict:
        sources = _build_tag_sources(settings)
        if not sources:
            return {"status": "ok", "sources": [], "count": 0, "items": []}

        candidates: list[StrikeCandidate] = []
        source_debug: list[dict] = []
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "proino-briefing/1.0 (+personal-use)"},
            verify=_verify_config(settings),
            trust_env=True,
        ) as client:
            for source in sources:
                rows, debug = await self._fetch_source_with_retry(client, source, settings)
                candidates.extend(rows)
                source_debug.append(debug)

        normalized = self._normalize_candidates(candidates)
        if settings.strike_feed_use_llm and normalized:
            await self._apply_llm_summaries(settings, normalized)

        raw_ordered = sorted(
            candidates,
            key=lambda item: (
                item.published_at or datetime.min.replace(tzinfo=timezone.utc),
                item.score,
            ),
            reverse=True,
        )
        ordered = sorted(
            normalized,
            key=lambda item: (
                item.published_at or datetime.min.replace(tzinfo=timezone.utc),
                item.score,
            ),
            reverse=True,
        )
        selected = _select_diverse_by_source(ordered, limit)
        cards = [self._to_card(item) for item in selected]

        by_source: dict[str, int] = {}
        for item in cards:
            source_name = str(item.get("source", "unknown"))
            by_source[source_name] = by_source.get(source_name, 0) + 1

        raw_items = [
            {
                "id": item.id,
                "source": item.source,
                "title": item.title,
                "url": item.url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "score": item.score,
            }
            for item in raw_ordered[:limit]
        ]

        return {
            "status": "ok",
            "source_debug": source_debug,
            "raw_candidate_count": len(candidates),
            "deduped_count": len(normalized),
            "count": len(cards),
            "counts_by_source": by_source,
            "raw_items": raw_items,
            "items": cards,
        }

    async def _fetch_source(
        self, client: httpx.AsyncClient, source: StrikeTagSource
    ) -> tuple[list[StrikeCandidate], dict]:
        rss_url = source.tag_url.rstrip("/") + "/feed"
        rss_rows, rss_error = await self._fetch_rss(client, source, rss_url)
        if rss_rows:
            debug = {
                "source": source.name,
                "tag_url": source.tag_url,
                "rss_url": rss_url,
                "mode_used": "rss",
                "rss_count": len(rss_rows),
                "html_count": 0,
                "rss_error": rss_error,
                "html_error": None,
            }
            return rss_rows, debug

        html_rows, html_error = await self._fetch_html(client, source)
        debug = {
            "source": source.name,
            "tag_url": source.tag_url,
            "rss_url": rss_url,
            "mode_used": "html" if html_rows else "none",
            "rss_count": 0,
            "html_count": len(html_rows),
            "rss_error": rss_error,
            "html_error": html_error,
        }
        return html_rows, debug

    async def _fetch_source_with_retry(
        self, client: httpx.AsyncClient, source: StrikeTagSource, settings: Settings
    ) -> tuple[list[StrikeCandidate], dict]:
        rows, debug = await self._fetch_source(client, source)
        if rows:
            return rows, debug
        if not settings.weather_allow_insecure_fallback:
            return rows, debug
        if not _has_tls_error(debug):
            return rows, debug

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "proino-briefing/1.0 (+personal-use)"},
            verify=False,
            trust_env=True,
        ) as insecure_client:
            insecure_rows, insecure_debug = await self._fetch_source(insecure_client, source)

        if insecure_rows:
            merged = {
                **insecure_debug,
                "tls_warning": "Fetched with SSL verification disabled fallback.",
                "secure_attempt": debug,
            }
            return insecure_rows, merged
        debug["insecure_retry_failed"] = insecure_debug
        return rows, debug

    async def _fetch_rss(
        self,
        client: httpx.AsyncClient,
        source: StrikeTagSource,
        rss_url: str,
    ) -> tuple[list[StrikeCandidate], str | None]:
        try:
            response = await client.get(rss_url, timeout=20.0)
            if response.status_code >= 400:
                return [], f"HTTP {response.status_code}"
            parsed = feedparser.parse(response.text)
        except Exception as exc:
            return [], str(exc)[:220]

        rows: list[StrikeCandidate] = []
        for entry in parsed.entries:
            title = str(entry.get("title", "")).strip()
            link = str(entry.get("link", "")).strip()
            if not title or not link:
                continue
            canonical = canonicalize_url(link)
            snippet = truncate_snippet(
                str(entry.get("summary") or entry.get("description") or "").strip() or None,
                max_len=300,
            )
            published = _parse_datetime(str(entry.get("published") or entry.get("updated") or ""))
            rows.append(
                StrikeCandidate(
                    id=_candidate_id(canonical),
                    source=source.name,
                    source_tag_url=source.tag_url,
                    title=title,
                    url=canonical,
                    snippet=snippet,
                    published_at=published,
                    score=_relevance_score(title, snippet),
                    summary_md=_default_summary(title, source.name),
                )
            )
        return rows, None

    async def _fetch_html(
        self, client: httpx.AsyncClient, source: StrikeTagSource
    ) -> tuple[list[StrikeCandidate], str | None]:
        try:
            response = await client.get(source.tag_url, timeout=20.0)
            response.raise_for_status()
        except Exception as exc:
            return [], str(exc)[:220]

        soup = BeautifulSoup(response.text, "html.parser")
        rows: list[StrikeCandidate] = []
        seen: set[str] = set()
        source_host = urlparse(source.tag_url).netloc.lower().replace("www.", "")
        selectors = [
            "article h1 a[href]",
            "article h2 a[href]",
            "article h3 a[href]",
            "h2 a[href]",
            "h3 a[href]",
        ]

        for selector in selectors:
            for anchor in soup.select(selector):
                href = str(anchor.get("href") or "").strip()
                title = anchor.get_text(" ", strip=True)
                if not href or not title or len(title) < 18:
                    continue
                url = canonicalize_url(urljoin(source.tag_url, href))
                parsed = urlparse(url)
                candidate_host = parsed.netloc.lower().replace("www.", "")
                if candidate_host and candidate_host != source_host:
                    continue
                if "/tag/apergia" in url or "/page/" in url:
                    continue
                if url in seen:
                    continue
                seen.add(url)
                snippet = truncate_snippet(str(anchor.get("title") or "").strip() or None, max_len=220)
                rows.append(
                    StrikeCandidate(
                        id=_candidate_id(url),
                        source=source.name,
                        source_tag_url=source.tag_url,
                        title=title,
                        url=url,
                        snippet=snippet,
                        published_at=_extract_date_from_url(url),
                        score=_relevance_score(title, snippet),
                        summary_md=_default_summary(title, source.name),
                    )
                )
                if len(rows) >= 60:
                    return rows, None
        return rows, None

    def _normalize_candidates(self, candidates: list[StrikeCandidate]) -> list[StrikeCandidate]:
        seen_urls: set[str] = set()
        output: list[StrikeCandidate] = []
        for item in sorted(
            candidates,
            key=lambda row: (
                row.published_at or datetime.min.replace(tzinfo=timezone.utc),
                row.score,
            ),
            reverse=True,
        ):
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            output.append(item)
        return output

    async def _apply_llm_summaries(self, settings: Settings, candidates: list[StrikeCandidate]) -> None:
        provider = get_provider(settings)
        model = settings.llm_model
        limited = candidates[: min(len(candidates), settings.strike_feed_limit * 2)]

        payload = [
            {
                "id": item.id,
                "source": item.source,
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
            }
            for item in limited
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "Είσαι επιμελητής ενότητας απεργιών. Επέστρεψε μόνο έγκυρο JSON array "
                    "με αντικείμενα {id, summary_md, relevance}."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Από τα παρακάτω θέματα επίλεξε τα πιο ουσιαστικά (έως 12) και γράψε σύντομη "
                    "ελληνική περίληψη 1-2 bullets ανά θέμα. Κάθε summary_md να τελειώνει με "
                    "'Πηγές: <όνομα>'.\n\n"
                    + json.dumps(payload, ensure_ascii=False)
                ),
            },
        ]

        try:
            response = await provider.generate(messages=messages, model=model, temperature=0.1, max_tokens=1200)
            parsed = _parse_llm_json_array(response)
        except Exception:
            return

        by_id = {item.id: item for item in candidates}
        for row in parsed:
            item_id = str(row.get("id", "")).strip()
            if not item_id or item_id not in by_id:
                continue
            summary = str(row.get("summary_md", "")).strip()
            if summary:
                by_id[item_id].summary_md = summary
            try:
                relevance = float(row.get("relevance", by_id[item_id].score))
                by_id[item_id].score = max(0.0, min(relevance, 1.0))
            except (TypeError, ValueError):
                continue

    def _to_card(self, item: StrikeCandidate) -> dict:
        return {
            "id": item.id,
            "score": item.score,
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "snippet": item.snippet,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "topics": ["Απεργίες", "Μετακινήσεις"],
            "is_strike_related": True,
            "summary_md": "",
            "sources": [
                {
                    "article_id": item.id,
                    "title": item.title,
                    "url": item.url,
                    "source": item.source,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                }
            ],
        }


def _extract_date_from_url(url: str) -> datetime | None:
    # Many Greek news URLs include /YYYY/MM/DD/ segments.
    match = re.search(r"/(20\d{2})/(\d{1,2})/(\d{1,2})/", url)
    if not match:
        return None
    try:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_llm_json_array(text: str) -> list[dict]:
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines).strip()
    start = body.find("[")
    end = body.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    sliced = body[start : end + 1]
    parsed = json.loads(sliced)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _normalize_tag_url(url: str) -> str | None:
    cleaned = url.strip().strip("\"' ")
    cleaned = cleaned.replace("https://https://", "https://")
    cleaned = cleaned.replace("http://http://", "http://")
    cleaned = cleaned.replace("http://https://", "https://")
    cleaned = cleaned.replace("https://http://", "http://")
    if not cleaned:
        return None
    if not re.match(r"^https?://", cleaned, flags=re.IGNORECASE):
        cleaned = "https://" + cleaned.lstrip("/")
    parsed = urlparse(cleaned)
    if not parsed.netloc:
        return None
    return cleaned


def _verify_config(settings: Settings) -> bool | str:
    if settings.weather_ca_bundle:
        return settings.weather_ca_bundle
    return settings.weather_ssl_verify


def _has_tls_error(debug: dict) -> bool:
    values = [str(debug.get("rss_error") or ""), str(debug.get("html_error") or "")]
    payload = " ".join(values).lower()
    return "certificate verify failed" in payload or "ssl" in payload


def _select_diverse_by_source(items: list[StrikeCandidate], limit: int) -> list[StrikeCandidate]:
    if limit <= 0:
        return []
    if not items:
        return []

    by_source: dict[str, list[StrikeCandidate]] = {}
    source_order: list[str] = []
    for item in items:
        if item.source not in by_source:
            by_source[item.source] = []
            source_order.append(item.source)
        by_source[item.source].append(item)

    selected: list[StrikeCandidate] = []
    idx = 0
    while len(selected) < limit:
        progressed = False
        for source in source_order:
            bucket = by_source[source]
            if idx < len(bucket):
                selected.append(bucket[idx])
                progressed = True
                if len(selected) >= limit:
                    break
        if not progressed:
            break
        idx += 1

    return selected
