from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.config import Settings

logger = logging.getLogger(__name__)
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"

_QUOTE_LABEL_RE = re.compile(
    r"^(?:η\s+)?(?:απόφθεγμα|παροιμία|ρητό|φράση)\s+της\s+ημέρας(?:\s+είναι)?\s*[:：-]\s*",
    flags=re.IGNORECASE,
)
_QUOTED_WITH_AUTHOR_RE = re.compile(
    r"[«\"“](?P<quote>[^»\"”]{8,320})[»\"”]\s*(?:--|—|–|-)\s*(?P<author>[^|]{2,120})$"
)
_QUOTE_WITH_AUTHOR_RE = re.compile(
    r"(?P<quote>.{8,320}?)\s*(?:--|—|–|-)\s*(?P<author>[A-Za-zΑ-ΩΆΈΉΊΌΎΏΪΫα-ωάέήίόύώϊϋΐΰ0-9 .,'’`-]{2,120})$"
)
_QUOTED_ONLY_RE = re.compile(r"[«\"“](?P<quote>[^»\"”]{8,320})[»\"”]$")


class QuoteOfDayService:
    async def fetch_for_day(self, settings: Settings, day: date) -> dict:
        source_url = _with_date_param(settings.quote_of_day_source_url, day)
        ajax_url = _ajax_url_from_source(source_url)
        sse = _sse_for_day(day)
        provider = urlsplit(source_url).netloc.lower().replace("www.", "")
        logger.info("Quote-of-day fetch start day=%s source_url=%s ajax_url=%s sse=%s", day, source_url, ajax_url, sse)

        quote: str | None = None
        author: str | None = None

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={
                    "User-Agent": BROWSER_UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": source_url,
                },
                verify=_verify_config(settings),
                trust_env=True,
            ) as client:
                ajax_response = await client.post(
                    ajax_url,
                    data={"PhraseType": "P", "SSE": str(sse)},
                    timeout=20.0,
                )
                ajax_response.raise_for_status()
                logger.info(
                    "Quote-of-day ajax http_ok day=%s status=%s bytes=%d",
                    day,
                    ajax_response.status_code,
                    len(ajax_response.text),
                )
                quote, author = _extract_from_ajax_payload(ajax_response.text)

                if not quote:
                    logger.warning("Quote-of-day ajax parse failed day=%s source_url=%s reason=no_quote_in_ajax", day, source_url)
                    html_response = await client.get(source_url, timeout=20.0)
                    html_response.raise_for_status()
                    logger.info(
                        "Quote-of-day html fallback http_ok day=%s status=%s bytes=%d",
                        day,
                        html_response.status_code,
                        len(html_response.text),
                    )
                    quote, author = _extract_quote_and_author(html_response.text)
        except Exception as exc:
            logger.warning("Quote-of-day fetch failed day=%s source_url=%s error=%s", day, source_url, exc)
            return {
                "provider": provider or "lexigram.gr",
                "day": str(day),
                "source_url": source_url,
                "quote": None,
                "author": None,
                "unavailable": True,
                "error": str(exc)[:280],
            }

        if not quote:
            logger.warning("Quote-of-day parse failed day=%s source_url=%s reason=no_quote_found", day, source_url)
            return {
                "provider": provider or "lexigram.gr",
                "day": str(day),
                "source_url": source_url,
                "quote": None,
                "author": None,
                "unavailable": True,
                "error": "Δεν βρέθηκε απόφθεγμα για τη μέρα.",
            }

        logger.info(
            "Quote-of-day ready day=%s author=%s quote_chars=%d quote_preview=%s",
            day,
            author or "-",
            len(quote),
            _short_for_log(quote),
        )
        return {
            "provider": provider or "lexigram.gr",
            "day": str(day),
            "source_url": source_url,
            "quote": quote,
            "author": author,
            "unavailable": False,
            "error": None,
        }


