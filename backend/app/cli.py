from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import SourceType
from app.runtime import bootstrap_data, configure_logging
from app.services.briefing import BriefingService
from app.services.ingestion import IngestionService
from app.use_cases import (
    NotFoundError,
    fetch_live_strikes,
    generate_briefing_payload,
    get_briefing_payload,
    get_today_briefing_payload,
    list_articles,
    list_briefings,
    list_sources,
    resolve_source,
    run_ingestion_pipeline,
    update_source,
)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date: {value}. Expected YYYY-MM-DD.") from exc


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of formatted text")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brief",
        description="Terminal client for the Proino Briefing app.",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    subparsers = parser.add_subparsers(dest="command", required=True)

    today = subparsers.add_parser("today", help="Show today's briefing")
    today.add_argument("--details", action="store_true", help="Include supporting source rows")
    _add_json_flag(today)

    day_cmd = subparsers.add_parser("day", help="Show a stored briefing for a specific day")
    day_cmd.add_argument("day", type=_parse_day, help="Briefing day in YYYY-MM-DD format")
    day_cmd.add_argument("--details", action="store_true", help="Include supporting source rows")
    _add_json_flag(day_cmd)

    archive = subparsers.add_parser("archive", help="List archived briefings")
    archive.add_argument("--limit", type=int, default=30, help="Maximum rows to show")
    _add_json_flag(archive)

    ingest = subparsers.add_parser("ingest", help="Run ingestion and regenerate today's briefing")
    _add_json_flag(ingest)

    generate = subparsers.add_parser("generate", help="Generate a briefing")
    generate.add_argument("--day", type=_parse_day, help="Target day in YYYY-MM-DD format")
    generate.add_argument("--details", action="store_true", help="Include supporting source rows")
    _add_json_flag(generate)

    sources = subparsers.add_parser("sources", help="List or update source configuration")
    source_subparsers = sources.add_subparsers(dest="sources_command", required=True)

    sources_list = source_subparsers.add_parser("list", help="List configured sources")
    _add_json_flag(sources_list)

    sources_set = source_subparsers.add_parser("set", help="Update a source by id or exact name")
    sources_set.add_argument("source", help="Source id or exact source name")
    enabled_group = sources_set.add_mutually_exclusive_group()
    enabled_group.add_argument("--enable", action="store_true", help="Enable the source")
    enabled_group.add_argument("--disable", action="store_true", help="Disable the source")
    sources_set.add_argument("--weight", type=float, help="Set source weight (0.0 to 5.0)")
    sources_set.add_argument("--type", choices=[item.value for item in SourceType], help="Set source type")
    sources_set.add_argument("--feed-url", help="Set RSS/feed URL")
    sources_set.add_argument("--clear-feed-url", action="store_true", help="Clear RSS/feed URL")
    sources_set.add_argument("--sitemap-url", help="Set sitemap/JSON URL")
    sources_set.add_argument("--clear-sitemap-url", action="store_true", help="Clear sitemap/JSON URL")
    _add_json_flag(sources_set)

    articles = subparsers.add_parser("articles", help="List ingested articles")
    articles.add_argument("--source", help="Filter by exact source name")
    articles.add_argument("--limit", type=int, default=20, help="Maximum rows to show")
    _add_json_flag(articles)

    strikes = subparsers.add_parser("strikes", help="Preview live strike cards")
    strikes.add_argument("--limit", type=int, default=20, help="Maximum rows to show")
    strikes.add_argument("--debug", action="store_true", help="Include source fetch diagnostics")
    strikes.add_argument("--details", action="store_true", help="Include supporting source rows")
    _add_json_flag(strikes)

    return parser


