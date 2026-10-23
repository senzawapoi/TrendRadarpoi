"""
配置加载模块

负责从 YAML 配置文件和环境变量加载配置。
"""

from typing import Any

from .settings import RuntimeSettings, load_settings


def _load_app_config(config_data: dict, settings: RuntimeSettings) -> dict:
    """加载应用配置"""
    app_config = config_data.get("app", {})
    advanced = config_data.get("advanced", {})
    return {
        "VERSION_CHECK_URL": advanced.get("version_check_url", ""),
        "SHOW_VERSION_UPDATE": app_config.get("show_version_update", True),
        "TIMEZONE": settings.timezone,
    }


def _load_crawler_config(config_data: dict, settings: RuntimeSettings) -> dict:
    """加载爬虫配置"""
    advanced = config_data.get("advanced", {})
    crawler_config = advanced.get("crawler", {})
    return {
        "REQUEST_INTERVAL": crawler_config.get("request_interval", 100),
        "USE_PROXY": crawler_config.get("use_proxy", False),
        "DEFAULT_PROXY": crawler_config.get("default_proxy", ""),
        "ENABLE_CRAWLER": settings.get_bool(
            "ENABLE_CRAWLER",
            "advanced.crawler.enabled",
            True,
        ),
    }


def _load_report_config(config_data: dict, settings: RuntimeSettings) -> dict:
    """加载报告配置"""
    report_config = config_data.get("report", {})

    return {
        "REPORT_MODE": settings.get_str("REPORT_MODE", "report.mode", "daily"),
        "DISPLAY_MODE": settings.get_str("DISPLAY_MODE", "report.display_mode", "keyword"),
        "RANK_THRESHOLD": report_config.get("rank_threshold", 10),
        "SORT_BY_POSITION_FIRST": settings.get_bool(
            "SORT_BY_POSITION_FIRST",
            "report.sort_by_position_first",
        ),
        "MAX_NEWS_PER_KEYWORD": settings.get_int(
            "MAX_NEWS_PER_KEYWORD",
            "report.max_news_per_keyword",
        ),
        "REVERSE_CONTENT_ORDER": settings.get_bool(
            "REVERSE_CONTENT_ORDER",
            "report.reverse_content_order",
        ),
    }


def _load_weight_config(config_data: dict) -> dict:
    """加载权重配置"""
    advanced = config_data.get("advanced", {})
    weight = advanced.get("weight", {})
    return {
        "RANK_WEIGHT": weight.get("rank", 0.6),
        "FREQUENCY_WEIGHT": weight.get("frequency", 0.3),
        "HOTNESS_WEIGHT": weight.get("hotness", 0.1),
    }


def _load_rss_config(config_data: dict) -> dict:
    """加载 RSS 配置"""
    rss = config_data.get("rss", {})
    advanced = config_data.get("advanced", {})
    advanced_rss = advanced.get("rss", {})
    advanced_crawler = advanced.get("crawler", {})

    # RSS 代理配置：优先使用 RSS 专属代理，否则复用 crawler 的 default_proxy
    rss_proxy_url = advanced_rss.get("proxy_url", "") or advanced_crawler.get("default_proxy", "")

    # 新鲜度过滤配置
    freshness_filter = rss.get("freshness_filter", {})

    # 验证并设置 max_age_days 默认值
    raw_max_age = freshness_filter.get("max_age_days", 3)
    try:
        max_age_days = int(raw_max_age)
        if max_age_days < 0:
            print(f"[警告] RSS freshness_filter.max_age_days 为负数 ({max_age_days})，使用默认值 3")
            max_age_days = 3
    except (ValueError, TypeError):
        print(f"[警告] RSS freshness_filter.max_age_days 格式错误 ({raw_max_age})，使用默认值 3")
        max_age_days = 3

    # RSS 配置直接从 config.yaml 读取，不再支持环境变量
    return {
        "ENABLED": rss.get("enabled", False),
        "REQUEST_INTERVAL": advanced_rss.get("request_interval", 2000),
        "TIMEOUT": advanced_rss.get("timeout", 15),
        "USE_PROXY": advanced_rss.get("use_proxy", False),
        "PROXY_URL": rss_proxy_url,
        "FEEDS": rss.get("feeds", []),
        "FRESHNESS_FILTER": {
            "ENABLED": freshness_filter.get("enabled", True),  # 默认启用
            "MAX_AGE_DAYS": max_age_days,
        },
    }


