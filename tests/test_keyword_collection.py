import unittest
from unittest.mock import Mock

from keyword_collection import KeywordCollector, matches_requested_keyword


RSS = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<rss version=\"2.0\"><channel><item>
  <title>Example Robotics launches a warehouse robot</title>
  <link>https://example.com/robot</link>
  <description>Example Robotics announced an autonomous robot.</description>
  <pubDate>Mon, 10 Aug 2026 12:00:00 GMT</pubDate>
  <source url=\"https://example.com\">Example News</source>
</item><item>
  <title>Unrelated market update</title>
  <link>https://example.com/market</link>
  <description>Markets were broadly higher in morning trading.</description>
</item></channel></rss>"""


class KeywordCollectionTests(unittest.TestCase):
    def test_keyword_matching_requires_phrase_or_all_space_separated_terms(self):
        self.assertTrue(matches_requested_keyword("Physical AI", "Physical AI robot", ""))
        self.assertTrue(matches_requested_keyword("AI robot", "New robot with AI", ""))
        self.assertFalse(matches_requested_keyword("Physical AI", "Physical robot", "AI software"))

    def test_google_news_fetches_new_matching_candidates(self):
        collector = KeywordCollector()
        response = Mock(content=RSS)
        response.raise_for_status.return_value = None
        collector.session.get = Mock(return_value=response)

        items = collector.fetch_google_news_items("Example Robotics")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Example Robotics launches a warehouse robot")
        self.assertIn("Keyword collector source: Google News RSS", items[0]["raw_text"])
        self.assertIn("Google News query: Example Robotics", items[0]["raw_text"])
        self.assertEqual(collector.session.get.call_count, 2)

    def test_google_news_failure_returns_no_candidates(self):
        collector = KeywordCollector()
        collector.session.get = Mock(side_effect=Exception("network unavailable"))

        # Requests exceptions are handled by the collector; use a real
        # requests exception so that unexpected programming errors still fail.
        import requests
        collector.session.get.side_effect = requests.RequestException("network unavailable")
        self.assertEqual(collector.fetch_google_news_items("Physical AI"), [])


if __name__ == "__main__":
    unittest.main()
