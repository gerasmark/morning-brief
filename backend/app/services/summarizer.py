from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.llm.router import get_provider
from app.models import Article, Cluster, ClusterArticle, Summary

SYSTEM_PROMPT = "Είσαι συντάκτης πρωινής ενημέρωσης. Γράφεις σύντομα, ουδέτερα, χωρίς υπερβολές."


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

    provider = get_provider(settings)
    messages = _build_messages(cluster, articles)

    try:
        summary_md = await provider.generate(messages=messages, model=settings.llm_model, temperature=0.2, max_tokens=450)
        if not summary_md:
            summary_md = "(Περίληψη μη διαθέσιμη ακόμη)"
    except Exception:
        summary_md = "(Περίληψη μη διαθέσιμη ακόμη)"

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
