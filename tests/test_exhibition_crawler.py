import unittest

from crawlers.exhibition_crawler import ExhibitionCrawler, SearchResult


AI_HAKURANKAI_HTML = """
<html><head><title>AI博覧会 Spring 2027</title>
<meta name="description" content="最新のAI技術とサービスが集結するAI博覧会です。"></head>
<body><main>
<h1>AI博覧会 Spring 2027</h1>
<p>会期：2027年3月4日 - 6日</p>
<p>会場：東京国際フォーラム</p>
<p>主催：AIポータルメディア AIsmiley</p>
</main></body></html>
"""

AI_HAKURANKAI_HUB_HTML = """
<html><body>
<a href="/ai_hakurankai/summer-2026/">AI博覧会 Summer 2026</a>
<a href="/ai_hakurankai/fukuoka-2026/">AI博覧会 Fukuoka 2026</a>
<a href="/ai_hakurankai/news/">お知らせ</a>
<a href="https://example.com/ai_hakurankai/spring-2027/">外部サイト</a>
</body></html>
"""


class ExhibitionCrawlerTests(unittest.TestCase):
    def test_ai_hakurankai_is_recognized_as_explicit_event(self):
        crawler = ExhibitionCrawler(delay=0)
        self.assertTrue(crawler.is_ai_hakurankai_event(
            "https://aismiley.co.jp/ai_hakurankai/spring-2027/",
            "AI博覧会 Spring 2027",
        ))

    def test_ai_hakurankai_is_saved_even_without_robotics_keywords(self):
        crawler = ExhibitionCrawler(delay=0)
        crawler.fetch_html = lambda _url: AI_HAKURANKAI_HTML
        result = SearchResult(
            query='site:aismiley.co.jp/ai_hakurankai "AI博覧会"',
            title="AI博覧会 Spring 2027",
            url="https://aismiley.co.jp/ai_hakurankai/spring-2027/",
            snippet="AIの専門展示会",
        )

        item = crawler.build_item(result)

        self.assertIsNotNone(item)
        self.assertEqual(item["source_type"], "event")
        self.assertEqual(item["published_at"], "2027-03-04")

    def test_other_ai_event_still_requires_robotics_context(self):
        crawler = ExhibitionCrawler(delay=0)
        self.assertFalse(crawler.is_ai_hakurankai_event(
            "https://example.com/ai_hakurankai/",
            "AI博覧会 Spring 2027",
        ))

    def test_official_hub_discovers_only_event_detail_pages(self):
        crawler = ExhibitionCrawler(delay=0)
        crawler.fetch_html = lambda _url: AI_HAKURANKAI_HUB_HTML

        urls = crawler.discover_ai_hakurankai_event_urls("https://aismiley.co.jp/ai_hakurankai/")

        self.assertEqual(urls, [
            "https://aismiley.co.jp/ai_hakurankai/summer-2026/",
            "https://aismiley.co.jp/ai_hakurankai/fukuoka-2026/",
        ])

    def test_ai_hakurankai_compact_dot_dates_are_parsed(self):
        crawler = ExhibitionCrawler(delay=0)

        self.assertEqual(
            crawler.extract_date_range("AI博覧会 Fukuoka 2026 | 2026.9.30-10.1"),
            ("2026-09-30", "2026-10-01"),
        )

    def test_ai_hakurankai_pipe_slash_dates_are_parsed_as_cross_month_range(self):
        crawler = ExhibitionCrawler(delay=0)

        self.assertEqual(
            crawler.extract_date_range("AI博覧会 Fukuoka 2026|9/30-10/1"),
            ("2026-09-30", "2026-10-01"),
        )


if __name__ == "__main__":
    unittest.main()
