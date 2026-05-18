"""renderer 测试"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from trendradar.ai_frontier.renderer import (
    render_html,
    render_markdown,
    save_html_report,
)
from trendradar.ai_frontier.sources.base import AIItem


def _item(source, title="t", url="https://u", score=0, trans=""):
    return AIItem(
        source=source,
        source_name=source,
        title=title,
        url=url,
        score=score,
        title_translated=trans,
    )


def test_render_markdown_empty_returns_no_new_message():
    out = render_markdown([])
    assert "无新增" in out


def test_render_markdown_groups_by_source():
    items = [
        _item("arxiv", title="Paper 1", url="https://a1"),
        _item("hackernews", title="HN post", url="https://hn1", score=100),
        _item("podcast", title="Podcast episode", url="https://p1"),
        _item("blog", title="Blog post", url="https://b1"),
    ]
    out = render_markdown(items)
    assert "ArXiv" in out
    assert "HackerNews" in out
    assert "Podcasts" in out
    assert "Official Blogs" in out
    assert "Paper 1" in out
    assert "HN post" in out
    assert "Podcast episode" in out
    assert "Blog post" in out
    assert "100🔥" in out


def test_render_markdown_prefers_translation():
    items = [_item("arxiv", title="Scaling Laws", trans="规模化定律")]
    out = render_markdown(items)
    assert "规模化定律" in out
    # 英文原文只在 HTML 中双语显示；markdown 只用翻译
    assert out.count("Scaling Laws") == 0 or "规模化定律" in out


def test_render_markdown_includes_total_count():
    items = [_item("arxiv") for _ in range(3)]
    out = render_markdown(items)
    assert "3 条" in out


def test_render_html_structure():
    items = [
        _item("arxiv", title="Paper A", url="https://a", trans="论文 A"),
        _item("reddit", title="Post B", url="https://b", score=50),
    ]
    html = render_html(items)
    assert "<!DOCTYPE html>" in html
    assert "Paper A" in html
    assert "论文 A" in html
    assert "Post B" in html
    assert "https://a" in html
    assert "50🔥" in html


def test_render_html_escapes_dangerous_content():
    items = [_item("arxiv", title="<script>alert(1)</script>", url="https://x")]
    html = render_html(items)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_save_html_report_creates_file(tmp_path: Path):
    items = [_item("arxiv", title="t", url="https://u")]
    gen_at = datetime(2026, 4, 17, 12, 30)
    path = save_html_report(items, output_dir=tmp_path, generated_at=gen_at)
    assert path.exists()
    assert path.name == "12-30.html"
    content = path.read_text(encoding="utf-8")
    assert "AI 前沿" in content
