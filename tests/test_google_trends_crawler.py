import json
import unittest
from unittest.mock import Mock, patch

import requests

from crawlers.google_trends_crawler import (
    GoogleTrendsCrawler,
    GoogleTrendsRateLimitExhausted,
)


def response(status_code: int, *, retry_after: str = "") -> requests.Response:
    value = requests.Response()
    value.status_code = status_code
    value.url = "https://trends.google.com/test"
    if retry_after:
        value.headers["Retry-After"] = retry_after
    return value


class GoogleTrendsCrawlerTests(unittest.TestCase):
    def test_fetch_interest_parses_seven_day_timeline_and_top_five_regions(self) -> None:
        crawler = GoogleTrendsCrawler(delay=0, max_retries=0)
        explore = Mock(text=")]}'\n" + json.dumps({"widgets": [
            {"id": "TIMESERIES", "request": {"time": "now 7-d"}, "token": "timeline-token"},
            {"id": "GEO_MAP", "request": {"resolution": "REGION"}, "token": "geo-token"},
        ]}))
        timeline = Mock(text=")]}'\n" + json.dumps({"default": {"timelineData": [
            {"time": "1786402800", "formattedTime": "Aug 11 at 12:00 AM", "value": [45]},
        ]}}))
        regions = Mock(text=")]}'\n" + json.dumps({"default": {"geoMapData": [
            {"geoName": f"Region {index}", "geoCode": f"R-{index}", "value": [value]}
            for index, value in enumerate([20, 90, 40, 100, 70, 60], start=1)
        ]}}))
        crawler._get = Mock(side_effect=[explore, timeline, regions])

        points, ranking = crawler.fetch_interest("Physical AI", "JP")

        self.assertEqual(points[0]["value"], 45)
        self.assertIn("datetime", points[0])
        self.assertEqual(len(ranking), 5)
        self.assertEqual([item["value"] for item in ranking], [100, 90, 70, 60, 40])

    @patch("crawlers.google_trends_crawler.random.uniform", return_value=10)
    @patch("crawlers.google_trends_crawler.time.sleep")
    @patch("crawlers.google_trends_crawler.time.monotonic", side_effect=[100, 104, 110])
    def test_every_http_request_is_paced(self, monotonic: Mock, sleep: Mock, uniform: Mock) -> None:
        crawler = GoogleTrendsCrawler(delay=10, max_retries=0)
        crawler.session.get = Mock(side_effect=[response(200), response(200)])

        crawler._get("https://trends.google.com/first", params={})
        crawler._get("https://trends.google.com/second", params={})

        sleep.assert_called_once_with(6)
        uniform.assert_called_once_with(8.0, 12.0)

    @patch("crawlers.google_trends_crawler.time.sleep")
    def test_429_retries_then_succeeds_and_honors_retry_after(self, sleep: Mock) -> None:
        crawler = GoogleTrendsCrawler(delay=0, max_retries=3, retry_base_delay=30)
        crawler.session.get = Mock(side_effect=[response(429, retry_after="7"), response(200)])

        result = crawler._get("https://trends.google.com/test", params={})

        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(7.0)
        self.assertEqual(crawler.session.get.call_count, 2)

    @patch("crawlers.google_trends_crawler.time.sleep")
    def test_429_exhaustion_uses_exponential_backoff(self, sleep: Mock) -> None:
        crawler = GoogleTrendsCrawler(delay=0, max_retries=3, retry_base_delay=30)
        crawler.session.get = Mock(side_effect=[response(429) for _ in range(4)])

        with self.assertRaises(GoogleTrendsRateLimitExhausted):
            crawler._get("https://trends.google.com/test", params={})

        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60, 120])

    def test_rate_limit_aborts_remaining_and_does_not_create_failure_rows(self) -> None:
        crawler = GoogleTrendsCrawler(delay=0, max_retries=0)
        successful_points = [{"date": "2026-08-01", "datetime": "2026-08-01 00:00", "label": "2026/08/01", "value": 42, "partial": False}]
        crawler.fetch_interest = Mock(side_effect=[(successful_points, []), GoogleTrendsRateLimitExhausted("HTTP 429")])

        results = crawler.crawl(["Physical AI", "Embodied AI"])

        self.assertEqual(len(results), 1)
        self.assertTrue(crawler.aborted_by_rate_limit)
        self.assertEqual(len(crawler.failures), 1)
        payload = json.loads(results[0]["raw_text"])
        self.assertEqual(payload["error"], "")
        self.assertTrue(payload["points"])

    def test_non_rate_limit_failure_continues_without_failure_row(self) -> None:
        crawler = GoogleTrendsCrawler(delay=0, max_retries=0)
        successful_points = [{"date": "2026-08-01", "datetime": "2026-08-01 00:00", "label": "2026/08/01", "value": 50, "partial": False}]
        crawler.fetch_interest = Mock(side_effect=[ValueError("bad response"), (successful_points, [])])

        results = crawler.crawl(["Physical AI"])

        self.assertEqual(len(results), 1)
        self.assertFalse(crawler.aborted_by_rate_limit)
        self.assertEqual(len(crawler.failures), 1)
        self.assertNotIn("取得失敗", results[0]["raw_summary"])

    @patch("crawlers.google_trends_crawler.time.sleep")
    def test_network_error_and_5xx_are_retried(self, sleep: Mock) -> None:
        crawler = GoogleTrendsCrawler(delay=0, max_retries=2, retry_base_delay=5)
        crawler.session.get = Mock(side_effect=[
            requests.ConnectionError("temporary"),
            response(503),
            response(200),
        ])

        result = crawler._get("https://trends.google.com/test", params={})

        self.assertEqual(result.status_code, 200)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10])

    def test_eight_keywords_and_two_regions_create_sixteen_successes(self) -> None:
        crawler = GoogleTrendsCrawler(delay=0, max_retries=0)
        points = [{"date": "2026-08-01", "datetime": "2026-08-01 00:00", "label": "2026/08/01", "value": 30, "partial": False}]
        crawler.fetch_interest = Mock(return_value=(points, [{"name": "Tokyo", "code": "JP-13", "value": 100}]))

        results = crawler.crawl([f"keyword-{index}" for index in range(8)])

        self.assertEqual(len(results), 16)
        self.assertEqual(crawler.failures, [])
        self.assertFalse(crawler.aborted_by_rate_limit)
        payload = json.loads(results[0]["raw_text"])
        self.assertEqual(payload["time_range"], "now 7-d")
        self.assertEqual(payload["regional_interest"][0]["name"], "Tokyo")


if __name__ == "__main__":
    unittest.main()
