from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.services.keywords import GREEK_STOPWORDS

_TRACKING_PARAMS = {
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    host = parsed.netloc.lower()
    params = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        key = k.lower()
        if key.startswith("utm_") or key in _TRACKING_PARAMS:
            continue
        params.append((k, v))
    query = urlencode(params, doseq=True)
    cleaned = parsed._replace(scheme=scheme, netloc=host, query=query, fragment="")
    return urlunparse(cleaned)


def normalize_title(title: str) -> str:
    text = re.sub(r"[^\w\sάέήίόύώϊϋΐΰ]", " ", title.lower(), flags=re.UNICODE)
    tokens = [tok for tok in text.split() if tok and tok not in GREEK_STOPWORDS]
    return " ".join(tokens)


def fingerprint_from(title: str, url: str) -> str:
    domain = urlparse(url).netloc.lower()
    base = f"{normalize_title(title)}|{domain}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def cluster_key(article_fingerprints: list[str]) -> str:
    payload = "|".join(sorted(article_fingerprints))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def truncate_snippet(text: str | None, max_len: int = 500) -> str | None:
    if not text:
        return None
    squashed = re.sub(r"\s+", " ", text).strip()
    if len(squashed) <= max_len:
        return squashed
    return f"{squashed[: max_len - 1].rstrip()}…"


def token_set(text: str) -> set[str]:
    return set(normalize_title(text).split())
