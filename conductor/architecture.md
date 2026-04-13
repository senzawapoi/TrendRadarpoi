# TrendRadar — Architecture & Data Flow

## Module Responsibilities

```
trendradar/
├── __main__.py          # Main orchestrator (crawl → translate → store → detect → stats → render → push)
├── context.py           # AppContext: wraps all config-dependent operations
├── core/
│   ├── config.py        # Config loading
│   ├── loader.py        # Keyword group loading (frequency_words.txt parser)
│   ├── analyzer.py      # Keyword frequency stats, platform grouping conversion
│   ├── frequency.py     # Word frequency matching logic
│   └── data.py          # Data structure definitions
├── crawler/
│   ├── fetcher.py       # Trending platform data fetcher
│   └── rss/             # RSS feed fetcher (feedparser)
├── storage/
│   ├── base.py          # NewsData/NewsItem base data structures
│   ├── local.py         # SQLite local storage (detect_new_titles / detect_new_rss_items)
│   ├── remote.py        # S3-compatible remote storage
│   └── manager.py       # StorageManager unified entry point
├── services/
│   └── translation_service.py  # Gemini translation service wrapper
├── report/
│   ├── html.py          # HTML report renderer
│   ├── rss_html.py      # RSS-specific HTML renderer
│   ├── generator.py     # Report file generator
│   ├── formatter.py     # Formatting utilities
│   └── helpers.py       # Helper functions
├── notification/
│   ├── dispatcher.py    # Multi-channel notification dispatcher
│   ├── renderer.py      # Platform-specific message renderers
│   ├── splitter.py      # Long message batch splitter
│   ├── senders.py       # Channel-specific send implementations
│   ├── batch.py         # Batch management
│   ├── formatters.py    # Formatting helpers
│   └── push_manager.py  # Push record management
└── utils/
    ├── time.py          # Time utilities
    └── url.py           # URL utilities
```

## Main Pipeline Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    __main__.py pipeline                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Load config → AppContext                                │
│  2. Init TranslationService (Gemini API)                    │
│  3. Init StorageManager                                     │
│                                                             │
│  ┌── A. Trending Crawl ──────────────────────────────┐    │
│  │  DataFetcher.fetch_all()                             │    │
│  │       ↓                                              │    │
│  │  results: Dict[platform_id, List[title_dict]]        │    │
│  │       ↓                                              │    │
│  │  TranslationService.translate_news_items() (EN→ZH)   │    │
│  │       ↓                                              │    │
│  │  _apply_translations_to_hot_results() (write back)    │    │
│  │       ↓                                              │    │
│  │  storage_manager.save_news_data(hot_news_data)       │    │
│  │       ↓                                              │    │
│  │  detect_new_titles() → new_titles                    │    │
│  │       ↓                                              │    │
│  │  count_word_frequency() → hot_stats                  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌── B. RSS Crawl ──────────────────────────────────┐    │
│  │  RSSFetcher.fetch_all()                              │    │
│  │       ↓                                              │    │
│  │  storage_manager.save_rss_data(rss_data)             │    │
│  │       ↓                                              │    │
│  │  _convert_rss_items_to_list() → rss_items_list       │    │
│  │       ↓                                              │    │
│  │  TranslationService.translate_news_items() (EN→ZH)   │    │
│  │       ↓                                              │    │
│  │  _apply_translations_to_rss_items() (write back)     │    │
│  │       ↓                                              │    │
│  │  detect_new_rss_items() → rss_new_items_list         │    │
│  │       ↓                                              │    │
│  │  count_rss_frequency() → rss_stats + rss_new_stats   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌── C. Render & Push ───────────────────────────────┐    │
│  │                                                      │    │
│  │  [Incremental mode optimization (non-first crawl)]    │    │
│  │  ├─ hot_stats → convert_keyword_stats_to_platform    │    │
│  │  ├─ rss_stats = rss_new_stats (regroup by source)    │    │
│  │  └─ rss_new_stats = None (remove new section)        │    │
│  │                                                      │    │
│  │  [Skip check (incremental mode)]                     │    │
│  │  if !first_crawl && no_new_hot && no_new_rss → skip  │    │
│  │                                                      │    │
│  │  generate_html() → output/index.html                 │    │
│  │  dispatcher.dispatch_all() → multi-channel push       │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Key Data Structures

### Stats Format (shared by hot_stats / rss_stats)

```python
[
    {
        "word": "keyword or platform_name or feed_source_name",
        "count": 5,
        "position": 0,
        "percentage": 12.5,
        "titles": [
            {
                "title": "News headline",
                "source_name": "Source name",
                "time_display": "04-13 11:00",
                "count": 1,
                "ranks": [3],
                "rank_threshold": 5,
                "url": "https://...",
                "is_new": True,
            }
        ]
    }
]
```

### New Item Detection

- **Trending**: `detect_new_titles()` — compare current titles with same-day historical titles (SQLite)
- **RSS**: `detect_new_rss_items()` — compare current URLs with historical URLs (SQLite)
- **First crawl check**: `is_first_crawl_today()` — check if crawl_record exists for today

## SQLite Storage Layout

```
output/
├── YYYY-MM-DD/
│   ├── news_data.db    # Trending data (crawl_record + news_items + bilingual)
│   └── rss_data.db     # RSS data (rss_crawl_record + rss_items)
└── ...
