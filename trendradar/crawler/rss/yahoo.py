"""Read Yahoo Finance's public news listing into the legacy feed contract."""

from __future__ import annotations

import json
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .parser import ParsedRSSItem, RSSParser


class YahooFinanceParser(RSSParser):
    def parse(self, content: str, feed_url: str = "") -> list[ParsedRSSItem]:
        soup = BeautifulSoup(content, "html.parser")
        items: list[ParsedRSSItem] = []
        seen: set[str] = set()
        for card in soup.select('[data-testid="storyitem"]'):
            heading = card.find(["h2", "h3"])
            anchor = heading.find_parent("a", href=True) if heading else None
            if anchor is None or anchor not in card.descendants:
                continue
            url = urlsplit(urljoin(feed_url, anchor["href"]))
            if (
                url.scheme != "https" or url.netloc != "finance.yahoo.com"
                or not url.path.endswith(".html")
            ):
                continue
            canonical = urlunsplit((url.scheme, url.netloc, url.path, "", ""))
            title = heading.get_text(" ", strip=True)
            if not title or canonical in seen:
                continue
            seen.add(canonical)
            try:
                attributes = json.loads(anchor.get("data-yga", "{}"))
            except (ValueError, TypeError):
                attributes = {}
            if not isinstance(attributes, dict):
                attributes = {}
            timestamp = card.find("time", datetime=True)
            summary = card.find("p")
            author = attributes.get("yContentPartner")
            identifier = attributes.get("yDestinationContentUUID")
            items.append(ParsedRSSItem(
                title=title,
                url=canonical,
                # Relative labels are not stable publication timestamps.
                published_at=self._parse_iso_date(timestamp["datetime"]) if timestamp else None,
                summary=summary.get_text(" ", strip=True)[:self.max_summary_length]
                if summary else None,
                author=author if isinstance(author, str) else None,
                guid=identifier if isinstance(identifier, str) and identifier else canonical,
            ))
        if not items:
            raise ValueError("Yahoo Finance listing contains no recognized news articles")
        return items
