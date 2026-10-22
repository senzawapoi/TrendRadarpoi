from datetime import datetime, timedelta, timezone

from trendradar.core.models import (
    canonicalize_url,
    normalize_datetime,
    normalize_tags,
    normalize_text,
)


def test_canonicalize_url_normalizes_host_scheme_query_and_tracking():
    url = "EXAMPLE.com:443/path?z=2&utm_campaign=x&a=3&a=1&fbclid=y#fragment"
    assert canonicalize_url(url) == "https://example.com/path?a=1&a=3&z=2"


def test_canonicalize_url_rejects_invalid_or_unsupported_values():
    assert canonicalize_url("not a url") == ""
    assert canonicalize_url("ftp://example.com/file") == ""
    assert canonicalize_url("") == ""


def test_normalize_text_and_tags():
    assert normalize_text(" Ａ\n\t B  ") == "A B"
    assert normalize_tags([" AI ", "ai", "Ｎｅｗｓ", ""]) == ["AI", "News"]


def test_normalize_datetime_converts_to_utc_and_rejects_invalid():
    value = normalize_datetime("2026-08-21T20:00:00+08:00")
    assert value == datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
    assert normalize_datetime(datetime(2026, 8, 21, 12)) == datetime(
        2026, 8, 21, 12, tzinfo=timezone.utc
    )
    assert normalize_datetime(datetime(2026, 8, 21, tzinfo=timezone(timedelta(hours=8)))) == (
        datetime(2026, 8, 20, 16, tzinfo=timezone.utc)
    )
    assert normalize_datetime("bad") is None
