# TrendRadar — Decisions & Fix Log

Record of key decisions and resolved issues to prevent repeat mistakes.

---

## 2025-04 Fixes

### 1. Incremental mode hardcoded `mode="current"`

**Problem**: `__main__.py` had hardcoded `mode="current"` in multiple places, preventing `incremental` mode from taking effect.

**Fix**: Read `report_mode` from config, replacing all hardcoded values. Added `skip_notification` logic.

### 2. RSS translation data written to news DB caused is_first_crawl misjudgment

**Problem**: `storage_manager.save_news_data(rss_news_data)` wrote RSS translations into the trending database, creating extra `crawl_record` entries, causing `is_first_crawl_today()` to always return `False`.

**Fix**: Removed that line. RSS data only writes via `save_rss_data()` to the RSS-specific database.

### 3. GitHub Actions statelessness broke incremental mode

**Problem**: Each GitHub Actions run is a fresh container; `output/` directory lost, no historical data for comparison.

**Fix**: Added `actions/cache@v4` step in `crawler.yml` to cache `output/` directory, key: `trendradar-${{ github.run_id }}`, restore-keys: `trendradar-`.

### 4. RSS displayed old+new mixed + redundant "RSS New This Time" section

**Problem**: Both `rss_stats` (all items) and `rss_new_stats` (new items) passed to renderer, causing mixed old/new in main section plus a separate redundant "RSS New" block.

**Fix**: In incremental mode (non-first crawl), regroup `rss_new_stats` by feed source to replace `rss_stats`, set `rss_new_stats = None`.

### 5. Trending grouped by keyword instead of platform

**Problem**: `convert_keyword_stats_to_platform_stats()` existed but was never called; trending always grouped by keyword.

**Fix**: In incremental mode (non-first crawl), call this function to convert trending data to platform-grouped format.

---

## Decision Records

### Git Branch Strategy

- Develop locally on `main` branch
- Push only to `master`: `git push origin main:master`
- Do NOT push both main and master

### Translation Write-back Strategy

- English titles replaced with Chinese translation directly (no bilingual concatenation)
- Original text accessible via news link
- Degrades to monolingual mode if API key missing; does not block pipeline

### Incremental Mode Display Strategy

- **Trending**: Grouped by platform (Jin10, GitHub, IT Home, etc.)
- **RSS**: Only new items, grouped by feed source (HackerNews, BBC, etc.)
- **First crawl**: Show all content (all treated as "new")
- **No new items**: Skip notification push

### Code Modification Principle

- Prefer data transformations in `__main__.py` presentation layer; avoid touching storage/detection logic
- Keep DB writes and historical comparison logic stable; only substitute data before passing to renderers
