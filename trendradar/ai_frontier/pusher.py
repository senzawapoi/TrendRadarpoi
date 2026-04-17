"""AI 前沿 Bark 推送

轻量级 Bark 推送器，直接 POST JSON 到 `https://api.day.app/{device_key}/push`。
不走主 notification 管道（已解耦的独立推送链路）。
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import requests

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.utils.logging import log

# Bark 单条消息体最大约 4KB，保守分批
BARK_MAX_BODY_BYTES = 3600


def extract_bark_endpoint(bark_url: str) -> tuple[str, str] | None:
    """从 https://api.day.app/xxxxx/ 解析出 (api_endpoint, device_key)"""
    if not bark_url or not bark_url.strip():
        return None
    parsed = urlparse(bark_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        return None
    device_key = parts[0]
    api_endpoint = f"{parsed.scheme}://{parsed.netloc}/push"
    return api_endpoint, device_key


def split_body(body: str, max_bytes: int = BARK_MAX_BODY_BYTES) -> list[str]:
    """按字节数将 body 拆成多批，避免超过 Bark 单条上限"""
    if not body:
        return []
    encoded = body.encode("utf-8")
    if len(encoded) <= max_bytes:
        return [body]

    # 按行切分尽量保持完整
    lines = body.split("\n")
    batches: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for line in lines:
        line_bytes = len((line + "\n").encode("utf-8"))
        if current and current_bytes + line_bytes > max_bytes:
            batches.append("\n".join(current))
            current = [line]
            current_bytes = line_bytes
        else:
            current.append(line)
            current_bytes += line_bytes
    if current:
        batches.append("\n".join(current))
    return batches


def _bark_post(
    api_endpoint: str,
    device_key: str,
    title: str,
    body: str,
    timeout: int = 15,
) -> bool:
    payload = {
        "title": title,
        "body": body,
        "device_key": device_key,
        "group": "AI-Frontier",
        "level": "active",  # 默认推送
    }
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(
            api_endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code != 200:
            log.warning(
                "Bark 返回状态非 200",
                status=resp.status_code,
                text=(resp.text or "")[:200],
            )
            return False
        try:
            data = resp.json()
            code = data.get("code")
            if code != 200:
                log.warning("Bark 响应 code 非 200", code=code, message=data.get("message"))
                return False
        except ValueError:
            # 非 JSON 响应，当作失败
            return False
        return True
    except Exception as e:
        log.warning("Bark 请求异常", error=str(e))
        return False


def push_to_bark(
    bark_url: str,
    title: str,
    body: str,
    *,
    batch_interval: float = 1.5,
    max_bytes: int = BARK_MAX_BODY_BYTES,
) -> bool:
    """推送一条（或多批）消息到 Bark。

    Args:
        bark_url: https://api.day.app/{device_key}
        title: 推送标题
        body: 推送正文（markdown）
        batch_interval: 批次发送间隔（秒）
        max_bytes: 单批最大字节数

    Returns:
        是否所有批次都成功
    """
    import time

    endpoint_info = extract_bark_endpoint(bark_url)
    if endpoint_info is None:
        log.warning("Bark URL 无效，跳过推送", bark_url=bark_url)
        return False

    api_endpoint, device_key = endpoint_info
    batches = split_body(body, max_bytes=max_bytes)
    if not batches:
        log.info("推送正文为空，跳过")
        return False

    total = len(batches)
    log.info(f"Bark 推送：{total} 批")

    success = 0
    # 反序发送：确保 Bark 列表里最新在顶
    for idx, batch in enumerate(reversed(batches), 1):
        sub_title = title if total == 1 else f"{title} ({total - idx + 1}/{total})"
        ok = _bark_post(api_endpoint, device_key, sub_title, batch)
        if ok:
            success += 1
        if idx < total:
            time.sleep(batch_interval)

    log.info(f"Bark 推送完成：{success}/{total}")
    return success == total


def push_items_to_bark(
    bark_url: str,
    items: list[AIItem],
    title: str = "🤖 AI 前沿",
) -> bool:
    """渲染 items 为 markdown 后推送到 Bark"""
    from trendradar.ai_frontier.renderer import render_markdown

    if not items:
        log.info("AI 前沿无新增，跳过 Bark 推送")
        return True

    body = render_markdown(items)
    push_title = f"{title} · 新增 {len(items)} 条"
    return push_to_bark(bark_url, push_title, body)
