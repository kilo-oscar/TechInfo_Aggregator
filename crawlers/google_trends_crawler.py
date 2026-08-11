from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import requests

from app import app
from crawler_utils import get_current_crawl_batch_id, save_raw_item
from models import RawItem, db
from trend_settings import DEFAULT_TREND_KEYWORDS, TREND_REGIONS


EXPLORE_API_URL = "https://trends.google.com/trends/api/explore"
TIMESERIES_API_URL = "https://trends.google.com/trends/api/widgetdata/multiline"
GEO_MAP_API_URL = "https://trends.google.com/trends/api/widgetdata/comparedgeo"
TIME_RANGE = "now 7-d"
DEFAULT_KEYWORDS = DEFAULT_TREND_KEYWORDS
REGIONS = TREND_REGIONS
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/124.0.0.0 Safari/537.36"
)
JST = timezone(timedelta(hours=9))


class GoogleTrendsRateLimitExhausted(RuntimeError):
    pass


def strip_google_prefix(text: str) -> str:
    marker = text.find("{")
    if marker < 0:
        raise ValueError("Google Trends response did not contain JSON")
    return text[marker:]


def build_explore_url(keyword: str, geo: str) -> str:
    params = {"q": keyword, "date": TIME_RANGE}
    if geo:
        params["geo"] = geo
    return "https://trends.google.com/trends/explore?" + urlencode(params)


