from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.utcnow()


class SourceType(str, enum.Enum):
    rss = "rss"
    sitemap = "sitemap"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    feed_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sitemap_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    articles: Mapped[list[Article]] = relationship("Article", back_populates="source")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    url: Mapped[str] = mapped_column(String(1200), nullable=False, unique=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    source: Mapped[Source] = relationship("Source", back_populates="articles")
    clusters: Mapped[list[ClusterArticle]] = relationship("ClusterArticle", back_populates="article")


class Cluster(Base):
    __tablename__ = "clusters"
    __table_args__ = (UniqueConstraint("day", "key", name="uq_cluster_day_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    representative_title: Mapped[str] = mapped_column(String(1000), nullable=False)
    representative_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    representative_source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    topics: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_strike_related: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    cluster_articles: Mapped[list[ClusterArticle]] = relationship(
        "ClusterArticle", back_populates="cluster", cascade="all, delete-orphan"
    )
    representative_source: Mapped[Source] = relationship("Source")
    summaries: Mapped[list[Summary]] = relationship("Summary", back_populates="cluster", cascade="all, delete-orphan")


class ClusterArticle(Base):
    __tablename__ = "cluster_articles"
    __table_args__ = (UniqueConstraint("cluster_id", "article_id", name="uq_cluster_article"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)

    cluster: Mapped[Cluster] = relationship("Cluster", back_populates="cluster_articles")
    article: Mapped[Article] = relationship("Article", back_populates="clusters")


class Summary(Base):
    __tablename__ = "summaries"
    __table_args__ = (UniqueConstraint("cluster_id", "model", "provider", name="uq_summary_cluster_model_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    cluster: Mapped[Cluster] = relationship("Cluster", back_populates="summaries")


class DailyTopSummary(Base):
    __tablename__ = "daily_top_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    day: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class DailyStrikeSummary(Base):
    __tablename__ = "daily_strike_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    day: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    day: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    weather_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_cluster_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    strike_cluster_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class EmailDeliveryConfig(Base):
    __tablename__ = "email_delivery_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transport: Mapped[str] = mapped_column(String(32), default="smtp", nullable=False)
    auto_send_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recipient_emails: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class EmailDeliveryLog(Base):
    __tablename__ = "email_delivery_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    triggered_by: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_emails: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
