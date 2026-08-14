"""Precision filters for Google News RSS candidate results.

Google News search syntax is useful for finding candidates, but its RSS results
can contain fuzzy matches.  In particular, a ``site:`` clause is not a
guarantee that the result is from that site.  Filters in this module therefore
validate the publisher and the visible article context before persistence.
"""

from __future__ import annotations

import unicodedata


PRTIMES_QUERY_PREFIX = "site:prtimes.jp"
AU_WEB_PORTAL_QUERY_PREFIX = "site:article.auone.jp"

ROBOTICS_TOPIC_KEYWORDS = (
    "physical ai",
    "フィジカルai",
    "ロボット",
    "ロボティクス",
    "robotics",
    "robot",
    "humanoid",
    "ヒューマノイド",
)


def _normalized(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold()


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def is_expected_site_publisher(*, query: str, publisher: str) -> bool:
    """Return whether an RSS publisher matches a strict site-limited query."""
    normalized_query = _normalized(query)
    normalized_publisher = _normalized(publisher)

    if normalized_query.startswith(PRTIMES_QUERY_PREFIX):
        return "pr times" in normalized_publisher or "prtimes" in normalized_publisher
    if normalized_query.startswith(AU_WEB_PORTAL_QUERY_PREFIX):
        return any(name in normalized_publisher for name in ("au web", "auone", "au one"))
    return True


def should_keep_japanese_robotics_media_item(*, query: str, publisher: str, title: str, summary: str) -> bool:
    """Fail closed for PR TIMES and au Web portal candidate feeds.

    Both a publisher match and a Physical AI / robotics term in the RSS-visible
    title or summary are required.  This deliberately avoids trusting only the
    Google News query, which may use fuzzy matching.
    """
    normalized_query = _normalized(query)
    is_strict_site_query = normalized_query.startswith((PRTIMES_QUERY_PREFIX, AU_WEB_PORTAL_QUERY_PREFIX))
    if not is_strict_site_query:
        return True

    if not is_expected_site_publisher(query=query, publisher=publisher):
        return False

    article_context = _normalized(f"{title} {summary}")
    if normalized_query.startswith(AU_WEB_PORTAL_QUERY_PREFIX):
        # The au query is intentionally narrower than the PR TIMES queries.
        return _has_any(article_context, ("physical ai", "フィジカルai"))
    return _has_any(article_context, ROBOTICS_TOPIC_KEYWORDS)