class GoogleTrendsCrawler:
    def __init__(
        self,
        timeout: int = 20,
        delay: float = 10.0,
        max_retries: int = 3,
        retry_base_delay: float = 30.0,
    ) -> None:
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max(max_retries, 0)
        self.retry_base_delay = max(retry_base_delay, 0)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"})
        self._last_request_at: float | None = None
        self.failures: list[dict] = []
        self.aborted_by_rate_limit = False

    def _pace_requests(self) -> None:
        if self._last_request_at is None or self.delay <= 0:
            return
        target_interval = random.uniform(self.delay * 0.8, self.delay * 1.2)
        remaining = target_interval - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def _retry_after_seconds(self, response: requests.Response, attempt: int) -> float:
        retry_after = (response.headers.get("Retry-After") or "").strip()
        if retry_after:
            try:
                return max(float(retry_after), 0)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0)
                except (TypeError, ValueError, OverflowError):
                    pass
        return self.retry_base_delay * (2 ** attempt)

    def _get(self, url: str, *, params: dict) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            self._pace_requests()
            self._last_request_at = time.monotonic()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise
                wait_seconds = self.retry_base_delay * (2 ** attempt)
                print(
                    f"[WARN] Google Trends request error: {type(exc).__name__}; "
                    f"retry={attempt + 1}/{self.max_retries}, wait={wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise GoogleTrendsRateLimitExhausted(
                        f"Google Trends rate limit remained after {self.max_retries} retries"
                    )
                wait_seconds = self._retry_after_seconds(response, attempt)
                print(
                    f"[WARN] Google Trends HTTP 429; retry={attempt + 1}/{self.max_retries}, "
                    f"wait={wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                wait_seconds = self.retry_base_delay * (2 ** attempt)
                print(
                    f"[WARN] Google Trends HTTP {response.status_code}; "
                    f"retry={attempt + 1}/{self.max_retries}, wait={wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            return response

        raise RuntimeError("Google Trends request retry loop ended unexpectedly")

    def fetch_interest(self, keyword: str, geo: str) -> tuple[list[dict], list[dict]]:
        request_payload = {
            "comparisonItem": [{"keyword": keyword, "geo": geo, "time": TIME_RANGE}],
            "category": 0,
            "property": "",
        }
        response = self._get(
            EXPLORE_API_URL,
            params={"hl": "ja", "tz": "-540", "req": json.dumps(request_payload, ensure_ascii=False)},
        )
        payload = json.loads(strip_google_prefix(response.text))
        widget = next((item for item in payload.get("widgets", []) if item.get("id") == "TIMESERIES"), None)
        if not widget:
            raise ValueError("Google Trends TIMESERIES widget was not returned")
        geo_widget = next((item for item in payload.get("widgets", []) if item.get("id") == "GEO_MAP"), None)

        response = self._get(
            TIMESERIES_API_URL,
            params={
                "hl": "ja",
                "tz": "-540",
                "req": json.dumps(widget["request"], ensure_ascii=False),
                "token": widget["token"],
            },
        )
        timeline = json.loads(strip_google_prefix(response.text)).get("default", {}).get("timelineData", [])
        points = []
        for point in timeline:
            values = point.get("value") or []
            if not values:
                continue
            timestamp = datetime.fromtimestamp(int(point["time"]), JST)
            points.append({
                "date": timestamp.strftime("%Y-%m-%d"),
                "datetime": timestamp.strftime("%Y-%m-%d %H:%M"),
                "label": point.get("formattedTime", ""),
                "value": int(values[0]),
                "partial": bool(point.get("isPartial")),
            })
        regional_interest = []
        if geo_widget:
            response = self._get(
                GEO_MAP_API_URL,
                params={
                    "hl": "ja",
                    "tz": "-540",
                    "req": json.dumps(geo_widget["request"], ensure_ascii=False),
                    "token": geo_widget["token"],
                },
            )
            geo_data = json.loads(strip_google_prefix(response.text)).get("default", {}).get("geoMapData", [])
            for region in geo_data:
                values = region.get("value") or []
                if not values:
                    continue
                try:
                    value = int(values[0])
                except (TypeError, ValueError):
                    continue
                regional_interest.append({
                    "name": region.get("geoName") or region.get("geoCode") or "地域名不明",
                    "code": region.get("geoCode", ""),
                    "value": max(0, min(100, value)),
                })
            regional_interest.sort(key=lambda value: (-value["value"], value["name"]))
        return points, regional_interest[:5]

    def crawl(self, keywords: list[str]) -> list[dict]:
        self.failures = []
        self.aborted_by_rate_limit = False
        results = []
        for keyword in keywords:
            for geo, region_label in REGIONS:
                explore_url = build_explore_url(keyword, geo)
                try:
                    points, regional_interest = self.fetch_interest(keyword, geo)
                    if not points:
                        raise ValueError("Google Trends timeline data was empty")
                except GoogleTrendsRateLimitExhausted as exc:
                    self.failures.append({
                        "keyword": keyword,
                        "geo": geo,
                        "region_label": region_label,
                        "error": str(exc),
                    })
                    self.aborted_by_rate_limit = True
                    print(
                        f"[ERROR] Google Trends rate limit exhausted: keyword={keyword!r}, "
                        f"region={region_label}; remaining combinations aborted"
                    )
                    return results
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    self.failures.append({
                        "keyword": keyword,
                        "geo": geo,
                        "region_label": region_label,
                        "error": error,
                    })
                    print(
                        f"[ERROR] Google Trends collection failed: keyword={keyword!r}, "
                        f"region={region_label}, error={error}"
                    )
                    continue

                values = [point["value"] for point in points]
                latest_value = values[-1]
                average_value = round(sum(values) / len(values), 1)
                peak_value = max(values)
                snapshot_date = datetime.now(JST).date().isoformat()
                results.append({
                    "source_name": f"Google Trends / {region_label}",
                    "source_type": "trend",
                    "title": f"Google Trends: {keyword} / {region_label}",
                    # Keep one stable URL per keyword and region. The previous
                    # snapshot query parameter created a new DB row every day.
                    "url": explore_url,
                    "published_at": snapshot_date,
                    "raw_summary": f"過去7日間の検索関心度: 最新={latest_value}, 平均={average_value}, 最高={peak_value}",
                    "raw_text": json.dumps({
                        "provider": "Google Trends",
                        "keyword": keyword,
                        "geo": geo,
                        "region_label": region_label,
                        "time_range": TIME_RANGE,
                        "explore_url": explore_url,
                        "fetched_on": snapshot_date,
                        "latest_value": latest_value,
                        "average_value": average_value,
                        "peak_value": peak_value,
                        "points": points,
                        "regional_interest": regional_interest,
                        "error": "",
                    }, ensure_ascii=False),
                })
        return results


def save_google_trend_item(data: dict) -> tuple[bool, int]:
    """Insert once, then update the existing keyword/region snapshot in place.

    Older rows created by the former snapshot-URL implementation are removed for
    this exact keyword/region. A failed collection never calls this function, so
    the last successful values remain visible.
    """
    existing_rows = (
        RawItem.query
        .filter(RawItem.source_type == "trend", RawItem.title == data["title"])
        .order_by(RawItem.fetched_at.desc(), RawItem.id.desc())
        .all()
    )
    if not existing_rows:
        return save_raw_item(data), 0

    current = existing_rows[0]
    for field_name in ("source_name", "source_type", "title", "published_at", "raw_summary", "raw_text"):
        setattr(current, field_name, data.get(field_name))
    current.crawl_batch_id = get_current_crawl_batch_id()
    current.fetched_at = datetime.utcnow()
    current.is_new = False

    removed = 0
    for duplicate in existing_rows[1:]:
        db.session.delete(duplicate)
        removed += 1
    db.session.commit()
    return False, removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Physical AI関連語のGoogle Trendsを収集する")
    parser.add_argument("--keywords", nargs="+", default=DEFAULT_KEYWORDS)
    parser.add_argument("--delay", type=float, default=10.0, help="HTTPリクエスト間の基本待機秒数（±20%%のジッター付き）")
    parser.add_argument("--max-retries", type=int, default=3, help="429・通信エラー・5xxの最大再試行回数")
    parser.add_argument("--retry-base-delay", type=float, default=30.0, help="指数バックオフの初期待機秒数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawler = GoogleTrendsCrawler(
        delay=max(args.delay, 0),
        max_retries=max(args.max_retries, 0),
        retry_base_delay=max(args.retry_base_delay, 0),
    )
    results = crawler.crawl(args.keywords)
    inserted = 0
    updated = 0
    removed_duplicates = 0
    with app.app_context():
        for item in results:
            was_inserted, removed = save_google_trend_item(item)
            inserted += int(was_inserted)
            updated += int(not was_inserted)
            removed_duplicates += removed
    print(
        f"google trends: successful={len(results)}, failed={len(crawler.failures)}, "
        f"inserted={inserted}, updated={updated}, removed_duplicates={removed_duplicates}, "
        f"rate_limit_abort={crawler.aborted_by_rate_limit}"
    )
    if crawler.failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
