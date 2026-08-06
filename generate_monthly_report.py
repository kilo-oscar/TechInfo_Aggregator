from __future__ import annotations

import argparse
from pathlib import Path

from app import app, get_monthly_report
from monthly_reports import (
    normalize_report_month,
    render_field_chart_svg,
    render_region_chart_svg,
    render_report_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SQLiteから月次分析レポートをMarkdown生成する")
    parser.add_argument("month", help="対象月 (YYYY-MM)")
    parser.add_argument("--output", "-o", help="出力先。省略時は reports/YYYY-MM.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    month = normalize_report_month(args.month)
    if not month:
        raise SystemExit("対象月は YYYY-MM 形式で指定してください")

    output_path = Path(args.output) if args.output else Path("reports") / f"{month}.md"
    with app.app_context():
        report = get_monthly_report(month)
        if report is None:
            raise SystemExit("月次レポートを生成できませんでした")
        asset_directory = output_path.parent / "assets" / month
        chart_base = f"assets/{month}"
        markdown = render_report_markdown(report, chart_base=chart_base)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    asset_directory.mkdir(parents=True, exist_ok=True)
    (asset_directory / "fields.svg").write_text(render_field_chart_svg(report), encoding="utf-8")
    (asset_directory / "regions.svg").write_text(render_region_chart_svg(report), encoding="utf-8")
    output_path.write_text(markdown, encoding="utf-8")
    print(f"monthly report generated: {output_path} ({report['total']} items)")


if __name__ == "__main__":
    main()
