"""GitHubTrendingSource 测试（离线 HTML 解析）"""

from __future__ import annotations

from trendradar.ai_frontier.sources.github_trending import GitHubTrendingSource

SAMPLE_HTML = """
<html><body>
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/openai/whisper"> openai / whisper </a>
  </h2>
  <p class="col-9 color-fg-muted my-1 pr-4">
    Robust Speech Recognition via Large-Scale Weak Supervision
  </p>
  <span itemprop="programmingLanguage">Python</span>
  <span class="d-inline-block float-sm-right">
    1,234 stars today
  </span>
</article>
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/someone/static-site-generator"> someone / static-site-generator </a>
  </h2>
  <p>A static site generator written in Rust</p>
  <span itemprop="programmingLanguage">Rust</span>
  <span class="d-inline-block float-sm-right">500 stars today</span>
</article>
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/anthropics/claude-code"> anthropics / claude-code </a>
  </h2>
  <p>Claude-powered coding agent for the terminal</p>
  <span itemprop="programmingLanguage">TypeScript</span>
  <span class="d-inline-block float-sm-right">2.3k stars today</span>
</article>
</body></html>
"""


def test_parse_stars_various_formats():
    src = GitHubTrendingSource({})
    assert src._parse_stars("1,234 stars today") == 1234
    assert src._parse_stars("2.3k stars today") == 2300
    assert src._parse_stars("1.5M stars") == 1_500_000
    assert src._parse_stars("") == 0
    assert src._parse_stars("invalid") == 0


def test_parse_html_python_lang_includes_all():
    src = GitHubTrendingSource({"languages": ["python"]})
    items = src._parse_html(SAMPLE_HTML, "python")
    # 指定语言不做关键词过滤，3 条都保留
    assert len(items) == 3
    titles = [i.title for i in items]
    assert "openai/whisper" in titles
    assert "someone/static-site-generator" in titles


def test_parse_html_unknown_lang_filters_by_keywords():
    src = GitHubTrendingSource({"languages": ["unknown"]})
    items = src._parse_html(SAMPLE_HTML, "unknown")
    # unknown 榜单需 ai_keywords 命中：whisper(ai/speech) 和 claude-code(claude) 保留
    titles = [i.title for i in items]
    assert "openai/whisper" in titles  # "ai" 命中
    assert "anthropics/claude-code" in titles  # "claude" 命中
    assert "someone/static-site-generator" not in titles  # Rust 静态站生成器被过滤


def test_parse_html_extracts_metadata():
    src = GitHubTrendingSource({"languages": ["python"]})
    items = src._parse_html(SAMPLE_HTML, "python")
    whisper = next(i for i in items if i.title == "openai/whisper")
    assert whisper.url == "https://github.com/openai/whisper"
    assert whisper.score == 1234
    assert "Python" in whisper.tags
    assert "Speech Recognition" in whisper.summary


def test_parse_html_empty_input():
    src = GitHubTrendingSource({})
    assert src._parse_html("", "python") == []
    assert src._parse_html("<html></html>", "python") == []
