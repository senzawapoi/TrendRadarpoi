# TrendRadar — Product Definition

> Hot news aggregation and analysis tool. Automatically crawls multi-platform trending lists and RSS feeds, filters by keyword matching, and pushes notifications through multiple channels.

## Basic Info

- **Version**: 4.7.0
- **Python**: >=3.10
- **Entry**: `python -m trendradar` or `trendradar` (after install)
- **GitHub**: https://github.com/senzawapoi/TrendRadarpoi.git
- **Branch**: `master` (primary deployment branch)

## Core Features

### Dual-Path Data Crawling

1. **Trending Platforms** (`platforms`) — Crawl real-time trending lists via APIs
2. **RSS Feeds** (`rss.feeds`) — Parse RSS/Atom feeds via feedparser

### Keyword Matching & Statistics

- Regex-based word group matching (`frequency_words.txt`)
- Required words + normal words combo filtering
- Group by keyword or by platform/source

### Three Report Modes

| Mode | Push Trigger | Content |
|------|-------------|----------|
| **daily** | Scheduled | All matched news today + new items section |
| **current** | Scheduled | Current list matched news + new items section |
| **incremental** | Only on new items | New items only; hot news grouped by platform, RSS grouped by feed source |

### Auto Translation

- **Engine**: Google Gemini API (wrapped by `TranslationService`)
- **API Key**: Environment variable `GEMINI_API_KEY` (via GitHub Secrets)
- **Logic**: Auto-detect English titles → translate to Chinese; Chinese titles unchanged
- **Scope**: Hot news titles + RSS titles + summaries
- **Write-back**: Translated text replaces original title; original accessible via link
- **Fallback**: Degrades to monolingual mode if API key missing or init fails

### Multi-Channel Notification

Supported: Bark, Feishu (Lark), DingTalk, WeCom, Telegram, Email, ntfy, Slack

### MCP Server

Provides AI query interface for historical news data via MCP (Model Context Protocol).

## Current User Configuration

- **Report mode**: `incremental`
- **Display mode**: `platform` (group by platform/source)
- **Trending platforms**: Jin10, GitHub, IT Home, FastBull Express
- **RSS feeds**: 18 sources (HackerNews, BBC, CNN, ArsTechnica, TechCrunch AI, NVIDIA Blog, etc.)
- **Notification channel**: Bark
- **Deployment**: GitHub Actions (runs at minute 30 every hour)
- **Translation**: Gemini API bilingual translation enabled
