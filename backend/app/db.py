from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings, resolve_database_url


def _to_async_sqlite_url(database_url: str) -> str:
    resolved_url = resolve_database_url(database_url)
    if resolved_url.startswith("sqlite+aiosqlite://"):
        return resolved_url
    if resolved_url.startswith("sqlite://"):
        return resolved_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return resolved_url


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(_to_async_sqlite_url(settings.database_url), future=True, echo=False)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    # Import models so metadata is complete before create_all.
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_sqlite_migrations(conn)


async def _run_sqlite_migrations(conn) -> None:
    await _ensure_column(
        conn,
        table_name="email_delivery_configs",
        column_name="transport",
        column_sql="transport VARCHAR(32) NOT NULL DEFAULT 'smtp'",
    )


async def _ensure_column(conn, *, table_name: str, column_name: str, column_sql: str) -> None:
    pragma = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = {row[1] for row in pragma.fetchall()}
    if column_name in columns:
        return
    await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))
