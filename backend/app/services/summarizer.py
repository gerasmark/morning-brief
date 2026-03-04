from __future__ import annotations

import logging
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.llm.router import get_provider
from app.llm.providers.groq_provider import GroqProvider
from app.models import Article, Cluster, ClusterArticle, DailyTopSummary, Summary

SYSTEM_PROMPT = "Είσαι συντάκτης πρωινής ενημέρωσης. Γράφεις σύντομα, ουδέτερα, χωρίς υπερβολές."
DAILY_TOP_SYSTEM_PROMPT = (
    "Είσαι έμπειρος συντάκτης πρωινής ενημέρωσης. "
    "Γράφεις σύντομη, καθαρή και ουδέτερη σύνοψη στα Ελληνικά, που διαβάζεται φυσικά και ευχάριστα. "
    "Χρησιμοποίησε πλήρεις προτάσεις με ομαλή ροή, χωρίς bullets και χωρίς το σύμβολο ';'."
)
GEMINI_PROVIDER_ALIASES = {"gemini", "google"}
logger = logging.getLogger(__name__)


async def ensure_cluster_summary(
    session: AsyncSession,
    settings: Settings,
    cluster: Cluster,
    articles: list[Article],
) -> Summary:
    existing = (
        await session.execute(
            select(Summary).where(
                Summary.cluster_id == cluster.id,
                Summary.model == settings.llm_model,
                Summary.provider == settings.llm_provider,
            )
        )
    ).scalars().first()
    if existing:
        return existing

    messages = _build_messages(cluster, articles)

    summary_md = await _generate_with_gemini_fallback(
        settings=settings,
        messages=messages,
        temperature=0.2,
        max_tokens=1000,
    )
    if summary_md:
        logger.info(
            "Cluster summary generated cluster_id=%s provider=%s model=%s chars=%d",
            cluster.id,
            settings.llm_provider,
            settings.llm_model,
            len(summary_md),
        )
    else:
        logger.warning(
            "Cluster summary empty cluster_id=%s provider=%s model=%s",
            cluster.id,
            settings.llm_provider,
            settings.llm_model,
        )

    created = Summary(
        cluster_id=cluster.id,
        model=settings.llm_model,
        provider=settings.llm_provider,
        summary_md=summary_md,
    )
    session.add(created)
    await session.commit()
    await session.refresh(created)
    return created


async def fetch_cluster_summary(
    session: AsyncSession,
    cluster_id: str,
    model: str,
    provider: str,
) -> Summary | None:
    stmt = select(Summary).where(Summary.cluster_id == cluster_id, Summary.model == model, Summary.provider == provider)
    return (await session.execute(stmt)).scalars().first()


async def list_cluster_articles(session: AsyncSession, cluster_id: str) -> list[Article]:
    cluster = (
        await session.execute(
            select(Cluster)
            .options(selectinload(Cluster.cluster_articles).selectinload(ClusterArticle.article))
            .where(Cluster.id == cluster_id)
        )
    ).scalars().first()
    if not cluster:
        return []
    return [item.article for item in cluster.cluster_articles if item.article]


async def ensure_daily_top_summary(
    session: AsyncSession,
    settings: Settings,
    day: date,
    clusters: list[Cluster],
    articles_by_cluster_id: dict[str, list[Article]],
) -> DailyTopSummary:
    existing = (await session.execute(select(DailyTopSummary).where(DailyTopSummary.day == day))).scalars().first()

    summary_md = ""
    if clusters:
        logger.info(
            "Daily summary generation start day=%s clusters=%d provider=%s model=%s",
            day,
            len(clusters),
            settings.llm_provider,
            settings.llm_model,
        )
        messages = _build_daily_top_messages(clusters=clusters, articles_by_cluster_id=articles_by_cluster_id)
        generated = await _generate_with_gemini_fallback(
            settings=settings,
            messages=messages,
            temperature=0.2,
            max_tokens=1000,
        )
        normalized = _normalize_daily_top_summary(generated)
        if normalized:
            summary_md = normalized
            logger.info(
                "Daily summary generated day=%s provider=%s model=%s chars=%d",
                day,
                settings.llm_provider,
                settings.llm_model,
                len(summary_md),
            )
        else:
            logger.warning(
                "Daily summary empty after normalization day=%s provider=%s model=%s",
                day,
                settings.llm_provider,
                settings.llm_model,
            )
    else:
        logger.warning("Daily summary skipped day=%s reason=no_clusters", day)

    if existing is not None:
        existing.provider = settings.llm_provider
        existing.model = settings.llm_model
        existing.summary_md = summary_md
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        logger.info("Daily summary updated day=%s chars=%d", day, len(summary_md))
        return existing

    created = DailyTopSummary(
        day=day,
        provider=settings.llm_provider,
        model=settings.llm_model,
        summary_md=summary_md,
    )
    session.add(created)
    await session.commit()
    await session.refresh(created)
    logger.info("Daily summary created day=%s chars=%d", day, len(summary_md))
    return created


async def fetch_daily_top_summary(session: AsyncSession, day: date) -> DailyTopSummary | None:
    stmt = select(DailyTopSummary).where(DailyTopSummary.day == day)
    return (await session.execute(stmt)).scalars().first()


