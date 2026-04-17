"""pusher 测试（不发真实请求）"""

from __future__ import annotations

from trendradar.ai_frontier.pusher import (
    extract_bark_endpoint,
    push_items_to_bark,
    push_to_bark,
    split_body,
)


def test_extract_bark_endpoint_valid():
    out = extract_bark_endpoint("https://api.day.app/AOCxghz123/")
    assert out is not None
    api, key = out
    assert api == "https://api.day.app/push"
    assert key == "AOCxghz123"


def test_extract_bark_endpoint_invalid():
    assert extract_bark_endpoint("") is None
    assert extract_bark_endpoint("   ") is None
    assert extract_bark_endpoint("not-a-url") is None
    assert extract_bark_endpoint("https://api.day.app/") is None


def test_split_body_short_returns_single_batch():
    body = "hello"
    assert split_body(body, max_bytes=100) == ["hello"]


def test_split_body_long_splits_by_line():
    body = "\n".join([f"line-{i}" for i in range(100)])
    batches = split_body(body, max_bytes=100)
    assert len(batches) > 1
    # 每批字节数都 <= 阈值
    for b in batches:
        assert len(b.encode("utf-8")) <= 100


def test_split_body_empty():
    assert split_body("") == []


def test_push_to_bark_invalid_url_returns_false():
    assert push_to_bark("", "t", "b") is False
    assert push_to_bark("not-url", "t", "b") is False


def test_push_to_bark_success_with_mock(monkeypatch):
    posted = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {"code": 200, "message": "success"}

        @property
        def text(self):
            return '{"code":200}'

    def fake_post(url, data, headers, timeout):
        posted.append({"url": url, "data": data, "headers": headers})
        return FakeResp()

    monkeypatch.setattr("trendradar.ai_frontier.pusher.requests.post", fake_post)
    ok = push_to_bark("https://api.day.app/devkey/", "title", "body content")
    assert ok is True
    assert len(posted) == 1
    assert posted[0]["url"] == "https://api.day.app/push"


def test_push_to_bark_failed_status(monkeypatch):
    class FakeResp:
        status_code = 500
        text = "err"

        def json(self):
            return {}

    monkeypatch.setattr(
        "trendradar.ai_frontier.pusher.requests.post",
        lambda *a, **kw: FakeResp(),
    )
    ok = push_to_bark("https://api.day.app/k", "t", "b")
    assert ok is False


def test_push_items_to_bark_empty_returns_true():
    # 空列表视为成功（无需推送）
    assert push_items_to_bark("https://api.day.app/k", []) is True


def test_push_items_to_bark_renders_and_pushes(monkeypatch):
    from trendradar.ai_frontier.sources.base import AIItem

    captured = {}

    def fake_push(bark_url, title, body, **kwargs):
        captured["title"] = title
        captured["body"] = body
        return True

    monkeypatch.setattr("trendradar.ai_frontier.pusher.push_to_bark", fake_push)

    items = [AIItem(source="arxiv", source_name="x", title="T", url="https://u")]
    ok = push_items_to_bark("https://api.day.app/k", items)
    assert ok is True
    assert "新增 1 条" in captured["title"]
    assert "T" in captured["body"] or "新增" in captured["body"]
