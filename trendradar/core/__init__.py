"""
核心模块 - 配置管理和核心工具
"""

from trendradar.core.analyzer import (
    calculate_news_weight,
    count_rss_frequency,
    count_word_frequency,
    format_time_display,
)
from trendradar.core.config import (
    get_account_at_index,
    limit_accounts,
    parse_multi_account_config,
    validate_paired_configs,
)
from trendradar.core.data import (
    detect_latest_new_titles,
    detect_latest_new_titles_from_storage,
    is_first_crawl_today,
    read_all_today_titles,
    read_all_today_titles_from_storage,
    save_titles_to_file,
)
from trendradar.core.exceptions import (
    BatchFailure,
    BatchResult,
    BatchSuccess,
    ConfigError,
    FetchError,
    NotificationError,
    NotificationPartialFailure,
    RSSFetchError,
    StorageError,
    StorageReadError,
    StorageWriteError,
    TranslationBatchError,
    TranslationError,
    TrendRadarError,
    ValidationError,
)
from trendradar.core.frequency import load_frequency_words, matches_word_groups
from trendradar.core.loader import load_config

__all__ = [
    "parse_multi_account_config",
    "validate_paired_configs",
    "limit_accounts",
    "get_account_at_index",
    "load_config",
    "load_frequency_words",
    "matches_word_groups",
    # 数据处理
    "save_titles_to_file",
    "read_all_today_titles_from_storage",
    "read_all_today_titles",
    "detect_latest_new_titles_from_storage",
    "detect_latest_new_titles",
    "is_first_crawl_today",
    # 统计分析
    "calculate_news_weight",
    "format_time_display",
    "count_word_frequency",
    "count_rss_frequency",
    # 异常
    "TrendRadarError",
    "FetchError",
    "RSSFetchError",
    "TranslationError",
    "TranslationBatchError",
    "StorageError",
    "StorageReadError",
    "StorageWriteError",
    "NotificationError",
    "NotificationPartialFailure",
    "ConfigError",
    "ValidationError",
    "BatchResult",
    "BatchSuccess",
    "BatchFailure",
]
