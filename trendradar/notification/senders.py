"""
消息发送器模块

将报告数据发送到各种通知渠道：
- 飞书 (Feishu/Lark)
- 钉钉 (DingTalk)
- 企业微信 (WeCom/WeWork)
- Telegram
- 邮件 (Email)
- ntfy
- Bark
- Slack

基于: python-resilience skill — tenacity retry with exponential backoff
基于: python-observability skill — structured logging
"""

import smtplib
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from urllib.parse import urlparse

import requests

from trendradar.core.exceptions import NotificationError
from trendradar.utils.logging import log

from .batch import add_batch_headers, get_max_batch_header_size
from .formatters import convert_markdown_to_mrkdwn, strip_markdown

# ── HTTP helpers with retry ────────────────────────────────────────────────────
# 基于: python-resilience skill — exponential backoff retry


@contextmanager
def _http_session(proxies: dict[str, str] | None = None):
    """
    Context manager for HTTP session with automatic cleanup.

    基于: python-resource-management skill — context managers for resource lifecycle
    """
    session = requests.Session()
    if proxies:
        session.proxies = proxies
    try:
        yield session
    finally:
        session.close()


def _http_post_with_retry(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict | None = None,
    data: bytes | None = None,
    proxies: dict[str, str] | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    channel: str = "HTTP",
) -> requests.Response:
    """
    HTTP POST with exponential backoff retry.

    基于: python-resilience skill — Exponential backoff retry for transient failures
    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            with _http_session(proxies) as session:
                response = session.post(
                    url,
                    headers=headers,
                    json=json,
                    data=data,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.HTTPError) as e:
            last_error = e
            if attempt < max_retries:
                wait = min(2 ** attempt, 10)
                log.warning(f"{channel} 请求失败，将在 {wait}s 后重试", attempt=attempt, max_retries=max_retries, wait_s=wait, error=str(e))
                time.sleep(wait)
            else:
                log.error(f"{channel} 请求失败（重试耗尽）", error=str(e))

    raise NotificationError(f"{channel} 请求失败（重试 {max_retries} 次后）: {last_error}")


# === SMTP 邮件配置 ===
SMTP_CONFIGS = {
    # Gmail（使用 STARTTLS）
    "gmail.com": {"server": "smtp.gmail.com", "port": 587, "encryption": "TLS"},
    # QQ邮箱（使用 SSL，更稳定）
    "qq.com": {"server": "smtp.qq.com", "port": 465, "encryption": "SSL"},
    # Outlook（使用 STARTTLS）
    "outlook.com": {"server": "smtp-mail.outlook.com", "port": 587, "encryption": "TLS"},
    "hotmail.com": {"server": "smtp-mail.outlook.com", "port": 587, "encryption": "TLS"},
    "live.com": {"server": "smtp-mail.outlook.com", "port": 587, "encryption": "TLS"},
    # 网易邮箱（使用 SSL，更稳定）
    "163.com": {"server": "smtp.163.com", "port": 465, "encryption": "SSL"},
    "126.com": {"server": "smtp.126.com", "port": 465, "encryption": "SSL"},
    # 新浪邮箱（使用 SSL）
    "sina.com": {"server": "smtp.sina.com", "port": 465, "encryption": "SSL"},
    # 搜狐邮箱（使用 SSL）
    "sohu.com": {"server": "smtp.sohu.com", "port": 465, "encryption": "SSL"},
    # 天翼邮箱（使用 SSL）
    "189.cn": {"server": "smtp.189.cn", "port": 465, "encryption": "SSL"},
    # 阿里云邮箱（使用 TLS）
    "aliyun.com": {"server": "smtp.aliyun.com", "port": 465, "encryption": "TLS"},
    # Yandex邮箱（使用 TLS）
    "yandex.com": {"server": "smtp.yandex.com", "port": 465, "encryption": "TLS"},
    # iCloud邮箱（使用 SSL）
    "icloud.com": {"server": "smtp.mail.me.com", "port": 587, "encryption": "SSL"},
}


def send_to_feishu(
    webhook_url: str,
    report_data: dict,
    report_type: str,
    update_info: dict | None = None,
    proxy_url: str | None = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 29000,
    batch_interval: float = 1.0,
    split_content_func: Callable = None,
    get_time_func: Callable = None,
    rss_items: list | None = None,
    rss_new_items: list | None = None,
) -> bool:
    """
    发送到飞书（支持分批发送，支持热榜+RSS合并）

    Args:
        webhook_url: 飞书 Webhook URL
        report_data: 报告数据
        report_type: 报告类型
        update_info: 更新信息（可选）
        proxy_url: 代理 URL（可选）
        mode: 报告模式 (daily/current)
        account_label: 账号标签（多账号时显示）
        batch_size: 批次大小（字节）
        batch_interval: 批次发送间隔（秒）
        split_content_func: 内容分批函数
        get_time_func: 获取当前时间的函数
        rss_items: RSS 统计条目列表（可选，用于合并推送）
        rss_new_items: RSS 新增条目列表（可选，用于新增区块）

    Returns:
        bool: 发送是否成功
    """
    headers = {"Content-Type": "application/json"}
    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    # 日志前缀
    log_prefix = f"飞书{account_label}" if account_label else "飞书"

    # 预留批次头部空间，避免添加头部后超限
    header_reserve = get_max_batch_header_size("feishu")
    batches = split_content_func(
        report_data,
        "feishu",
        update_info,
        max_bytes=batch_size - header_reserve,
        mode=mode,
        rss_items=rss_items,
        rss_new_items=rss_new_items,
    )

    # 统一添加批次头部（已预留空间，不会超限）
    batches = add_batch_headers(batches, "feishu", batch_size)

    log.info(f"{log_prefix}消息分为 {len(batches)} 批次发送", channel=log_prefix, report_type=report_type, batch_count=len(batches))

    # 逐批发送
    for i, batch_content in enumerate(batches, 1):
        content_size = len(batch_content.encode("utf-8"))
        log.info(f"发送{log_prefix}第 {i}/{len(batches)} 批次", channel=log_prefix, batch=i, total_batches=len(batches), size_bytes=content_size, report_type=report_type)

        total_titles = sum(
            len(stat["titles"]) for stat in report_data["stats"] if stat["count"] > 0
        )
        now = get_time_func() if get_time_func else datetime.now()

        payload = {
            "msg_type": "text",
            "content": {
                "total_titles": total_titles,
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "report_type": report_type,
                "text": batch_content,
            },
        }

        try:
            response = requests.post(
                webhook_url, headers=headers, json=payload, proxies=proxies, timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                # 检查飞书的响应状态
                if result.get("StatusCode") == 0 or result.get("code") == 0:
                    log.success(f"{log_prefix}第 {i}/{len(batches)} 批次发送成功", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type)
                    # 批次间间隔
                    if i < len(batches):
                        time.sleep(batch_interval)
                else:
                    error_msg = result.get("msg") or result.get("StatusMessage", "未知错误")
                    log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=error_msg)
                    return False
            else:
                log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, status_code=response.status_code)
                return False
        except requests.exceptions.RequestException as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))
            return False
        except Exception as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))
            return False

    log.success(f"{log_prefix}所有 {len(batches)} 批次发送完成", channel=log_prefix, report_type=report_type, batch_count=len(batches))
    return True


def send_to_dingtalk(
    webhook_url: str,
    report_data: dict,
    report_type: str,
    update_info: dict | None = None,
    proxy_url: str | None = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 20000,
    batch_interval: float = 1.0,
    split_content_func: Callable = None,
    rss_items: list | None = None,
    rss_new_items: list | None = None,
) -> bool:
    """
    发送到钉钉（支持分批发送，支持热榜+RSS合并）

    Args:
        webhook_url: 钉钉 Webhook URL
        report_data: 报告数据
        report_type: 报告类型
        update_info: 更新信息（可选）
        proxy_url: 代理 URL（可选）
        mode: 报告模式 (daily/current)
        account_label: 账号标签（多账号时显示）
        batch_size: 批次大小（字节）
        batch_interval: 批次发送间隔（秒）
        split_content_func: 内容分批函数
        rss_items: RSS 统计条目列表（可选，用于合并推送）
        rss_new_items: RSS 新增条目列表（可选，用于新增区块）

    Returns:
        bool: 发送是否成功
    """
    headers = {"Content-Type": "application/json"}
    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    # 日志前缀
    log_prefix = f"钉钉{account_label}" if account_label else "钉钉"

    # 预留批次头部空间，避免添加头部后超限
    header_reserve = get_max_batch_header_size("dingtalk")
    batches = split_content_func(
        report_data,
        "dingtalk",
        update_info,
        max_bytes=batch_size - header_reserve,
        mode=mode,
        rss_items=rss_items,
        rss_new_items=rss_new_items,
    )

    # 统一添加批次头部（已预留空间，不会超限）
    batches = add_batch_headers(batches, "dingtalk", batch_size)

    log.info(f"{log_prefix}消息分为 {len(batches)} 批次发送", channel=log_prefix, report_type=report_type, batch_count=len(batches))

    # 逐批发送
    for i, batch_content in enumerate(batches, 1):
        content_size = len(batch_content.encode("utf-8"))
        log.info(f"发送{log_prefix}第 {i}/{len(batches)} 批次", channel=log_prefix, batch=i, total_batches=len(batches), size_bytes=content_size, report_type=report_type)

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"TrendRadar 热点分析报告 - {report_type}",
                "text": batch_content,
            },
        }

        try:
            response = requests.post(
                webhook_url, headers=headers, json=payload, proxies=proxies, timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    log.success(f"{log_prefix}第 {i}/{len(batches)} 批次发送成功", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type)
                    # 批次间间隔
                    if i < len(batches):
                        time.sleep(batch_interval)
                else:
                    log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=result.get("errmsg"))
                    return False
            else:
                log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, status_code=response.status_code)
                return False
        except requests.exceptions.RequestException as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))
            return False
        except Exception as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))
            return False

    log.success(f"{log_prefix}所有 {len(batches)} 批次发送完成", channel=log_prefix, report_type=report_type, batch_count=len(batches))
    return True


def send_to_wework(
    webhook_url: str,
    report_data: dict,
    report_type: str,
    update_info: dict | None = None,
    proxy_url: str | None = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 4000,
    batch_interval: float = 1.0,
    msg_type: str = "markdown",
    split_content_func: Callable = None,
    rss_items: list | None = None,
    rss_new_items: list | None = None,
) -> bool:
    """
    发送到企业微信（支持分批发送，支持 markdown 和 text 两种格式，支持热榜+RSS合并）

    Args:
        webhook_url: 企业微信 Webhook URL
        report_data: 报告数据
        report_type: 报告类型
        update_info: 更新信息（可选）
        proxy_url: 代理 URL（可选）
        mode: 报告模式 (daily/current)
        account_label: 账号标签（多账号时显示）
        batch_size: 批次大小（字节）
        batch_interval: 批次发送间隔（秒）
        msg_type: 消息类型 (markdown/text)
        split_content_func: 内容分批函数
        rss_items: RSS 统计条目列表（可选，用于合并推送）
        rss_new_items: RSS 新增条目列表（可选，用于新增区块）

    Returns:
        bool: 发送是否成功
    """
    headers = {"Content-Type": "application/json"}
    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    # 日志前缀
    log_prefix = f"企业微信{account_label}" if account_label else "企业微信"

    # 获取消息类型配置（markdown 或 text）
    is_text_mode = msg_type.lower() == "text"

    if is_text_mode:
        log.info(f"{log_prefix}使用 text 格式（个人微信模式）", channel=log_prefix, report_type=report_type, msg_type="text")
    else:
        log.info(f"{log_prefix}使用 markdown 格式（群机器人模式）", channel=log_prefix, report_type=report_type, msg_type="markdown")

    # text 模式使用 wework_text，markdown 模式使用 wework
    header_format_type = "wework_text" if is_text_mode else "wework"

    # 获取分批内容，预留批次头部空间
    header_reserve = get_max_batch_header_size(header_format_type)
    batches = split_content_func(
        report_data, "wework", update_info, max_bytes=batch_size - header_reserve, mode=mode,
        rss_items=rss_items,
        rss_new_items=rss_new_items,
    )

    # 统一添加批次头部（已预留空间，不会超限）
    batches = add_batch_headers(batches, header_format_type, batch_size)

    log.info(f"{log_prefix}消息分为 {len(batches)} 批次发送", channel=log_prefix, report_type=report_type, batch_count=len(batches))

    # 逐批发送
    for i, batch_content in enumerate(batches, 1):
        # 根据消息类型构建 payload
        if is_text_mode:
            # text 格式：去除 markdown 语法
            plain_content = strip_markdown(batch_content)
            payload = {"msgtype": "text", "text": {"content": plain_content}}
            content_size = len(plain_content.encode("utf-8"))
        else:
            # markdown 格式：保持原样
            payload = {"msgtype": "markdown", "markdown": {"content": batch_content}}
            content_size = len(batch_content.encode("utf-8"))

        log.info(f"发送{log_prefix}第 {i}/{len(batches)} 批次", channel=log_prefix, batch=i, total_batches=len(batches), size_bytes=content_size, report_type=report_type)

        try:
            response = requests.post(
                webhook_url, headers=headers, json=payload, proxies=proxies, timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    log.success(f"{log_prefix}第 {i}/{len(batches)} 批次发送成功", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type)
                    # 批次间间隔
                    if i < len(batches):
                        time.sleep(batch_interval)
                else:
                    log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=result.get("errmsg"))
                    return False
            else:
                log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, status_code=response.status_code)
                return False
        except requests.exceptions.RequestException as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))
            return False
        except Exception as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))

    log.success(f"{log_prefix}所有 {len(batches)} 批次发送完成", channel=log_prefix, report_type=report_type, batch_count=len(batches))
    return True


def send_to_telegram(
    bot_token: str,
    chat_id: str,
    report_data: dict,
    report_type: str,
    update_info: dict | None = None,
    proxy_url: str | None = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 4000,
    batch_interval: float = 1.0,
    split_content_func: Callable = None,
    rss_items: list | None = None,
    rss_new_items: list | None = None,
) -> bool:
    """
    发送到 Telegram（支持分批发送，支持热榜+RSS合并）

    Args:
        bot_token: Telegram Bot Token
        chat_id: Telegram Chat ID
        report_data: 报告数据
        report_type: 报告类型
        update_info: 更新信息（可选）
        proxy_url: 代理 URL（可选）
        mode: 报告模式 (daily/current)
        account_label: 账号标签（多账号时显示）
        batch_size: 批次大小（字节）
        batch_interval: 批次发送间隔（秒）
        split_content_func: 内容分批函数
        rss_items: RSS 统计条目列表（可选，用于合并推送）
        rss_new_items: RSS 新增条目列表（可选，用于新增区块）

    Returns:
        bool: 发送是否成功
    """
    headers = {"Content-Type": "application/json"}
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    # 日志前缀
    log_prefix = f"Telegram{account_label}" if account_label else "Telegram"

    # 获取分批内容，预留批次头部空间
    header_reserve = get_max_batch_header_size("telegram")
    batches = split_content_func(
        report_data, "telegram", update_info, max_bytes=batch_size - header_reserve, mode=mode,
        rss_items=rss_items,
        rss_new_items=rss_new_items,
    )

    # 统一添加批次头部（已预留空间，不会超限）
    batches = add_batch_headers(batches, "telegram", batch_size)

    log.info(f"{log_prefix}消息分为 {len(batches)} 批次发送", channel=log_prefix, report_type=report_type, batch_count=len(batches))

    # 逐批发送
    for i, batch_content in enumerate(batches, 1):
        content_size = len(batch_content.encode("utf-8"))
        log.info(f"发送{log_prefix}第 {i}/{len(batches)} 批次", channel=log_prefix, batch=i, total_batches=len(batches), size_bytes=content_size, report_type=report_type)

        payload = {
            "chat_id": chat_id,
            "text": batch_content,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(
                url, headers=headers, json=payload, proxies=proxies, timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    log.success(f"{log_prefix}第 {i}/{len(batches)} 批次发送成功", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type)
                    # 批次间间隔
                    if i < len(batches):
                        time.sleep(batch_interval)
                else:
                    log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=result.get("description"))
                    return False
            else:
                log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, status_code=response.status_code)
                return False
        except requests.exceptions.RequestException as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))
            return False
        except Exception as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))

    log.success(f"{log_prefix}所有 {len(batches)} 批次发送完成", channel=log_prefix, report_type=report_type, batch_count=len(batches))
    return True


def send_to_email(
    from_email: str,
    password: str,
    to_email: str,
    report_type: str,
    html_file_path: str,
    custom_smtp_server: str | None = None,
    custom_smtp_port: int | None = None,
    *,
    get_time_func: Callable = None,
) -> bool:
    """
    发送邮件通知

    Args:
        from_email: 发件人邮箱
        password: 邮箱密码/授权码
        to_email: 收件人邮箱（多个用逗号分隔）
        report_type: 报告类型
        html_file_path: HTML 报告文件路径
        custom_smtp_server: 自定义 SMTP 服务器（可选）
        custom_smtp_port: 自定义 SMTP 端口（可选）
        get_time_func: 获取当前时间的函数

    Returns:
        bool: 发送是否成功
    """
    try:
        if not html_file_path or not Path(html_file_path).exists():
            log.error("邮件发送失败：HTML文件不存在或未提供", html_file=html_file_path)
            return False

        log.debug("使用HTML文件", html_file=html_file_path)
        with open(html_file_path, encoding="utf-8") as f:
            html_content = f.read()

        domain = from_email.split("@")[-1].lower()

        if custom_smtp_server and custom_smtp_port:
            # 使用自定义 SMTP 配置
            smtp_server = custom_smtp_server
            smtp_port = int(custom_smtp_port)
            # 根据端口判断加密方式：465=SSL, 587=TLS
            if smtp_port == 465:
                use_tls = False  # SSL 模式（SMTP_SSL）
            elif smtp_port == 587:
                use_tls = True  # TLS 模式（STARTTLS）
            else:
                # 其他端口优先尝试 TLS（更安全，更广泛支持）
                use_tls = True
        elif domain in SMTP_CONFIGS:
            # 使用预设配置
            config = SMTP_CONFIGS[domain]
            smtp_server = config["server"]
            smtp_port = config["port"]
            use_tls = config["encryption"] == "TLS"
        else:
            log.warning("未识别的邮箱服务商，使用通用 SMTP 配置", domain=domain)
            smtp_server = f"smtp.{domain}"
            smtp_port = 587
            use_tls = True

        msg = MIMEMultipart("alternative")

        # 严格按照 RFC 标准设置 From header
        sender_name = "TrendRadar"
        msg["From"] = formataddr((sender_name, from_email))

        # 设置收件人
        recipients = [addr.strip() for addr in to_email.split(",")]
        if len(recipients) == 1:
            msg["To"] = recipients[0]
        else:
            msg["To"] = ", ".join(recipients)

        # 设置邮件主题
        now = get_time_func() if get_time_func else datetime.now()
        subject = f"TrendRadar 热点分析报告 - {report_type} - {now.strftime('%m月%d日 %H:%M')}"
        msg["Subject"] = Header(subject, "utf-8")

        # 设置其他标准 header
        msg["MIME-Version"] = "1.0"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()

        # 添加纯文本部分（作为备选）
        text_content = f"""
