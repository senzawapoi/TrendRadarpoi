from trendradar.intelligence.translation import translate_news_items_canonically
from trendradar.storage.base import NewsItem


def _item(title: str, canonical_id: str) -> NewsItem:
    item = NewsItem(title=title, source_id="source")
    item._canonical_content_id = canonical_id
    return item


def test_translation_runs_once_per_canonical_and_propagates():
    first = _item("Same", "canonical")
    duplicate = _item("Same duplicate", "canonical")
    other = _item("Other", "other")
    calls = []

    def translate(items):
        calls.append([item.title for item in items])
        for item in items:
            item.title_translated = f"translated:{item.title}"
            item.is_english = True
        return len(items)

    count = translate_news_items_canonically([first, duplicate, other], translate)
    assert count == 2
    assert calls == [["Same", "Other"]]
    assert first.title_translated == duplicate.title_translated == "translated:Same"
    assert other.title_translated == "translated:Other"


def test_translation_cache_prevents_cross_batch_calls():
    cache = {}
    first = _item("First", "canonical")
    second = _item("Second", "canonical")

    def translate(items):
        items[0].title_translated = "cached"
        return 1

    assert translate_news_items_canonically([first], translate, cache=cache) == 1
    assert translate_news_items_canonically(
        [second],
        lambda _items: (_ for _ in ()).throw(AssertionError("must not translate")),
        cache=cache,
    ) == 0
    assert second.title_translated == "cached"