def _extract_quote_and_author(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidate_selectors = (
        "blockquote",
        "q",
        "[id*='paroim']",
        "[class*='paroim']",
        "[id*='apofthegm']",
        "[class*='apofthegm']",
        "[id*='quote']",
        "[class*='quote']",
        "article p",
        "main p",
        "td",
        "p",
    )

    candidates: list[str] = []
    for selector in candidate_selectors:
        for node in soup.select(selector):
            text = _normalize_text(node.get_text(" ", strip=True))
            if _looks_like_quote_candidate(text):
                candidates.append(text)

    if not candidates:
        for fragment in soup.stripped_strings:
            text = _normalize_text(fragment)
            if _looks_like_quote_candidate(text):
                candidates.append(text)

    for candidate in _unique_keep_order(candidates):
        parsed = _parse_quote_candidate(candidate)
        if parsed:
            return parsed

    # Last-resort fallback for pages that keep everything in a single text blob.
    page_text = _normalize_text(soup.get_text(" ", strip=True))
    parsed = _parse_quote_candidate(page_text)
    if parsed:
        return parsed
    return None, None


def _parse_quote_candidate(raw_text: str) -> tuple[str, str | None] | None:
    text = _normalize_text(raw_text)
    if not text:
        return None

    text = _QUOTE_LABEL_RE.sub("", text).strip()
    if not text:
        return None

    match = _QUOTED_WITH_AUTHOR_RE.search(text)
    if match:
        quote = _clean_quote(match.group("quote"))
        author = _clean_author(match.group("author"))
        if quote:
            return quote, author

    match = _QUOTE_WITH_AUTHOR_RE.search(text)
    if match:
        quote = _clean_quote(match.group("quote"))
        author = _clean_author(match.group("author"))
        if quote:
            return quote, author

    match = _QUOTED_ONLY_RE.search(text)
    if match:
        quote = _clean_quote(match.group("quote"))
        if quote:
            return quote, None

    lowered = text.casefold()
    if (
        20 <= len(text) <= 220
        and text.count(" ") >= 3
        and "http" not in lowered
        and "lexigram" not in lowered
        and "copyright" not in lowered
    ):
        quote = _clean_quote(text)
        if quote:
            return quote, None

    return None


def _looks_like_quote_candidate(text: str) -> bool:
    if len(text) < 16 or len(text) > 460:
        return False
    lowered = text.casefold()
    if any(
        phrase in lowered
        for phrase in ("απόφθεγμα της ημέρας", "παροιμία της ημέρας", "ρητό της ημέρας", "φράση της ημέρας")
    ):
        return True
    return any(marker in text for marker in (" -- ", "--", "—", " – ", "«", "»"))


def _clean_quote(value: str) -> str:
    quote = _normalize_text(value).strip(" \"'«»“”")
    quote = quote.strip()
    if len(quote) < 8 or len(quote) > 340:
        return ""
    return quote


def _clean_author(value: str | None) -> str | None:
    if not value:
        return None
    author = _normalize_text(value).strip(" -–—|,.;:()[]{}")
    if not author or len(author) > 120:
        return None
    if "http" in author.casefold():
        return None
    return author


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _with_date_param(base_url: str, day: date) -> str:
    split = urlsplit(base_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query["date"] = day.isoformat()
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def _verify_config(settings: Settings) -> bool | str:
    if settings.weather_ca_bundle:
        return settings.weather_ca_bundle
    return settings.weather_ssl_verify


def _short_for_log(text: str, limit: int = 80) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _ajax_url_from_source(source_url: str) -> str:
    split = urlsplit(source_url)
    base_path = split.path.rsplit("/", 1)[0] + "/"
    return urlunsplit((split.scheme, split.netloc, urljoin(base_path, "ajaxGetFrasiImeras.php"), "", ""))


def _sse_for_day(day: date) -> int:
    # Lexigram accepts SSE as epoch seconds around 00:00:01 UTC for the target date.
    dt = datetime(day.year, day.month, day.day, 0, 0, 1, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _extract_from_ajax_payload(payload: str) -> tuple[str | None, str | None]:
    text = payload.strip()
    if not text:
        return None, None
    parts = text.split("<split>")
    if len(parts) < 5:
        return None, None
    quote = _clean_quote(parts[3] or "")
    author = _clean_author(parts[4] or "")
    if not quote:
        return None, None
    return quote, author