def _build_messages(cluster: Cluster, articles: list[Article]) -> list[dict]:
    lines = [
        f"Κεντρικός τίτλος: {cluster.representative_title}",
        "",
        "Άρθρα/Πηγές:",
    ]

    for idx, article in enumerate(articles, start=1):
        source_name = article.source.name if article.source else "Άγνωστη πηγή"
        lines.append(f"{idx}. [{source_name}] {article.title}")
        lines.append(f"   URL: {article.url}")
        if article.snippet:
            lines.append(f"   Snippet: {article.snippet}")

    lines.append("")
    lines.append("Παρακαλώ:")
    lines.append("- Γράψε 2-4 bullets στα Ελληνικά.")
    lines.append("- Αν υπάρχουν αντικρουόμενες πληροφορίες, σημείωσε αβεβαιότητα.")
    lines.append("- Μην προσθέτεις στοιχεία που δεν υπάρχουν στα titles/snippets.")
    lines.append("- Κλείσε με γραμμή 'Πηγές:' και μόνο ονόματα πηγών.")

    user_prompt = "\n".join(lines)

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _build_daily_top_messages(clusters: list[Cluster], articles_by_cluster_id: dict[str, list[Article]]) -> list[dict]:
    lines = [
        "Παρακάτω έχεις τα κορυφαία θέματα της ημέρας.",
        "",
        "Ζητούμενο:",
        "- Γράψε μια σύντομη σύνοψη 1 έως 3 παραγράφων στα Ελληνικά.",
        "- Χωρίς bullets, χωρίς markdown τίτλους, χωρίς αρίθμηση.",
        "- Θέλω φυσική ροή σαν μικρό άρθρο, όχι αποσπασματικές φράσεις.",
        "- Μην χρησιμοποιήσεις καθόλου το σύμβολο ';'.",
        "- Μην προσθέτεις πληροφορίες που δεν υπάρχουν στα δεδομένα.",
        "",
        "Θέματα:",
    ]

    for idx, cluster in enumerate(clusters[:15], start=1):
        articles = articles_by_cluster_id.get(cluster.id, [])
        source_names = sorted({article.source.name if article.source else "Άγνωστη πηγή" for article in articles})
        lines.append(f"{idx}. {cluster.representative_title}")
        lines.append(f"   Score: {cluster.score:.2f}")
        if source_names:
            lines.append(f"   Πηγές: {', '.join(source_names[:6])}")

        supporting_titles: list[str] = []
        for article in articles[:3]:
            title = article.title.strip()
            if not title or title == cluster.representative_title:
                continue
            source = article.source.name if article.source else "Άγνωστη πηγή"
            supporting_titles.append(f"[{source}] {title}")
        if supporting_titles:
            lines.append(f"   Σχετικά: {' | '.join(supporting_titles[:2])}")

    return [
        {"role": "system", "content": DAILY_TOP_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _normalize_daily_top_summary(raw_summary: str) -> str:
    text = raw_summary.replace("\r\n", "\n").strip()
    if not text:
        return ""

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n+", text) if chunk.strip()]
    if not paragraphs:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        paragraphs = [" ".join(lines)]

    cleaned_paragraphs = [re.sub(r"^[-*]\s*", "", paragraph) for paragraph in paragraphs]
    return "\n\n".join(cleaned_paragraphs[:3]).strip()


async def _generate_with_gemini_fallback(
    settings: Settings,
    messages: list[dict],
    *,
    temperature: float,
    max_tokens: int,
) -> str:
    primary_provider = settings.llm_provider.strip().lower()
    try:
        provider = get_provider(settings)
        logger.info(
            "Primary generation attempt provider=%s model=%s max_tokens=%d",
            primary_provider,
            settings.llm_model,
            max_tokens,
        )
        generated = await provider.generate(
            messages=messages,
            model=settings.llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = generated.strip() if generated else ""
        if text:
            logger.info(
                "Primary generation success provider=%s model=%s chars=%d",
                primary_provider,
                settings.llm_model,
                len(text),
            )
            return text
        logger.warning(
            "Primary generation returned empty provider=%s model=%s",
            primary_provider,
            settings.llm_model,
        )
    except Exception as exc:
        logger.warning(
            "Primary generation failed provider=%s model=%s error=%s",
            primary_provider,
            settings.llm_model,
            exc,
        )

    if primary_provider not in GEMINI_PROVIDER_ALIASES:
        logger.info("Groq fallback skipped provider=%s reason=not_gemini", primary_provider)
        return ""
    if not settings.groq_api_key:
        logger.warning("Groq fallback unavailable reason=missing_groq_api_key")
        return ""

    try:
        fallback_provider = GroqProvider(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
        logger.warning(
            "Groq fallback attempt model=%s max_tokens=%d reasoning_effort=%s",
            settings.groq_fallback_model,
            max_tokens,
            settings.groq_reasoning_effort,
        )
        generated = await fallback_provider.generate(
            messages=messages,
            model=settings.groq_fallback_model,
            temperature=1,
            top_p=1,
            max_tokens=max_tokens,
            reasoning_effort=settings.groq_reasoning_effort,
            tools=[],
        )
        text = generated.strip() if generated else ""
        if text:
            logger.warning(
                "Groq fallback success model=%s chars=%d",
                settings.groq_fallback_model,
                len(text),
            )
            return text
        logger.warning("Groq fallback returned empty model=%s", settings.groq_fallback_model)
        return ""
    except Exception as exc:
        logger.warning(
            "Groq fallback failed model=%s error=%s",
            settings.groq_fallback_model,
            exc,
        )
        return ""