def _load_storage_config(config_data: dict, settings: RuntimeSettings) -> dict:
    """加载存储配置"""
    storage = config_data.get("storage", {})
    formats = storage.get("formats", {})

    return {
        "BACKEND": settings.get_str("STORAGE_BACKEND", "storage.backend", "auto"),
        "FORMATS": {
            "SQLITE": formats.get("sqlite", True),
            "TXT": settings.get_bool("STORAGE_TXT_ENABLED", "storage.formats.txt", True),
            "HTML": settings.get_bool("STORAGE_HTML_ENABLED", "storage.formats.html", True),
        },
        "LOCAL": {
            "DATA_DIR": str(settings.database_path),
            "RETENTION_DAYS": settings.get_int(
                "LOCAL_RETENTION_DAYS",
                "storage.local.retention_days",
            ),
        },
        "REMOTE": {
            "ENDPOINT_URL": settings.get_str(
                "S3_ENDPOINT_URL",
                "storage.remote.endpoint_url",
            ),
            "BUCKET_NAME": settings.get_str(
                "S3_BUCKET_NAME",
                "storage.remote.bucket_name",
            ),
            "ACCESS_KEY_ID": settings.get_str(
                "S3_ACCESS_KEY_ID",
                "storage.remote.access_key_id",
            ),
            "SECRET_ACCESS_KEY": settings.get_str(
                "S3_SECRET_ACCESS_KEY",
                "storage.remote.secret_access_key",
            ),
            "REGION": settings.get_str("S3_REGION", "storage.remote.region"),
            "RETENTION_DAYS": settings.get_int(
                "REMOTE_RETENTION_DAYS",
                "storage.remote.retention_days",
            ),
        },
        "PULL": {
            "ENABLED": settings.get_bool("PULL_ENABLED", "storage.pull.enabled"),
            "DAYS": settings.get_int("PULL_DAYS", "storage.pull.days", 7),
        },
    }


def _load_intelligence_config(settings: RuntimeSettings) -> dict:
    """Load the compatibility-first unified pipeline switch and local database path."""
    return {
        "ENABLED": settings.intelligence_enabled,
        "DATABASE_PATH": str(settings.intelligence_database_path),
        "STORY": settings.intelligence_story_config,
        "SECURITY": settings.intelligence_security_config,
        "ASSISTANT": settings.intelligence_assistant_config,
    }


def _load_ai_config(settings: RuntimeSettings) -> dict:
    """Load bounded Gemini settings without exposing the environment-only credential."""
    return {"GEMINI": settings.gemini_config}


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径，默认从环境变量 CONFIG_PATH 获取或使用 config/config.yaml

    Returns:
        包含所有配置的字典

    Raises:
        FileNotFoundError: 配置文件不存在
    """
    settings = load_settings(config_path)
    config_data = settings.as_dict()

    print(f"配置文件加载成功: {settings.config_path}")

    # 合并所有配置
    config = {}

    # 应用配置
    config.update(_load_app_config(config_data, settings))

    # 爬虫配置
    config.update(_load_crawler_config(config_data, settings))

    # 报告配置
    config.update(_load_report_config(config_data, settings))

    # 权重配置
    config["WEIGHT_CONFIG"] = _load_weight_config(config_data)

    # 平台配置
    config["PLATFORMS"] = config_data.get("platforms", [])

    # RSS 配置
    config["RSS"] = _load_rss_config(config_data)

    # 存储配置
    config["STORAGE"] = _load_storage_config(config_data, settings)

    # 统一情报数据层
    config["INTELLIGENCE"] = _load_intelligence_config(settings)

    # 核心 AI 服务（凭据只通过 RuntimeSettings 暴露给受控构造器）
    config["AI"] = _load_ai_config(settings)
    config["FEISHU"] = settings.feishu_config

    config["LARK"] = settings.lark_config

    return config
