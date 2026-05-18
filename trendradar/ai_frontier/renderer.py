"""AI 前沿报告渲染

生成 markdown（推送正文）+ HTML（详细报告）。
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from trendradar.ai_frontier.detector import group_by_source
from trendradar.ai_frontier.sources.base import AIItem
from trendradar.utils.logging import log

# 源展示名称
SOURCE_LABELS = {
    "arxiv": "📄 ArXiv 论文",
    "reddit": "🔥 Reddit",
    "hackernews": "🗞️ HackerNews",
    "github": "⭐ GitHub Trending",
    "x": "🐦 X / Twitter",
    "podcast": "🎙️ AI Podcasts",
    "blog": "📝 Official Blogs",
}

# 源对应的 emoji（推送使用）
SOURCE_EMOJI = {
    "arxiv": "📄",
    "reddit": "🔥",
    "hackernews": "🗞️",
    "github": "⭐",
    "x": "🐦",
    "podcast": "🎙️",
    "blog": "📝",
}


def _display_title(item: AIItem) -> str:
    """展示标题：有翻译时展示『中文（原文截断）』；否则原文"""
    if item.title_translated:
        return f"{item.title_translated}"
    return item.title


def render_markdown(items: list[AIItem], total_new: int | None = None) -> str:
    """生成 markdown 正文（用于 Bark/IM 推送）"""
    if not items:
        return "🔕 AI 前沿：本次无新增"

    groups = group_by_source(items)

    lines: list[str] = []
    count = total_new if total_new is not None else len(items)
    lines.append(f"🤖 AI 前沿 (新增 {count} 条)")
    lines.append("━" * 12)

    for source, group_items in groups.items():
        label = SOURCE_LABELS.get(source, source)
        lines.append(f"\n**{label}** ({len(group_items)})")
        for item in group_items:
            title = _display_title(item)
            score_badge = f" · {item.score}🔥" if item.score > 0 else ""
            author_badge = f" @{item.author}" if item.source == "x" and item.author else ""
            lines.append(f"- {title}{score_badge}{author_badge}")
            lines.append(f"  {item.url}")

    return "\n".join(lines)


def render_html(items: list[AIItem], generated_at: datetime | None = None) -> str:
    """生成 HTML 报告页面"""
    gen_at = generated_at or datetime.now()
    groups = group_by_source(items)

    sections: list[str] = []
    for source, group_items in groups.items():
        label = SOURCE_LABELS.get(source, source)
        rows: list[str] = []
        for item in group_items:
            title_html = html.escape(item.title)
            trans_html = html.escape(item.title_translated) if item.title_translated else ""
            url_html = html.escape(item.url)
            summary_html = html.escape((item.summary or "")[:200])
            source_name = html.escape(item.source_name or "")
            score_badge = (
                f'<span class="score">{item.score}🔥</span>' if item.score > 0 else ""
            )
            pub = item.published_at.strftime("%Y-%m-%d %H:%M") if item.published_at else ""
            trans_block = (
                f'<div class="title-zh"><a href="{url_html}" target="_blank">{trans_html}</a></div>'
                if trans_html
                else ""
            )
            rows.append(
                f"""
                <li class="item">
                  {trans_block}
                  <div class="title-en"><a href="{url_html}" target="_blank">{title_html}</a></div>
                  <div class="meta">
                    <span class="source">{source_name}</span>
                    {score_badge}
                    <span class="pub">{pub}</span>
                  </div>
                  {f'<div class="summary">{summary_html}</div>' if summary_html else ""}
                </li>
                """
            )

        sections.append(
            f"""
            <section class="group">
              <h2>{html.escape(label)} <span class="count">({len(group_items)})</span></h2>
              <ul class="items">
                {"".join(rows)}
              </ul>
            </section>
            """
        )

    style = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
           max-width: 900px; margin: 24px auto; padding: 0 16px; color: #222; background: #fafafa; }
    h1 { border-bottom: 2px solid #4a90e2; padding-bottom: 8px; }
    h2 { color: #4a90e2; margin-top: 32px; }
    .count { font-size: 0.8em; color: #888; }
    .items { list-style: none; padding-left: 0; }
    .item { background: #fff; margin: 12px 0; padding: 12px 16px; border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
    .title-zh a { color: #2b2b2b; font-weight: 600; text-decoration: none; font-size: 1.05em; }
    .title-en a { color: #6a6a6a; text-decoration: none; font-size: 0.95em; }
    .title-zh a:hover, .title-en a:hover { text-decoration: underline; }
    .meta { margin-top: 6px; font-size: 0.85em; color: #888; }
    .meta > * { margin-right: 10px; }
    .score { color: #e74c3c; font-weight: 600; }
    .summary { margin-top: 8px; color: #555; font-size: 0.9em; line-height: 1.5; }
    .footer { margin-top: 32px; color: #aaa; font-size: 0.8em; text-align: center; }
    """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI 前沿资讯 · {gen_at.strftime("%Y-%m-%d %H:%M")}</title>
  <style>{style}</style>
</head>
<body>
  <h1>🤖 AI 前沿资讯</h1>
  <p>共 <strong>{len(items)}</strong> 条新增 · 生成时间 {gen_at.strftime("%Y-%m-%d %H:%M:%S")}</p>
  {"".join(sections)}
  <div class="footer">Generated by TrendRadar AI Frontier</div>
</body>
</html>
"""


def save_html_report(
    items: list[AIItem],
    output_dir: str | Path = "output/ai_frontier",
    generated_at: datetime | None = None,
) -> Path:
    """保存 HTML 报告到 output/ai_frontier/YYYY-MM-DD/HH-MM.html"""
    gen_at = generated_at or datetime.now()
    base = Path(output_dir)
    day_dir = base / gen_at.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    filename = gen_at.strftime("%H-%M") + ".html"
    out_path = day_dir / filename

    html_doc = render_html(items, gen_at)
    out_path.write_text(html_doc, encoding="utf-8")
    log.success(f"HTML 报告已保存: {out_path}")
    return out_path
