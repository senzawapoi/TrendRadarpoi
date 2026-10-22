"""Standalone, additive HTML reporting for actionable security Stories."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trendradar.core.models import Story
from trendradar.domains.security.analyzer import SourceFreshness
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.utils.logging import log


def _safe_url(value: object) -> str:
    raw = str(value or "")
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    return raw if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _security_metadata(story: Story) -> Mapping[str, object]:
    value = story.metadata.get("security")
    return value if isinstance(value, Mapping) else {}


def prepare_security_report(
    stories: list[Story],
    storage: IntelligenceStorage,
) -> list[dict[str, object]]:
    """Resolve every persisted observation needed by the security report."""
    prepared: list[dict[str, object]] = []
    for story in stories:
        if story.domain != "security":
            continue
        evidence: list[dict[str, object]] = []
        for row in storage.list_story_evidence(story.id):
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            metadata = metadata if isinstance(metadata, Mapping) else {}
            evidence.append(
                {
                    "source": str(row["source"]),
                    "source_name": str(metadata.get("source_name") or row["source"]),
                    "title": str(row["title"]),
                    "url": _safe_url(row["url"]),
                    "observed_at": str(row["last_observed_at"]),
                }
            )
        prepared.append(
            {
                "story": story,
                "security": dict(_security_metadata(story)),
                "evidence": evidence,
            }
        )
    return prepared


def _display_time(value: datetime | None, local_timezone: ZoneInfo | timezone) -> str:
    return value.astimezone(local_timezone).isoformat() if value is not None else "Never"


def _freshness_table(
    freshness: list[SourceFreshness],
    local_timezone: ZoneInfo | timezone,
) -> str:
    rows: list[str] = []
    for source in freshness:
        state = "stale" if source.stale else source.status
        age = f"{source.age_hours:.1f}h" if source.age_hours is not None else "unknown"
        rows.append(
            """
            <tr class="state-{state_class}">
              <td>{adapter}</td><td>{status}</td><td>{last_success}</td><td>{age}</td>
              <td>{counts}</td><td>{error}</td>
            </tr>
            """.format(
                state_class=html.escape(state),
                adapter=html.escape(source.adapter_id),
                status=html.escape(f"{source.status}{' / stale' if source.stale else ''}"),
                last_success=html.escape(_display_time(source.last_success_at, local_timezone)),
                age=html.escape(age),
                counts=html.escape(f"{source.normalized_count}/{source.fetched_count}"),
                error=html.escape(source.error_summary),
            )
        )
    if not rows:
        return '<p class="empty">No enabled security sources.</p>'
    return """
    <div class="table-wrap"><table>
      <thead><tr><th>Source</th><th>Current status</th><th>Last success</th>
      <th>Age</th><th>Normalized/fetched</th><th>Latest error</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div>
    """.format(rows="".join(rows))


def _list_items(values: object) -> list[str]:
    if isinstance(values, list | tuple | set | frozenset):
        return [str(value) for value in values if str(value)]
    return [str(values)] if values else []


def _story_sections(
    report_data: list[dict[str, object]],
    local_timezone: ZoneInfo | timezone,
) -> str:
    sections: list[str] = []
    for entry in report_data:
        story = entry["story"]
        if not isinstance(story, Story):
            continue
        security = entry.get("security")
        security = security if isinstance(security, Mapping) else {}
        cves = _list_items(security.get("cve_ids"))
        actions = _list_items(security.get("required_actions"))
        references = [_safe_url(value) for value in _list_items(security.get("references"))]
        references = [value for value in references if value]
        facts = [
            f"CVEs: {', '.join(cves) or 'None identified'}",
            f"Severity: {security.get('severity') or 'Unknown'}",
            f"CVSS: {security.get('cvss_score') if security.get('cvss_score') is not None else 'Unknown'}",
            f"KEV: {'Yes' if security.get('known_exploited') else 'No'}",
            f"Due: {security.get('due_date') or 'Not specified'}",
        ]
        reason_rows = "".join(
            f"<li>{html.escape(reason)}</li>" for reason in story.importance.reasons
        )
        action_rows = "".join(f"<li>{html.escape(value)}</li>" for value in actions)
        reference_rows = "".join(
            '<li><a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a></li>'.format(
                url=html.escape(value, quote=True)
            )
            for value in references
        )
        evidence_rows: list[str] = []
        evidence = entry.get("evidence")
        for item in evidence if isinstance(evidence, list) else []:
            if not isinstance(item, Mapping):
                continue
            title = html.escape(str(item.get("title") or "Untitled evidence"))
            url = html.escape(str(item.get("url") or ""), quote=True)
            linked = (
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
                if url
                else title
            )
            evidence_rows.append(
                "<li>{linked}<span>{source} | {observed}</span></li>".format(
                    linked=linked,
                    source=html.escape(str(item.get("source_name") or item.get("source") or "")),
                    observed=html.escape(str(item.get("observed_at") or "")),
                )
            )
        sections.append(
            """
            <article class="story">
              <header><span class="score">{score:.1f}</span><div><h2>{title}</h2>
              <p class="time">{event_time}</p></div></header>
              <p class="summary">{summary}</p>
              <ul class="facts">{facts}</ul>
              <div class="details">
                <section><h3>Why it matters</h3><ul>{reasons}</ul></section>
                <section><h3>Required action</h3><ul>{actions}</ul></section>
              </div>
              <section><h3>Source evidence ({evidence_count})</h3><ul class="evidence">{evidence}</ul></section>
              <section><h3>References</h3><ul class="references">{references}</ul></section>
            </article>
            """.format(
                score=story.importance.score,
                title=html.escape(story.title),
                event_time=html.escape(story.event_time.astimezone(local_timezone).isoformat()),
                summary=html.escape(story.summary),
                facts="".join(f"<li>{html.escape(fact)}</li>" for fact in facts),
                reasons=reason_rows or "<li>No ranking evidence available.</li>",
                actions=action_rows or "<li>No action specified.</li>",
                evidence_count=len(evidence_rows),
                evidence="".join(evidence_rows) or "<li>No source observations available.</li>",
                references=reference_rows or "<li>No external references available.</li>",
            )
        )
    return "".join(sections) or '<p class="empty">No Security Stories for this period.</p>'


def render_security_report(
    report_data: list[dict[str, object]],
    *,
    freshness: list[SourceFreshness] | None = None,
    generated_at: datetime,
    timezone_name: str = "Asia/Shanghai",
    narrative: str | None = None,
) -> str:
    """Render actionable Security Stories and passive source health."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    try:
        local_timezone: ZoneInfo | timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = timezone.utc
    local_time = generated_at.astimezone(local_timezone)
    narrative_section = ""
    if isinstance(narrative, str) and narrative.strip():
        narrative_section = (
            '<section class="security-narrative"><h2>Security narrative</h2>'
            f"<p>{html.escape(narrative.strip())}</p></section>\n  "
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Security Intelligence | {local_time:%Y-%m-%d}</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, sans-serif; color: #172027; background: #f5f6f4; }}
    body {{ margin: 0 auto; max-width: 1060px; padding: 24px 18px 48px; }}
    h1 {{ margin: 0; font-size: 28px; }} h2 {{ font-size: 19px; margin: 0; }}
    h3 {{ font-size: 14px; margin: 16px 0 7px; }} .generated, .time {{ color: #667078; font-size: 12px; }}
    .generated {{ margin: 6px 0 22px; }} .story {{ background: #fff; border: 1px solid #dce1dd; border-radius: 6px; margin: 16px 0; padding: 18px; }}
    .story header {{ display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 14px; }}
    .score {{ background: #9f2d20; color: #fff; padding: 9px 4px; text-align: center; font-weight: 700; align-self: start; }}
    .summary {{ line-height: 1.55; }} .facts {{ display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 0; list-style: none; font-size: 13px; }}
    .details {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }}
    ul {{ margin: 0; padding-left: 19px; }} li {{ margin: 5px 0; }}
    .evidence li {{ display: grid; gap: 2px; }} .evidence span {{ color: #667078; font-size: 12px; }}
    a {{ color: #1265a8; overflow-wrap: anywhere; }} .table-wrap {{ overflow-x: auto; margin-bottom: 22px; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 12px; }}
    th, td {{ border: 1px solid #dce1dd; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #e9ece8; }} .state-unhealthy td, .state-stale td {{ background: #fff0ed; }}
    .state-healthy td {{ background: #eef8f1; }} .empty {{ background: #fff; border: 1px solid #dce1dd; padding: 18px; }}
    @media (max-width: 680px) {{ body {{ padding: 16px 12px 36px; }} .details {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>Security Intelligence</h1>
  <p class="generated">Generated {local_time:%Y-%m-%d %H:%M:%S %Z} | {len(report_data)} Stories</p>
  <section><h2>Source freshness</h2>{_freshness_table(freshness or [], local_timezone)}</section>
  {narrative_section}<main>{_story_sections(report_data, local_timezone)}</main>
</body>
</html>
"""


def save_security_report(
    stories: list[Story],
    storage: IntelligenceStorage,
    *,
    freshness: list[SourceFreshness] | None = None,
    output_dir: str | Path = "output/security",
    generated_at: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
    narrative_analyzer: object | None = None,
) -> Path:
    timestamp = generated_at or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = timezone.utc
    target = Path(output_dir) / f"{timestamp.astimezone(local_timezone):%Y-%m-%d}.html"
    narrative = None
    if stories and narrative_analyzer is not None:
        try:
            narrative = narrative_analyzer.analyze(stories)
        except Exception as exc:
            log.warning(
                "Security narrative generation failed; deterministic report remains available",
                error_type=type(exc).__name__,
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_security_report(
            prepare_security_report(stories, storage),
            freshness=freshness,
            generated_at=timestamp,
            timezone_name=timezone_name,
            narrative=narrative,
        ),
        encoding="utf-8",
    )
    return target


__all__ = ["prepare_security_report", "render_security_report", "save_security_report"]