TrendRadar 热点分析报告
========================
报告类型：{report_type}
生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}

请使用支持HTML的邮件客户端查看完整报告内容。
        """
        text_part = MIMEText(text_content, "plain", "utf-8")
        msg.attach(text_part)

        html_part = MIMEText(html_content, "html", "utf-8")
        msg.attach(html_part)

        log.info("正在发送邮件", smtp_server=smtp_server, smtp_port=smtp_port, from_email=from_email, to_email=to_email)

        try:
            if use_tls:
                # TLS 模式
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                server.set_debuglevel(0)  # 设为1可以查看详细调试信息
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                # SSL 模式
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
                server.set_debuglevel(0)
                server.ehlo()

            # 登录
            server.login(from_email, password)

            # 发送邮件
            server.send_message(msg)
            server.quit()

            log.success("邮件发送成功", report_type=report_type, to_email=to_email)
            return True

        except smtplib.SMTPServerDisconnected:
            log.error("邮件发送失败：服务器意外断开连接，请检查网络或稍后重试")
            return False

    except smtplib.SMTPAuthenticationError as e:
        log.error("邮件发送失败：认证错误，请检查邮箱和密码/授权码", error=str(e))
        return False
    except smtplib.SMTPRecipientsRefused as e:
        log.error("邮件发送失败：收件人地址被拒绝", error=str(e))
        return False
    except smtplib.SMTPSenderRefused as e:
        log.error("邮件发送失败：发件人地址被拒绝", error=str(e))
        return False
    except smtplib.SMTPDataError as e:
        log.error("邮件发送失败：邮件数据错误", error=str(e))
        return False
    except smtplib.SMTPConnectError as e:
        log.error("邮件发送失败：无法连接到 SMTP 服务器", smtp_server=smtp_server, smtp_port=smtp_port, error=str(e))
        return False
    except Exception as e:
        log.error("邮件发送失败", report_type=report_type, error=str(e))
        import traceback
        traceback.print_exc()
        return False


def send_to_ntfy(
    server_url: str,
    topic: str,
    token: str | None,
    report_data: dict,
    report_type: str,
    update_info: dict | None = None,
    proxy_url: str | None = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 3800,
    split_content_func: Callable = None,
    rss_items: list | None = None,
    rss_new_items: list | None = None,
) -> bool:
    """
    发送到 ntfy（支持分批发送，严格遵守4KB限制，支持热榜+RSS合并）

    Args:
        server_url: ntfy 服务器 URL
        topic: ntfy 主题
        token: ntfy 访问令牌（可选）
        report_data: 报告数据
        report_type: 报告类型
        update_info: 更新信息（可选）
        proxy_url: 代理 URL（可选）
        mode: 报告模式 (daily/current)
        account_label: 账号标签（多账号时显示）
        batch_size: 批次大小（字节）
        split_content_func: 内容分批函数
        rss_items: RSS 统计条目列表（可选，用于合并推送）
        rss_new_items: RSS 新增条目列表（可选，用于新增区块）

    Returns:
        bool: 发送是否成功
    """
    # 日志前缀
    log_prefix = f"ntfy{account_label}" if account_label else "ntfy"

    # 避免 HTTP header 编码问题
    report_type_en_map = {
        "当日汇总": "Daily Summary",
        "当前榜单汇总": "Current Ranking",
        "增量更新": "Incremental Update",
        "实时增量": "Realtime Incremental",
        "实时当前榜单": "Realtime Current Ranking",
    }
    report_type_en = report_type_en_map.get(report_type, "News Report")

    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Markdown": "yes",
        "Title": report_type_en,
        "Priority": "default",
        "Tags": "news",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    # 构建完整URL，确保格式正确
    base_url = server_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"
    url = f"{base_url}/{topic}"

    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    # 获取分批内容，预留批次头部空间
    header_reserve = get_max_batch_header_size("ntfy")
    batches = split_content_func(
        report_data, "ntfy", update_info, max_bytes=batch_size - header_reserve, mode=mode,
        rss_items=rss_items,
        rss_new_items=rss_new_items,
    )

    # 统一添加批次头部（已预留空间，不会超限）
    batches = add_batch_headers(batches, "ntfy", batch_size)

    total_batches = len(batches)
    log.info(f"{log_prefix}消息分为 {total_batches} 批次发送", channel=log_prefix, report_type=report_type, batch_count=total_batches)

    # 反转批次顺序，使得在ntfy客户端显示时顺序正确
    # ntfy显示最新消息在上面，所以我们从最后一批开始推送
    reversed_batches = list(reversed(batches))

    log.debug(f"{log_prefix}将按反向顺序推送，确保客户端显示顺序正确", channel=log_prefix, batch_count=total_batches)

    # 逐批发送（反向顺序）
    success_count = 0
    for idx, batch_content in enumerate(reversed_batches, 1):
        # 计算正确的批次编号（用户视角的编号）
        actual_batch_num = total_batches - idx + 1

        content_size = len(batch_content.encode("utf-8"))
        log.info(f"发送{log_prefix}第 {actual_batch_num}/{total_batches} 批次", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, push_order=idx, size_bytes=content_size, report_type=report_type)

        # 检查消息大小，确保不超过4KB
        if content_size > 4096:
            log.warning(f"{log_prefix}第 {actual_batch_num} 批次消息过大，可能被拒绝", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, size_bytes=content_size)

        # 更新 headers 的批次标识
        current_headers = headers.copy()
        if total_batches > 1:
            current_headers["Title"] = f"{report_type_en} ({actual_batch_num}/{total_batches})"

        try:
            response = requests.post(
                url,
                headers=current_headers,
                data=batch_content.encode("utf-8"),
                proxies=proxies,
                timeout=30,
            )

            if response.status_code == 200:
                log.success(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次发送成功", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type)
                success_count += 1
                if idx < total_batches:
                    # 公共服务器建议 2-3 秒，自托管可以更短
                    interval = 2 if "ntfy.sh" in server_url else 1
                    time.sleep(interval)
            elif response.status_code == 429:
                log.warning(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次速率限制，等待后重试", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type)
                time.sleep(10)  # 等待10秒后重试
                # 重试一次
                retry_response = requests.post(
                    url,
                    headers=current_headers,
                    data=batch_content.encode("utf-8"),
                    proxies=proxies,
                    timeout=30,
                )
                if retry_response.status_code == 200:
                    log.success(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次重试成功", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type)
                    success_count += 1
                else:
                    log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次重试失败", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, status_code=retry_response.status_code)
            elif response.status_code == 413:
                log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次消息过大被拒绝", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type, size_bytes=content_size)
            else:
                log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次发送失败", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type, status_code=response.status_code)
                log.debug("ntfy错误详情", response_text=response.text)

        except requests.exceptions.ConnectTimeout:
            log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次连接超时", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type)
        except requests.exceptions.ReadTimeout:
            log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次读取超时", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type)
        except requests.exceptions.ConnectionError as e:
            log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次连接错误", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type, error=str(e))
        except Exception as e:
            log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次发送异常", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type, error=str(e))

    # 判断整体发送是否成功
    if success_count == total_batches:
        log.success(f"{log_prefix}所有 {total_batches} 批次发送完成", channel=log_prefix, report_type=report_type, batch_count=total_batches)
        return True
    elif success_count > 0:
        log.warning(f"{log_prefix}部分发送成功", channel=log_prefix, report_type=report_type, success_count=success_count, total_batches=total_batches)
        return True  # 部分成功也视为成功
    else:
        log.error(f"{log_prefix}发送完全失败", channel=log_prefix, report_type=report_type)
        return False


def send_to_bark(
    bark_url: str,
    report_data: dict,
    report_type: str,
    update_info: dict | None = None,
    proxy_url: str | None = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 3600,
    batch_interval: float = 1.0,
    split_content_func: Callable = None,
    rss_items: list | None = None,
    rss_new_items: list | None = None,
) -> bool:
    """
    发送到 Bark（支持分批发送，使用 markdown 格式，支持热榜+RSS合并）

    Args:
        bark_url: Bark URL（包含 device_key）
        report_data: 报告数据
        report_type: 报告类型
        update_info: 更新信息（可选）
        proxy_url: 代理 URL（可选）
        mode: 报告模式 (daily/current)
        account_label: 账号标签（多账号时显示）
        batch_size: 批次大小（字节）
        batch_interval: 批次发送间隔（秒）
        split_content_func: 内容分批函数
        rss_items: RSS 统计条目列表（可选，用于合并推送）
        rss_new_items: RSS 新增条目列表（可选，用于新增区块）

    Returns:
        bool: 发送是否成功
    """
    # 日志前缀
    log_prefix = f"Bark{account_label}" if account_label else "Bark"

    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    # 解析 Bark URL，提取 device_key 和 API 端点
    # Bark URL 格式: https://api.day.app/device_key 或 https://bark.day.app/device_key
    parsed_url = urlparse(bark_url)
    device_key = parsed_url.path.strip('/').split('/')[0] if parsed_url.path else None

    if not device_key:
        log.error(f"{log_prefix} URL 格式错误，无法提取 device_key", channel=log_prefix, bark_url=bark_url)
        return False

    # 构建正确的 API 端点
    api_endpoint = f"{parsed_url.scheme}://{parsed_url.netloc}/push"

    # 获取分批内容，预留批次头部空间
    header_reserve = get_max_batch_header_size("bark")
    batches = split_content_func(
        report_data, "bark", update_info, max_bytes=batch_size - header_reserve, mode=mode,
        rss_items=rss_items,
        rss_new_items=rss_new_items,
    )

    # 统一添加批次头部（已预留空间，不会超限）
    batches = add_batch_headers(batches, "bark", batch_size)

    total_batches = len(batches)
    log.info(f"{log_prefix}消息分为 {total_batches} 批次发送", channel=log_prefix, report_type=report_type, batch_count=total_batches)

    # 反转批次顺序，使得在Bark客户端显示时顺序正确
    # Bark显示最新消息在上面，所以我们从最后一批开始推送
    reversed_batches = list(reversed(batches))

    log.debug(f"{log_prefix}将按反向顺序推送，确保客户端显示顺序正确", channel=log_prefix, batch_count=total_batches)

    # 逐批发送（反向顺序）
    success_count = 0
    for idx, batch_content in enumerate(reversed_batches, 1):
        # 计算正确的批次编号（用户视角的编号）
        actual_batch_num = total_batches - idx + 1

        content_size = len(batch_content.encode("utf-8"))
        log.info(f"发送{log_prefix}第 {actual_batch_num}/{total_batches} 批次", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, push_order=idx, size_bytes=content_size, report_type=report_type)

        # 检查消息大小（Bark使用APNs，限制4KB）
        if content_size > 4096:
            log.warning(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次消息过大，可能被拒绝", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, size_bytes=content_size)

        # 构建JSON payload
        payload = {
            "title": report_type,
            "markdown": batch_content,
            "device_key": device_key,
            "sound": "default",
            "group": "TrendRadar",
            "action": "none",  # 点击推送跳到 APP 不弹出弹框,方便阅读
        }

        try:
            response = requests.post(
                api_endpoint,
                json=payload,
                proxies=proxies,
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 200:
                    log.success(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次发送成功", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type)
                    success_count += 1
                    # 批次间间隔
                    if idx < total_batches:
                        time.sleep(batch_interval)
                else:
                    log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次发送失败", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type, error=result.get("message", "未知错误"))
            else:
                log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次发送失败", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type, status_code=response.status_code)
                log.debug("Bark错误详情", response_text=response.text)

        except requests.exceptions.ConnectTimeout:
            log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次连接超时", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type)
        except requests.exceptions.ReadTimeout:
            log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次读取超时", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type)
        except requests.exceptions.ConnectionError as e:
            log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次连接错误", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type, error=str(e))
        except Exception as e:
            log.error(f"{log_prefix}第 {actual_batch_num}/{total_batches} 批次发送异常", channel=log_prefix, batch=actual_batch_num, total_batches=total_batches, report_type=report_type, error=str(e))

    # 判断整体发送是否成功
    if success_count == total_batches:
        log.success(f"{log_prefix}所有 {total_batches} 批次发送完成", channel=log_prefix, report_type=report_type, batch_count=total_batches)
        return True
    elif success_count > 0:
        log.warning(f"{log_prefix}部分发送成功", channel=log_prefix, report_type=report_type, success_count=success_count, total_batches=total_batches)
        return True  # 部分成功也视为成功
    else:
        log.error(f"{log_prefix}发送完全失败", channel=log_prefix, report_type=report_type)
        return False


def send_to_slack(
    webhook_url: str,
    report_data: dict,
    report_type: str,
    update_info: dict | None = None,
    proxy_url: str | None = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 4000,
    batch_interval: float = 1.0,
    split_content_func: Callable = None,
    rss_items: list | None = None,
    rss_new_items: list | None = None,
) -> bool:
    """
    发送到 Slack（支持分批发送，使用 mrkdwn 格式，支持热榜+RSS合并）

    Args:
        webhook_url: Slack Webhook URL
        report_data: 报告数据
        report_type: 报告类型
        update_info: 更新信息（可选）
        proxy_url: 代理 URL（可选）
        mode: 报告模式 (daily/current)
        account_label: 账号标签（多账号时显示）
        batch_size: 批次大小（字节）
        batch_interval: 批次发送间隔（秒）
        split_content_func: 内容分批函数
        rss_items: RSS 统计条目列表（可选，用于合并推送）
        rss_new_items: RSS 新增条目列表（可选，用于新增区块）

    Returns:
        bool: 发送是否成功
    """
    headers = {"Content-Type": "application/json"}
    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    # 日志前缀
    log_prefix = f"Slack{account_label}" if account_label else "Slack"

    # 获取分批内容，预留批次头部空间
    header_reserve = get_max_batch_header_size("slack")
    batches = split_content_func(
        report_data, "slack", update_info, max_bytes=batch_size - header_reserve, mode=mode,
        rss_items=rss_items,
        rss_new_items=rss_new_items,
    )

    # 统一添加批次头部（已预留空间，不会超限）
    batches = add_batch_headers(batches, "slack", batch_size)

    log.info(f"{log_prefix}消息分为 {len(batches)} 批次发送", channel=log_prefix, report_type=report_type, batch_count=len(batches))

    # 逐批发送
    for i, batch_content in enumerate(batches, 1):
        # 转换 Markdown 到 mrkdwn 格式
        mrkdwn_content = convert_markdown_to_mrkdwn(batch_content)

        content_size = len(mrkdwn_content.encode("utf-8"))
        log.info(f"发送{log_prefix}第 {i}/{len(batches)} 批次", channel=log_prefix, batch=i, total_batches=len(batches), size_bytes=content_size, report_type=report_type)

        # 构建 Slack payload（使用简单的 text 字段，支持 mrkdwn）
        payload = {"text": mrkdwn_content}

        try:
            response = requests.post(
                webhook_url, headers=headers, json=payload, proxies=proxies, timeout=30
            )

            # Slack Incoming Webhooks 成功时返回 "ok" 文本
            if response.status_code == 200 and response.text == "ok":
                log.success(f"{log_prefix}第 {i}/{len(batches)} 批次发送成功", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type)
                # 批次间间隔
                if i < len(batches):
                    time.sleep(batch_interval)
            else:
                error_msg = response.text if response.text else f"状态码：{response.status_code}"
                log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送失败", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=error_msg)
                return False
        except requests.exceptions.RequestException as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))
            return False
        except Exception as e:
            log.error(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错", channel=log_prefix, batch=i, total_batches=len(batches), report_type=report_type, error=str(e))
            return False

    log.success(f"{log_prefix}所有 {len(batches)} 批次发送完成", channel=log_prefix, report_type=report_type, batch_count=len(batches))
    return True