def _json_output(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_timestamp(value: str | None) -> str:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return value or "-"
    return parsed.strftime("%Y-%m-%d %H:%M")


def _paragraphs(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("\n\n") if item.strip()]


def _bullets(value: str | None) -> list[str]:
    if not value:
        return []
    rows: list[str] = []
    for line in value.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        rows.append(cleaned.lstrip("-*• ").strip())
    return rows


def _latest_published_at(item: dict[str, Any]) -> str | None:
    latest: datetime | None = None
    latest_iso: str | None = None
    for source in item.get("sources", []):
        current_iso = source.get("published_at")
        parsed = _parse_iso_datetime(current_iso)
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
            latest_iso = current_iso
    return latest_iso


def _should_use_color(no_color: bool) -> bool:
    if no_color or os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    term = os.getenv("TERM", "").lower()
    return sys.stdout.isatty() and term not in {"", "dumb"}


def _terminal_width() -> int:
    return max(80, min(shutil.get_terminal_size((120, 40)).columns, 140))


@dataclass
class DashboardRenderer:
    color: bool
    width: int

    _tones: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._tones = {
            "cyan": "96",
            "blue": "94",
            "green": "92",
            "amber": "93",
            "red": "91",
            "magenta": "95",
            "slate": "90",
            "white": "97",
        }

    def render_briefing(self, payload: dict[str, Any], *, details: bool) -> str:
        top_stories = payload.get("top_stories") or []
        strikes = payload.get("strikes") or []
        weather = payload.get("weather") or {}
        names = (payload.get("birthdays") or {}).get("names") or []

        blocks = [
            self.banner(
                "Proino Briefing",
                payload.get("day", "-"),
                [
                    self.chip(f"top {len(top_stories)}", "blue"),
                    self.chip(f"strikes {len(strikes)}", "amber"),
                    self.chip(weather.get("city") or "weather", "green"),
                ],
            ),
            self.metric_grid(
                [
                    ("Top Stories", str(len(top_stories)), "blue", "ranked clusters"),
                    ("Live Strikes", str(len(strikes)), "amber", "current transport view"),
                    ("Weather", self._weather_value(weather), "green", weather.get("current_condition") or "live"),
                    ("Names", str(len(names)), "magenta", "today"),
                ]
            ),
            self.info_row(payload),
        ]

        top_summary = _paragraphs(payload.get("top_summary_md"))
        strike_summary = _bullets(payload.get("strike_summary_md"))
        if top_summary or strike_summary:
            summary_panels: list[str] = []
            summary_width = self.column_width(2) if top_summary and strike_summary else self.width
            if top_summary:
                summary_panels.append(
                    self.panel(
                        "Top Summary",
                        self.wrap_lines(top_summary, max(24, summary_width - 6)),
                        tone="blue",
                        width=summary_width,
                    )
                )
            if strike_summary:
                summary_panels.append(
                    self.panel(
                        "Strike Summary",
                        [f"- {item}" for item in strike_summary],
                        tone="amber",
                        width=summary_width,
                    )
                )
            blocks.append(self.stack_blocks(summary_panels, columns=2))

        blocks.append(self.section_title("Top Stories", f"{len(top_stories)} ranked clusters", "blue"))
        if top_stories:
            blocks.extend(
                self.story_cards(
                    top_stories,
                    tone="blue",
                    details=details,
                    show_summary=False,
                )
            )
        else:
            blocks.append(self.panel("Top Stories", ["No top stories available."], tone="blue"))

        blocks.append(self.section_title("Strikes", f"{len(strikes)} live items", "amber"))
        if strikes:
            blocks.extend(self.story_cards(strikes, tone="amber", details=details, show_summary=True))
        else:
            blocks.append(self.panel("Strikes", ["No live strike items available."], tone="amber"))

        return "\n\n".join(blocks)

    def render_archive(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return self.panel("Archive", ["No archived briefings found."], tone="slate")
        table = self.table_panel(
            "Archive",
            ["Day", "Top", "Strikes", "Created"],
            [
                [
                    str(row.get("day", "-")),
                    str(row.get("top_count", 0)),
                    str(row.get("strike_count", 0)),
                    _format_timestamp(row.get("created_at")),
                ]
                for row in rows
            ],
            tone="blue",
        )
        header = self.banner(
            "Archive",
            f"{len(rows)} stored briefings",
            [self.chip("history", "blue"), self.chip("read only", "slate")],
        )
        return "\n\n".join([header, table])

    def render_sources(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return self.panel("Sources", ["No sources configured."], tone="slate")

        table = self.table_panel(
            "Sources",
            ["ID", "Name", "Status", "Weight", "Type"],
            [
                [
                    str(row.get("id", "-")),
                    str(row.get("name", "-")),
                    "enabled" if row.get("enabled") else "disabled",
                    f"{float(row.get('weight', 0.0)):.1f}",
                    str(row.get("type", "-")),
                ]
                for row in rows
            ],
            tone="cyan",
        )

        detail_cards = [
            self.panel(
                str(row.get("name", "-")),
                [
                    f"base    {row.get('base_url') or '-'}",
                    f"feed    {row.get('feed_url') or '-'}",
                    f"sitemap {row.get('sitemap_url') or '-'}",
                ],
                tone="cyan" if row.get("enabled") else "slate",
                width=self.column_width(2),
            )
            for row in rows[:6]
        ]

        header = self.banner(
            "Sources",
            f"{len(rows)} configured feeds",
            [self.chip("enabled", "green"), self.chip("weighted", "cyan")],
        )
        blocks = [header, table]
        if detail_cards:
            blocks.append(self.stack_blocks(detail_cards, columns=2))
        return "\n\n".join(blocks)

    def render_articles(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return self.panel("Articles", ["No articles found."], tone="slate")
        cards = []
        for index, row in enumerate(rows, start=1):
            published_at = row.get("published_at") or row.get("created_at")
            cards.append(
                self.panel(
                    f"{index:02d}  {row.get('source') or 'Source'}",
                    [
                        self.strong(str(row.get("title") or "-")),
                        self.muted(_format_timestamp(published_at)),
                        str(row.get("url") or "-"),
                    ],
                    tone="blue",
                )
            )
        header = self.banner(
            "Articles",
            f"{len(rows)} recent rows",
            [self.chip("ingested", "blue"), self.chip("local db", "slate")],
        )
        return "\n\n".join([header, *cards])

    def render_ingestion(self, payload: dict[str, Any]) -> str:
        metric_grid = self.metric_grid(
            [
                ("Fetched", str(payload.get("fetched", 0)), "blue", "raw article rows"),
                ("Inserted", str(payload.get("inserted", 0)), "green", "new rows"),
                ("Failed", str(len(payload.get("failed_sources") or [])), "red", "source failures"),
                ("Sources", str(len(payload.get("source_stats") or [])), "cyan", "checked"),
            ]
        )

        failed = ", ".join(payload.get("failed_sources") or []) or "none"
        summary = self.banner(
            "Ingestion Complete",
            failed,
            [self.chip("pipeline", "green"), self.chip("fresh run", "blue")],
        )

        table = self.table_panel(
            "Per Source",
            ["Source", "Status", "Fetched", "Inserted", "HTTP", "Statuses"],
            [
                [
                    str(item.get("source", "-")),
                    str(item.get("status", "-")),
                    str(item.get("fetched", 0)),
                    str(item.get("inserted", 0)),
                    f"{item.get('http_requests', 0)}/{item.get('http_non_200', 0)}",
                    self._status_preview(item.get("http_statuses") or {}),
                ]
                for item in payload.get("source_stats", [])
            ],
            tone="green",
        )
        return "\n\n".join([summary, metric_grid, table])

    def render_strikes(self, payload: dict[str, Any], *, details: bool) -> str:
        items = payload.get("items") or []
        header = self.banner(
            "Live Strikes",
            f"{len(items)} selected items",
            [self.chip("transport", "amber"), self.chip("live", "red")],
        )
        blocks = [header]
        if items:
            blocks.extend(self.story_cards(items, tone="amber", details=details, show_summary=True))
        else:
            blocks.append(self.panel("Strikes", ["No live strike items available."], tone="amber"))

        if "source_debug" in payload:
            summary = self.metric_grid(
                [
                    ("Raw", str(payload.get("raw_candidate_count", 0)), "amber", "candidates"),
                    ("Deduped", str(payload.get("deduped_count", 0)), "green", "after cleanup"),
                    ("Shown", str(payload.get("count", 0)), "blue", "selected"),
                    ("Sources", str(len(payload.get("source_debug") or [])), "cyan", "tag feeds"),
                ]
            )
            debug_table = self.table_panel(
                "Source Debug",
                ["Source", "Mode", "RSS", "HTML", "RSS Error", "HTML Error"],
                [
                    [
                        str(item.get("source", "-")),
                        str(item.get("mode_used", "-")),
                        str(item.get("rss_count", 0)),
                        str(item.get("html_count", 0)),
                        str(item.get("rss_error") or "-"),
                        str(item.get("html_error") or "-"),
                    ]
                    for item in payload.get("source_debug", [])
                ],
                tone="red",
            )
            blocks.extend([summary, debug_table])

        return "\n\n".join(blocks)

    def banner(self, title: str, subtitle: str, chips: list[str]) -> str:
        title_line = self.style(title.upper(), "1", self._tones["white"])
        subtitle_line = self.style(subtitle, self._tones["cyan"])
        chip_line = " ".join(chips) if chips else ""
        return self.panel("", [title_line, subtitle_line, chip_line], tone="cyan", width=self.width)

    def metric_grid(self, items: list[tuple[str, str, str, str]]) -> str:
        columns = 4 if self.width >= 128 else 2
        card_width = self.column_width(columns)
        cards = [
            self.metric_card(label, value, tone=tone, subtitle=subtitle, width=card_width)
            for label, value, tone, subtitle in items
        ]
        return self.stack_blocks(cards, columns=columns)

    def metric_card(self, label: str, value: str, *, tone: str, subtitle: str, width: int) -> str:
        return self.panel(
            label,
            [
                self.style(value, "1", self._tones.get(tone, self._tones["white"])),
                self.muted(subtitle),
            ],
            tone=tone,
            width=width,
        )

    def info_row(self, payload: dict[str, Any]) -> str:
        weather = payload.get("weather") or {}
        birthdays = payload.get("birthdays") or {}
        quote = payload.get("quote_of_day") or {}

        weather_lines = self._weather_lines(weather)
        daybook_lines = []
        if birthdays.get("unavailable"):
            daybook_lines.append(f"names unavailable: {birthdays.get('error') or 'unknown error'}")
        else:
            names = birthdays.get("names") or []
            daybook_lines.append(f"names {', '.join(names) if names else '-'}")

        if quote.get("unavailable"):
            daybook_lines.append(f"quote unavailable: {quote.get('error') or 'unknown error'}")
        elif quote.get("quote"):
            rendered = f"quote {quote['quote']}"
            if quote.get("author"):
                rendered += f" | {quote['author']}"
            daybook_lines.append(rendered)
        else:
            daybook_lines.append("quote -")

        panel_width = self.column_width(2)
        panels = [
            self.panel("Weather", weather_lines, tone="green", width=panel_width),
            self.panel("Daybook", daybook_lines, tone="magenta", width=panel_width),
        ]
        return self.stack_blocks(panels, columns=2)

    def section_title(self, title: str, subtitle: str, tone: str) -> str:
        plain = f"{title}  {subtitle}"
        line = "─" * max(0, self.width - len(plain) - 1)
        return self.style(f"{title}", "1", self._tones.get(tone, self._tones["white"])) + " " + self.muted(subtitle) + " " + self.tone(line, tone)

    def story_cards(
        self,
        items: list[dict[str, Any]],
        *,
        tone: str,
        details: bool,
        show_summary: bool,
    ) -> list[str]:
        cards: list[str] = []
        for index, item in enumerate(items, start=1):
            source_count = len(item.get("sources", []))
            latest_published = _format_timestamp(_latest_published_at(item))
            lines = [
                self.strong(str(item.get("title") or "-")),
                f"{self.chip(str(item.get('source') or 'source'), tone)} {self.chip(f'{source_count} sources', 'slate')} {self.chip(latest_published, 'slate')}",
                self.muted(str(item.get("url") or "-")),
            ]
            if show_summary and item.get("summary_md"):
                summary_rows = _bullets(item.get("summary_md"))
                if summary_rows:
                    lines.append("")
                    lines.extend([f"- {row}" for row in summary_rows[:4]])
            if details:
                lines.append("")
                for source in item.get("sources", []):
                    lines.append(
                        f"- {source.get('source')}: {source.get('title')} ({_format_timestamp(source.get('published_at'))})"
                    )

            cards.append(self.panel(f"{index:02d}", lines, tone=tone))
        return cards

    def table_panel(
        self,
        title: str,
        headers: list[str],
        rows: list[list[str]],
        *,
        tone: str,
    ) -> str:
        if not rows:
            return self.panel(title, ["No rows available."], tone=tone)

        min_col_width = 6
        max_width = self.width - 6
        widths = [len(header) for header in headers]
        for row in rows:
            for index, cell in enumerate(row):
                widths[index] = max(widths[index], len(self.strip_ansi(str(cell))))
        while sum(widths) + (3 * (len(widths) - 1)) > max_width:
            largest = max(range(len(widths)), key=lambda idx: widths[idx])
            if widths[largest] <= min_col_width:
                break
            widths[largest] -= 1

        header_line = " | ".join(
            self.pad(self.style(headers[index], "1", self._tones["white"]), widths[index])
            for index in range(len(headers))
        )
        separator = "─" * self.visible_len(header_line)
        lines = [header_line, self.muted(separator)]
        for row in rows:
            rendered = [
                self.pad(self.truncate(str(row[index]), widths[index]), widths[index])
                for index in range(len(headers))
            ]
            lines.append(" | ".join(rendered))
        return self.panel(title, lines, tone=tone, width=self.width)

    def stack_blocks(self, blocks: list[str], *, columns: int) -> str:
        if not blocks:
            return ""
        columns = max(1, min(columns, len(blocks)))
        gap = 2
        column_width = (self.width - (gap * (columns - 1))) // columns
        rows: list[str] = []
        for start in range(0, len(blocks), columns):
            current = self.equalize_blocks(blocks[start : start + columns])
            sized = [self.resize_block(block, column_width) for block in current]
            rows.append(self.join_columns(sized, gap=gap))
        return "\n\n".join(rows)

    def column_width(self, columns: int, *, gap: int = 2) -> int:
        return (self.width - (gap * (columns - 1))) // max(1, columns)

    def equalize_blocks(self, blocks: list[str]) -> list[str]:
        split_blocks = [block.splitlines() for block in blocks]
        target_height = max((len(lines) for lines in split_blocks), default=0)
        equalized: list[str] = []
        for lines in split_blocks:
            if len(lines) < 3 or len(lines) >= target_height:
                equalized.append("\n".join(lines + ([""] * (target_height - len(lines)))))
                continue

            body_template = lines[1]
            padding = [self.blank_like_panel_line(body_template) for _ in range(target_height - len(lines))]
            equalized.append("\n".join(lines[:-1] + padding + [lines[-1]]))
        return equalized

    def blank_like_panel_line(self, line: str) -> str:
        visible_positions: list[tuple[int, int]] = []
        index = 0
        while index < len(line):
            match = ANSI_RE.match(line, index)
            if match is not None:
                index = match.end()
                continue
            visible_positions.append((index, index + 1))
            index += 1

        if len(visible_positions) < 2:
            return line

        left_end = visible_positions[0][1]
        right_start = visible_positions[-1][0]
        inner_width = max(0, len(visible_positions) - 2)
        return line[:left_end] + (" " * inner_width) + line[right_start:]

    def resize_block(self, block: str, width: int) -> str:
        lines = block.splitlines()
        return "\n".join(self.pad(line, width) for line in lines)

    def join_columns(self, blocks: list[str], *, gap: int) -> str:
        split_blocks = [block.splitlines() for block in blocks]
        widths = [max((self.visible_len(line) for line in lines), default=0) for lines in split_blocks]
        height = max((len(lines) for lines in split_blocks), default=0)
        output: list[str] = []
        spacer = " " * gap
        for row_index in range(height):
            row_parts = []
            for block_index, lines in enumerate(split_blocks):
                line = lines[row_index] if row_index < len(lines) else ""
                row_parts.append(self.pad(line, widths[block_index]))
            output.append(spacer.join(row_parts).rstrip())
        return "\n".join(output)

    def panel(
        self,
        title: str,
        lines: list[str],
        *,
        tone: str,
        width: int | None = None,
    ) -> str:
        target_width = max(22, min(width or self.width, self.width))
        inner_width = target_width - 2
        wrapped: list[str] = []
        for line in lines:
            if line == "":
                wrapped.append("")
                continue
            wrapped.extend(self.wrap_preserving_style(line, inner_width - 2))
        if not wrapped:
            wrapped = [""]

        visible_title = self.visible_len(title)
        if visible_title > 0:
            top_fill = max(0, inner_width - visible_title - 3)
            top = f"┌─ {title} {'─' * top_fill}┐"
        else:
            top = f"┌{'─' * inner_width}┐"
        body = [f"│{self.pad(line, inner_width)}│" for line in wrapped]
        bottom = f"└{'─' * inner_width}┘"

        return "\n".join(
            [
                self.tone(top, tone),
                *[self.tone(line[:1], tone) + line[1:-1] + self.tone(line[-1:], tone) for line in body],
                self.tone(bottom, tone),
            ]
        )

    def wrap_lines(self, lines: list[str], width: int) -> list[str]:
        wrapped: list[str] = []
        for line in lines:
            wrapped.extend(textwrap.wrap(line, width=width) or [""])
        return wrapped

    def wrap_preserving_style(self, value: str, width: int) -> list[str]:
        plain = self.strip_ansi(value)
        if not plain:
            return [""]
        wrapped_plain = textwrap.wrap(plain, width=max(10, width), replace_whitespace=False) or [plain]
        if value == plain:
            return wrapped_plain
        style_prefix = value[: value.find(plain)] if plain in value else ""
        style_suffix = "\033[0m" if self.color and "\033[" in value else ""
        return [f"{style_prefix}{line}{style_suffix}" for line in wrapped_plain]

    def visible_len(self, value: str) -> int:
        return len(self.strip_ansi(value))

    def strip_ansi(self, value: str) -> str:
        return ANSI_RE.sub("", value)

    def truncate(self, value: str, width: int) -> str:
        plain = self.strip_ansi(value)
        if len(plain) <= width:
            return value
        if width <= 3:
            return plain[:width]
        return plain[: width - 3] + "..."

    def pad(self, value: str, width: int) -> str:
        visible = self.visible_len(value)
        if visible >= width:
            return self.truncate(value, width)
        return value + (" " * (width - visible))

    def tone(self, value: str, tone: str) -> str:
        return self.style(value, self._tones.get(tone, self._tones["white"]))

    def muted(self, value: str) -> str:
        return self.style(value, self._tones["slate"])

    def strong(self, value: str) -> str:
        return self.style(value, "1", self._tones["white"])

    def chip(self, value: str, tone: str) -> str:
        return self.style(f"[{value}]", "1", self._tones.get(tone, self._tones["white"]))

    def style(self, value: str, *codes: str) -> str:
        if not self.color or not value:
            return value
        return f"\033[{';'.join(codes)}m{value}\033[0m"

    def _weather_value(self, weather: dict[str, Any]) -> str:
        if weather.get("unavailable"):
            return "offline"
        current_temp = weather.get("current_temperature")
        if current_temp is None:
            return "--"
        return f"{current_temp}°"

    def _weather_lines(self, weather: dict[str, Any]) -> list[str]:
        if not weather:
            return ["no weather data"]
        if weather.get("unavailable"):
            return [f"unavailable: {weather.get('error') or 'unknown error'}"]

        lines = [
            f"city {weather.get('city') or '-'}",
            f"now  {weather.get('current_temperature', '-')}° | {weather.get('current_condition') or '-'}",
            f"day  {weather.get('temperature_min', '-')}° / {weather.get('temperature_max', '-')}",
            f"rain {weather.get('precipitation_probability', '-')}% | wind {weather.get('wind_speed', '-')} km/h",
        ]
        forecast = weather.get("forecast") or []
        for item in forecast[1:3]:
            lines.append(
                f"{item.get('day')}  {item.get('temperature_max', '-')}°/{item.get('temperature_min', '-')}  {item.get('condition') or '-'}"
            )
        if weather.get("tls_warning"):
            lines.append(f"tls  {weather['tls_warning']}")
        return lines

    def _status_preview(self, statuses: dict[Any, Any]) -> str:
        if not statuses:
            return "-"
        return ", ".join(f"{key}={value}" for key, value in sorted(statuses.items()))


async def _resolve_source_identifier(session: AsyncSession, identifier: str) -> dict[str, Any]:
    source = await resolve_source(session, identifier)
    if source is not None:
        return {"id": source.id, "name": source.name}
    rows = await list_sources(session)
    lowered = identifier.strip().casefold()
    for row in rows:
        if str(row["name"]).casefold() == lowered:
            return {"id": row["id"], "name": row["name"]}
    raise NotFoundError("Source not found")


def _build_source_updates(args: argparse.Namespace) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if args.enable:
        updates["enabled"] = True
    if args.disable:
        updates["enabled"] = False

    if args.weight is not None:
        if not 0.0 <= args.weight <= 5.0:
            raise ValueError("Weight must be between 0.0 and 5.0.")
        updates["weight"] = args.weight

    if args.feed_url and args.clear_feed_url:
        raise ValueError("Use either --feed-url or --clear-feed-url, not both.")
    if args.sitemap_url and args.clear_sitemap_url:
        raise ValueError("Use either --sitemap-url or --clear-sitemap-url, not both.")

    if args.feed_url is not None:
        updates["feed_url"] = args.feed_url
    if args.clear_feed_url:
        updates["feed_url"] = None

    if args.sitemap_url is not None:
        updates["sitemap_url"] = args.sitemap_url
    if args.clear_sitemap_url:
        updates["sitemap_url"] = None

    if args.type is not None:
        updates["type"] = SourceType(args.type)

    if not updates:
        raise ValueError("No source changes provided.")
    return updates


async def main_async(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings)
    await bootstrap_data()

    renderer = DashboardRenderer(color=_should_use_color(args.no_color), width=_terminal_width())
    briefing_service = BriefingService()
    ingestion_service = IngestionService()

    try:
        async with SessionLocal() as session:
            if args.command == "today":
                payload = await get_today_briefing_payload(session, settings, briefing_service)
                print(_json_output(payload) if args.json else renderer.render_briefing(payload, details=args.details))
                return 0

            if args.command == "day":
                payload = await get_briefing_payload(session, settings, briefing_service, args.day)
                print(_json_output(payload) if args.json else renderer.render_briefing(payload, details=args.details))
                return 0

            if args.command == "archive":
                rows = await list_briefings(session)
                limited = rows[: max(args.limit, 0)]
                print(_json_output(limited) if args.json else renderer.render_archive(limited))
                return 0

            if args.command == "ingest":
                payload = await run_ingestion_pipeline(session, settings, ingestion_service, briefing_service)
                print(_json_output(payload) if args.json else renderer.render_ingestion(payload))
                return 0

            if args.command == "generate":
                payload = await generate_briefing_payload(
                    session,
                    settings,
                    briefing_service,
                    day=args.day,
                )
                briefing = payload.get("briefing") or {}
                print(_json_output(payload) if args.json else renderer.render_briefing(briefing, details=args.details))
                return 0

            if args.command == "articles":
                rows = await list_articles(session, source=args.source, limit=max(args.limit, 1))
                print(_json_output(rows) if args.json else renderer.render_articles(rows))
                return 0

            if args.command == "sources":
                if args.sources_command == "list":
                    rows = await list_sources(session)
                    print(_json_output(rows) if args.json else renderer.render_sources(rows))
                    return 0

                if args.sources_command == "set":
                    source_ref = await _resolve_source_identifier(session, args.source)
                    updates = _build_source_updates(args)
                    payload = await update_source(session, source_ref["id"], updates)
                    print(_json_output(payload) if args.json else renderer.render_sources([payload]))
                    return 0

            if args.command == "strikes":
                payload = await fetch_live_strikes(
                    settings,
                    briefing_service,
                    limit=max(args.limit, 1),
                    debug=args.debug,
                )
                print(_json_output(payload) if args.json else renderer.render_strikes(payload, details=args.details))
                return 0
    except NotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    parser.error("Unknown command")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(main_async(argv))
