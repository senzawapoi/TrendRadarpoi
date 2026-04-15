"""
应用上下文模块

提供配置上下文类，封装所有依赖配置的操作，消除全局状态和包装函数。
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from trendradar.core import (
    count_word_frequency,
    detect_latest_new_titles,
    load_frequency_words,
    matches_word_groups,
    read_all_today_titles,
    save_titles_to_file,
)
from trendradar.notification import (
    NotificationDispatcher,
    PushRecordManager,
    render_dingtalk_content,
    render_feishu_content,
    split_content_into_batches,
)
from trendradar.report import (
    clean_title,
    generate_html_report,
    prepare_report_data,
    render_html_content,
)
from trendradar.storage import get_storage_manager
from trendradar.utils.time import (
    convert_time_for_display,
    format_date_folder,
    format_time_filename,
    get_configured_time,
    get_current_time_display,
)


class AppContext:
    """
    应用上下文类

    封装所有依赖配置的操作，提供统一的接口。
    消除对全局 CONFIG 的依赖，提高可测试性。

    使用示例:
        config = load_config()
        ctx = AppContext(config)

        # 时间操作
        now = ctx.get_time()
        date_folder = ctx.format_date()

        # 存储操作
        storage = ctx.get_storage_manager()

        # 报告生成
        html = ctx.generate_html_report(stats, total_titles, ...)
    """

    def __init__(self, config: dict[str, Any]):
        """
        初始化应用上下文

        Args:
            config: 完整的配置字典
        """
        self.config = config
        self._storage_manager = None

    # === 配置访问 ===

    @property
    def timezone(self) -> str:
        """获取配置的时区"""
        return self.config.get("TIMEZONE", "Asia/Shanghai")

    @property
    def rank_threshold(self) -> int:
        """获取排名阈值"""
        return self.config.get("RANK_THRESHOLD", 50)

    @property
    def weight_config(self) -> dict:
        """获取权重配置"""
        return self.config.get("WEIGHT_CONFIG", {})

    @property
    def platforms(self) -> list[dict]:
        """获取平台配置列表"""
        return self.config.get("PLATFORMS", [])

    @property
    def platform_ids(self) -> list[str]:
        """获取平台ID列表"""
        return [p["id"] for p in self.platforms]

    @property
    def rss_config(self) -> dict:
        """获取 RSS 配置"""
        return self.config.get("RSS", {})

    @property
    def rss_enabled(self) -> bool:
        """RSS 是否启用"""
        return self.rss_config.get("ENABLED", False)

    @property
    def rss_feeds(self) -> list[dict]:
        """获取 RSS 源列表"""
        return self.rss_config.get("FEEDS", [])

    @property
    def display_mode(self) -> str:
        """获取显示模式 (keyword | platform)"""
        return self.config.get("DISPLAY_MODE", "keyword")

    # === 时间操作 ===

    def get_time(self) -> datetime:
        """获取当前配置时区的时间"""
        return get_configured_time(self.timezone)

    def format_date(self) -> str:
        """格式化日期文件夹 (YYYY-MM-DD)"""
        return format_date_folder(timezone=self.timezone)

    def format_time(self) -> str:
        """格式化时间文件名 (HH-MM)"""
        return format_time_filename(self.timezone)

    def get_time_display(self) -> str:
        """获取时间显示 (HH:MM)"""
        return get_current_time_display(self.timezone)

    @staticmethod
    def convert_time_display(time_str: str) -> str:
        """将 HH-MM 转换为 HH:MM"""
        return convert_time_for_display(time_str)

    # === 存储操作 ===

    def get_storage_manager(self):
        """获取存储管理器（延迟初始化，单例）"""
        if self._storage_manager is None:
            storage_config = self.config.get("STORAGE", {})
            remote_config = storage_config.get("REMOTE", {})
            local_config = storage_config.get("LOCAL", {})
            pull_config = storage_config.get("PULL", {})

            self._storage_manager = get_storage_manager(
                backend_type=storage_config.get("BACKEND", "auto"),
                data_dir=local_config.get("DATA_DIR", "output"),
                enable_txt=storage_config.get("FORMATS", {}).get("TXT", True),
                enable_html=storage_config.get("FORMATS", {}).get("HTML", True),
                remote_config={
                    "bucket_name": remote_config.get("BUCKET_NAME", ""),
                    "access_key_id": remote_config.get("ACCESS_KEY_ID", ""),
                    "secret_access_key": remote_config.get("SECRET_ACCESS_KEY", ""),
                    "endpoint_url": remote_config.get("ENDPOINT_URL", ""),
                    "region": remote_config.get("REGION", ""),
                },
                local_retention_days=local_config.get("RETENTION_DAYS", 0),
                remote_retention_days=remote_config.get("RETENTION_DAYS", 0),
                pull_enabled=pull_config.get("ENABLED", False),
                pull_days=pull_config.get("DAYS", 7),
                timezone=self.timezone,
            )
        return self._storage_manager

    def get_output_path(self, subfolder: str, filename: str) -> str:
        """获取输出路径"""
        output_dir = Path("output") / self.format_date() / subfolder
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / filename)

    # === 数据处理 ===

    def save_titles(self, results: dict, id_to_name: dict, failed_ids: list) -> str:
        """保存标题到文件"""
        output_path = self.get_output_path("txt", f"{self.format_time()}.txt")
        return save_titles_to_file(results, id_to_name, failed_ids, output_path, clean_title)

    def read_today_titles(
        self, platform_ids: list[str] | None = None, quiet: bool = False
    ) -> tuple[dict, dict, dict]:
        """读取当天所有标题"""
        return read_all_today_titles(self.get_storage_manager(), platform_ids, quiet=quiet)

    def detect_new_titles(
        self, platform_ids: list[str] | None = None, quiet: bool = False
    ) -> dict:
        """检测最新批次的新增标题"""
        return detect_latest_new_titles(self.get_storage_manager(), platform_ids, quiet=quiet)

    def is_first_crawl(self) -> bool:
        """检测是否是当天第一次爬取"""
        return self.get_storage_manager().is_first_crawl_today()

    # === 频率词处理 ===

    def load_frequency_words(
        self, frequency_file: str | None = None
    ) -> tuple[list[dict], list[str], list[str]]:
        """加载频率词配置"""
        return load_frequency_words(frequency_file)

    def matches_word_groups(
        self,
        title: str,
        word_groups: list[dict],
        filter_words: list[str],
        global_filters: list[str] | None = None,
    ) -> bool:
        """检查标题是否匹配词组规则"""
        return matches_word_groups(title, word_groups, filter_words, global_filters)

    # === 统计分析 ===

    def count_frequency(
        self,
        results: dict,
        word_groups: list[dict],
        filter_words: list[str],
        id_to_name: dict,
        title_info: dict | None = None,
        new_titles: dict | None = None,
        mode: str = "daily",
        global_filters: list[str] | None = None,
        quiet: bool = False,
    ) -> tuple[list[dict], int]:
        """统计词频"""
        return count_word_frequency(
            results=results,
            word_groups=word_groups,
            filter_words=filter_words,
            id_to_name=id_to_name,
            title_info=title_info,
            rank_threshold=self.rank_threshold,
            new_titles=new_titles,
            mode=mode,
            global_filters=global_filters,
            weight_config=self.weight_config,
            max_news_per_keyword=self.config.get("MAX_NEWS_PER_KEYWORD", 0),
            sort_by_position_first=self.config.get("SORT_BY_POSITION_FIRST", False),
            is_first_crawl_func=self.is_first_crawl,
            convert_time_func=self.convert_time_display,
            quiet=quiet,
        )

    # === 报告生成 ===

    def prepare_report(
        self,
        stats: list[dict],
        failed_ids: list | None = None,
        new_titles: dict | None = None,
        id_to_name: dict | None = None,
        mode: str = "daily",
    ) -> dict:
        """准备报告数据"""
        return prepare_report_data(
            stats=stats,
            failed_ids=failed_ids,
            new_titles=new_titles,
            id_to_name=id_to_name,
            mode=mode,
            rank_threshold=self.rank_threshold,
            matches_word_groups_func=self.matches_word_groups,
            load_frequency_words_func=self.load_frequency_words,
        )

    def generate_html(
        self,
        stats: list[dict],
        total_titles: int,
        failed_ids: list | None = None,
        new_titles: dict | None = None,
        id_to_name: dict | None = None,
        mode: str = "daily",
        is_daily_summary: bool = False,
        update_info: dict | None = None,
        rss_items: list[dict] | None = None,
        rss_new_items: list[dict] | None = None,
    ) -> str:
        """生成HTML报告"""
        return generate_html_report(
            stats=stats,
            total_titles=total_titles,
            failed_ids=failed_ids,
            new_titles=new_titles,
            id_to_name=id_to_name,
            mode=mode,
            is_daily_summary=is_daily_summary,
            update_info=update_info,
            rank_threshold=self.rank_threshold,
            output_dir="output",
            date_folder=self.format_date(),
            time_filename=self.format_time(),
            render_html_func=lambda *args, **kwargs: self.render_html(*args, rss_items=rss_items, rss_new_items=rss_new_items, **kwargs),
            matches_word_groups_func=self.matches_word_groups,
            load_frequency_words_func=self.load_frequency_words,
            enable_index_copy=True,
        )

    def render_html(
        self,
        report_data: dict,
        total_titles: int,
        is_daily_summary: bool = False,
        mode: str = "daily",
        update_info: dict | None = None,
        rss_items: list[dict] | None = None,
        rss_new_items: list[dict] | None = None,
    ) -> str:
        """渲染HTML内容"""
        return render_html_content(
            report_data=report_data,
            total_titles=total_titles,
            is_daily_summary=is_daily_summary,
            mode=mode,
            update_info=update_info,
            reverse_content_order=self.config.get("REVERSE_CONTENT_ORDER", False),
            get_time_func=self.get_time,
            rss_items=rss_items,
            rss_new_items=rss_new_items,
            display_mode=self.display_mode,
        )

    # === 通知内容渲染 ===

    def render_feishu(
        self,
        report_data: dict,
        update_info: dict | None = None,
        mode: str = "daily",
    ) -> str:
        """渲染飞书内容"""
        return render_feishu_content(
            report_data=report_data,
            update_info=update_info,
            mode=mode,
            separator=self.config.get("FEISHU_MESSAGE_SEPARATOR", "---"),
            reverse_content_order=self.config.get("REVERSE_CONTENT_ORDER", False),
            get_time_func=self.get_time,
        )

    def render_dingtalk(
        self,
        report_data: dict,
        update_info: dict | None = None,
        mode: str = "daily",
    ) -> str:
        """渲染钉钉内容"""
        return render_dingtalk_content(
            report_data=report_data,
            update_info=update_info,
            mode=mode,
            reverse_content_order=self.config.get("REVERSE_CONTENT_ORDER", False),
            get_time_func=self.get_time,
        )

    def split_content(
        self,
        report_data: dict,
        format_type: str,
        update_info: dict | None = None,
        max_bytes: int | None = None,
        mode: str = "daily",
        rss_items: list | None = None,
        rss_new_items: list | None = None,
    ) -> list[str]:
        """分批处理消息内容（支持热榜+RSS合并）

        Args:
            report_data: 报告数据
            format_type: 格式类型
            update_info: 更新信息
            max_bytes: 最大字节数
            mode: 报告模式
            rss_items: RSS 统计条目列表
            rss_new_items: RSS 新增条目列表

        Returns:
            分批后的消息内容列表
        """
        return split_content_into_batches(
            report_data=report_data,
            format_type=format_type,
            update_info=update_info,
            max_bytes=max_bytes,
            mode=mode,
            batch_sizes={
                "dingtalk": self.config.get("DINGTALK_BATCH_SIZE", 20000),
                "feishu": self.config.get("FEISHU_BATCH_SIZE", 29000),
                "default": self.config.get("MESSAGE_BATCH_SIZE", 4000),
            },
            feishu_separator=self.config.get("FEISHU_MESSAGE_SEPARATOR", "---"),
            reverse_content_order=self.config.get("REVERSE_CONTENT_ORDER", False),
            get_time_func=self.get_time,
            rss_items=rss_items,
            rss_new_items=rss_new_items,
            timezone=self.config.get("TIMEZONE", "Asia/Shanghai"),
            display_mode=self.display_mode,
        )

    # === 通知发送 ===

    def create_notification_dispatcher(self) -> NotificationDispatcher:
        """创建通知调度器"""
        return NotificationDispatcher(
            config=self.config,
            get_time_func=self.get_time,
            split_content_func=self.split_content,
        )

    def create_push_manager(self) -> PushRecordManager:
        """创建推送记录管理器"""
        return PushRecordManager(
            storage_backend=self.get_storage_manager(),
            get_time_func=self.get_time,
        )

    # === 资源清理 ===

    def cleanup(self):
        """清理资源"""
        if self._storage_manager:
            self._storage_manager.cleanup_old_data()
            self._storage_manager.cleanup()
            self._storage_manager = None
