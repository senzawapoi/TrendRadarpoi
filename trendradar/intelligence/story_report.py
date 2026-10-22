"""Additive local HTML reporting for ranked Stories."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trendradar.core.models import Story
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.utils.logging import log


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def prepare_story_report(
    stories: list[Story],
    storage: IntelligenceStorage,
    *,
    evidence_limit: int | None = None,
) -> list[dict]:
    """Resolve persisted observations into escaped-at-render-time report data."""
    prepared: list[dict] = []
    for story in stories:
        evidence = []
        for row in storage.list_story_evidence(story.id, limit=evidence_limit):
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            evidence.append(
                {
                    "source": row["source"],
                    "source_name": metadata.get("source_name") or row["source"],
                    "title": row["title"],
                    "url": _safe_url(row["url"] or ""),
                    "observed_at": row["last_observed_at"],
                }
            )
        prepared.append({"story": story, "evidence": evidence})
    return prepared


def render_story_report(
    report_data: list[dict],
    *,
    generated_at: datetime,
    timezone_name: str = "Asia/Shanghai",
    digest: str | None = None,
) -> str:
    """Render a standalone Story report without changing legacy report payloads."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = timezone.utc
    local_time = generated_at.astimezone(local_timezone)
    sections: list[str] = []
    for entry in report_data:
        story: Story = entry["story"]
        source_count = len({item["source"] for item in entry["evidence"]})
        reasons = "".join(f"<li>{html.escape(reason)}</li>" for reason in story.importance.reasons)
        evidence_rows = []
        for item in entry["evidence"]:
            title = html.escape(str(item["title"]))
            source = html.escape(str(item["source_name"]))
            observed = html.escape(str(item["observed_at"]))
            url = html.escape(str(item["url"]), quote=True)
            linked_title = (
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
                if url
                else title
            )
            evidence_rows.append(
                f"<li>{linked_title}<span>{source} · {observed}</span></li>"
            )
        sections.append(
            """
            <article class="story">
              <header>
                <span class="score">{score:.1f}</span>
                <div><h2>{title}</h2><p class="time">{event_time}</p></div>
              </header>
              <p class="meta">Members: {member_count}</p>
              <p class="summary">{summary}</p>
              <div class="details">
                <section><h3>Importance</h3><ul>{reasons}</ul></section>
                <section><h3>Sources ({source_count})</h3><ul class="evidence">{evidence}</ul></section>
              </div>
            </article>
            """.format(
                score=story.importance.score,
                title=html.escape(story.title),
                event_time=html.escape(story.event_time.astimezone(local_timezone).isoformat()),
                summary=html.escape(story.summary),
                reasons=reasons,
                source_count=source_count,
                member_count=len(story.member_ids),
                evidence="".join(evidence_rows) or "<li>No source observations available.</li>",
            )
        )
    content = "".join(sections) or '<p class="empty">No Stories for this period.</p>'
    digest_section = ""
    if isinstance(digest, str) and digest.strip():
        digest_section = (
            '<section class="daily-digest"><h2>Daily digest</h2>'
            f"<p>{html.escape(digest.strip())}</p></section>\n  "
        )
    body_content = f"{digest_section}{content}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Story Intelligence · {local_time:%Y-%m-%d}</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, sans-serif; color: #172027; background: #f5f6f4; }}
    body {{ margin: 0 auto; max-width: 960px; padding: 24px 18px 48px; }}
    h1 {{ margin: 0; font-size: 28px; }} .generated {{ color: #667078; margin: 6px 0 24px; }}
    .story {{ background: #fff; border: 1px solid #dce1dd; border-radius: 8px; margin: 14px 0; padding: 18px; }}
    .story header {{ display: grid; grid-template-columns: 64px 1fr; gap: 14px; align-items: start; }}
    .score {{ background: #154f3c; color: #fff; padding: 9px 4px; text-align: center; font-weight: 700; }}
    h2 {{ font-size: 19px; margin: 0; }} h3 {{ font-size: 14px; margin: 14px 0 6px; }}
    .time, .meta, .evidence span {{ color: #667078; font-size: 12px; }} .summary {{ line-height: 1.55; }}
    .details {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: 18px; }}
    ul {{ margin: 0; padding-left: 19px; }} li {{ margin: 5px 0; }}
    .evidence li {{ display: grid; gap: 2px; }} a {{ color: #1265a8; overflow-wrap: anywhere; }}
    @media (max-width: 680px) {{ .details {{ grid-template-columns: 1fr; }} body {{ padding: 16px 12px 36px; }} }}
  </style>
</head>
<body>
  <h1>Story Intelligence</h1>
  <p class="generated">Generated {local_time:%Y-%m-%d %H:%M:%S %Z} · {len(report_data)} Stories</p>
  {body_content}
</body>
</html>
"""


def save_story_report(
    stories: list[Story],
    storage: IntelligenceStorage,
    *,
    output_dir: str | Path = "output/stories",
    generated_at: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
    digest_analyzer: object | None = None,
) -> Path:
    timestamp = generated_at or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = timezone.utc
    target = Path(output_dir) / f"{timestamp.astimezone(local_timezone):%Y-%m-%d}.html"
    digest = None
    if stories and digest_analyzer is not None:
        try:
            digest = digest_analyzer.analyze(stories)
        except Exception as exc:
            log.warning("Daily digest generation failed; Story report remains available", error_type=type(exc).__name__)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_story_report(
            prepare_story_report(stories, storage),
            generated_at=timestamp,
            timezone_name=timezone_name,
            digest=digest,
        ),
        encoding="utf-8",
    )
    return target


__all__ = ["prepare_story_report", "render_story_report", "save_story_report"]
