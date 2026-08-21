import unittest
import re

from app import app, build_latest_default_trend_items, build_pdf_category_groups


class DailyTrendPdfTests(unittest.TestCase):
    def test_daily_pdf_trend_snapshot_always_has_sixteen_pairs(self):
        with app.app_context():
            items = build_latest_default_trend_items()

        self.assertEqual(len(items), 16)
        self.assertEqual(len({item.title for item in items}), 16)

    def test_trend_pdf_items_include_last_updated_timestamp(self):
        with app.app_context():
            trend_items = build_latest_default_trend_items()
            groups = build_pdf_category_groups(trend_items)

        trend_group = next(group for group in groups if group["category"] == "Google Trends")
        self.assertEqual(trend_group["count"], 16)
        self.assertTrue(all("last_updated_at" in item["trend"] for item in trend_group["items"]))

    def test_browser_trend_views_always_render_sixteen_panels(self):
        client = app.test_client()

        for path in ("/trends", "/?source_type=trend&crawl_date=2026-08-01"):
            response = client.get(path)
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(body.count("最終更新:"), 16)

    def test_daily_news_trend_tile_shows_sixteen_items_after_partial_collection(self):
        response = app.test_client().get("/?crawl_date=2026-08-15")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        tile = re.search(r'<a class="summary-card[^>]+aria-label="trendを表示".*?</a>', body, re.DOTALL)
        self.assertIsNotNone(tile)
        self.assertIn("16件", tile.group(0))


if __name__ == "__main__":
    unittest.main()
