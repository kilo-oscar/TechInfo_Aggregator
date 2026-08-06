from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from urllib.parse import urlencode

import requests

from app import app
from crawler_utils import save_raw_item


EXPLORE_API_URL = "https://trends.google.com/trends/api/explore"
TIMESERIES_API_URL = "https://trends.google.com/trends/api/widgetdata/multiline"
DEFAULT_KEYWORDS = [
    "Physical AI",
    "フィジカルAI",
    "Embodied AI",
    "Humanoid Robot",
    "Vision Language Action",
    "Robot Learning",
    "Sim-to-Real",
    "Robotics Foundation Model",
]
REGIONS = [
    ("JP", "日本"),
    ("", "世界"),
]
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/124.0.0.0 Safari/537.36"
)


def strip_google_prefix(text: str) -> str:
    marker = text.find("{")
    if marker < 0:
        raise ValueError("Google Trends response did not contain JSON")
    return text[marker:]


def build_explore_url(keyword: str, geo: str) -> str:
    params = {"q": keyword, "date": "today 12-m"}
    if geo:
        params["geo"] = geo
    return "https://trends.google.com/trends/explore?" + urlencode(params)


class GoogleTrendsCrawler:
    def __init__(self, timeout: int = 20, delay: float = 1.5) -> None:
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"})

    def fetch_interest(self, keyword: str, geo: str) -> list[dict]:
        request_payload = {
            "comparisonItem": [{"keyword": keyword, "geo": geo, "time": "today 12-m"}],
            "category": 0,
            "property": "",
        }
        response = self.session.get(
            EXPLORE_API_URL,
            params={"hl": "ja", "tz": "-540", "req": json.dumps(request_payload, ensure_ascii=False)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = json.loads(strip_google_prefix(response.text))
        widget = next((item for item in payload.get("widgets", []) if item.get("id") == "TIMESERIES"), None)
        if not widget:
            raise ValueError("Google Trends TIMESERIES widget was not returned")

        response = self.session.get(
            TIMESERIES_API_URL,
            params={
                "hl": "ja",
                "tz": "-540",
                "req": json.dumps(widget["request"], ensure_ascii=False),
                "token": widget["token"],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        timeline = json.loads(strip_google_prefix(response.text)).get("default", {}).get("timelineData", [])
        points = []
        for point in timeline:
            values = point.get("value") or []
            if not values:
                continue
            timestamp = datetime.fromtimestamp(int(point["time"]))
            points.append({
                "date": timestamp.strftime("%Y-%m-%d"),
                "label": point.get("formattedTime", ""),
                "value": int(values[0]),
                "partial": bool(point.get("isPartial")),
            })
        return points

    def crawl(self, keywords: list[str]) -> list[dict]:
        results = []
        for keyword in keywords:
            for geo, region_label in REGIONS:
                explore_url = build_explore_url(keyword, geo)
                error = ""
                points = []
                try:
                    points = self.fetch_interest(keyword, geo)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 429:
                        error = "Google Trendsのレート制限 (HTTP 429)。時間を空けて再実行してください。"

                values = [point["value"] for point in points]
                latest_value = values[-1] if values else None
                average_value = round(sum(values) / len(values), 1) if values else None
                peak_value = max(values) if values else None
                snapshot_date = date.today().isoformat()
                stored_url = explore_url + "&" + urlencode({"snapshot": snapshot_date})
                results.append({
                    "source_name": f"Google Trends / {region_label}",
                    "source_type": "trend",
                    "title": f"Google Trends: {keyword} / {region_label}",
                    "url": stored_url,
                    "published_at": snapshot_date,
                    "raw_summary": (
                        f"過去12か月の検索関心度: 最新={latest_value}, 平均={average_value}, 最高={peak_value}"
                        if points else f"Google Trends取得失敗: {error}"
                    ),
                    "raw_text": json.dumps({
                        "provider": "Google Trends",
                        "keyword": keyword,
                        "geo": geo,
                        "region_label": region_label,
                        "time_range": "today 12-m",
                        "explore_url": explore_url,
                        "fetched_on": snapshot_date,
                        "latest_value": latest_value,
                        "average_value": average_value,
                        "peak_value": peak_value,
                        "points": points,
                        "error": error,
                    }, ensure_ascii=False),
                })
                time.sleep(self.delay)
        return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Physical AI関連語のGoogle Trendsを収集する")
    parser.add_argument("--keywords", nargs="+", default=DEFAULT_KEYWORDS)
    parser.add_argument("--delay", type=float, default=1.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawler = GoogleTrendsCrawler(delay=max(args.delay, 0))
    results = crawler.crawl(args.keywords)
    inserted = 0
    with app.app_context():
        for item in results:
            inserted += int(save_raw_item(item))
    successes = sum(1 for item in results if '"points": []' not in item["raw_text"])
    print(f"google trends: collected={len(results)}, successful={successes}, inserted={inserted}")


if __name__ == "__main__":
    main()
