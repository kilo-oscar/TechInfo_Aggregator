import unittest

from app import app


class PdfRouteTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_daily_pdf_opens_when_the_day_contains_event_items(self):
        response = self.client.get("/today-news.pdf?date=2026-08-14&disposition=inline")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_event_filtered_pdf_opens(self):
        response = self.client.get("/filtered-results.pdf?source_type=event&disposition=inline")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_news_export_requires_a_month_and_builds_month_scoped_pdf_urls(self):
        response = self.client.get("/?source_type=news")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('id="news-export-month"', page)
        self.assertIn("年月を選択してください", page)
        self.assertIn('id="news-export-open"', page)
        self.assertIn('aria-disabled="true"', page)
        self.assertIn("archive_month=", page)


if __name__ == "__main__":
    unittest.main()
