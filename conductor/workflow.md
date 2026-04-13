# TrendRadar — Development Workflow

## Git Workflow

- **Local branch**: `main`
- **Remote push**: Only push to `master` → `git push origin main:master`
- **Commit convention**: `feat:` / `fix:` / `docs:` prefix

## Local Development & Testing

```bash
# Run full pipeline
py -m trendradar

# Output directory
output/YYYY-MM-DD/   # SQLite data + HTML report
output/index.html    # Latest HTML report
```

## Modification Principles

1. **Presentation layer first**: Prefer data transformations in `__main__.py` Section C (before render & push)
2. **Keep base stable**: Avoid modifying detection logic in `storage/local.py` (`detect_new_titles`, `detect_new_rss_items`)
3. **Reuse format**: New grouping approaches reuse existing stats format `[{"word": "...", "count": N, "titles": [...]}]`; zero changes to downstream renderers

## Key Environment Variables

| Variable | Purpose | Config Location |
|----------|---------|----------------|
| `GEMINI_API_KEY` | Gemini Translation API | GitHub Secrets |
| `BARK_URL` | Bark push URL | GitHub Secrets or config.yaml |

## GitHub Actions Deployment

- **Workflow file**: `.github/workflows/crawler.yml`
- **Frequency**: Minute 30 every hour
- **Cache**: `actions/cache@v4` persists `output/` directory
- **Check-in mechanism**: 7-day cycle, requires manual Check In to renew

## Configuration Files

| File | Description |
|------|-------------|
| `config/config.yaml` | Main config (platforms, RSS, report mode, notification channels, storage) |
| `config/frequency_words.txt` | Keyword groups (regex support, `/pattern/i => display_name` syntax) |
| `config/frequency_words_backup` | Keyword backup |
