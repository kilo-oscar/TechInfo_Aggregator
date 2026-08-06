from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from html import escape
from typing import Iterable

from models import RawItem


FIELD_LABELS = {
    "physical_ai": "Physical AI",
    "robot_makers": "Robot Makers",
    "real_haptics": "Real Haptics",
    "startup": "Startup",
    "paper": "論文",
    "event": "展示会・イベント",
    "policy": "政策",
    "thinktank": "シンクタンク",
    "company": "企業",
    "other_news": "その他ニュース",
    "other": "その他",
}

PHYSICAL_AI_KEYWORDS = (
    "physical ai", "physical-ai", "physical_ai", "フィジカルai",
    "embodied ai", "embodied intelligence", "身体性ai", "vla",
    "vision-language-action", "vision language action",
)

PHYSICAL_DOMAIN_KEYWORDS = (
    "robot", "robotics", "humanoid", "ロボット", "ロボティクス", "ヒューマノイド",
    "autonomous machine", "embodied", "haptic", "自律機械", "ハプティクス",
)

THEME_KEYWORDS = {
    "ヒューマノイド": ("humanoid", "ヒューマノイド", "人型ロボット"),
    "VLA・基盤モデル": ("vla", "vision-language-action", "vision language action", "foundation model", "基盤モデル"),
    "自律移動・モビリティ": ("autonomous", "mobility", "self-driving", "自律移動", "自動運転", "amr"),
    "製造・産業ロボット": ("manufactur", "industrial robot", "factory", "製造", "産業用ロボット", "工場"),
    "遠隔操作・ハプティクス": ("teleoperation", "remote operation", "haptic", "遠隔操作", "ハプティクス", "触覚"),
    "シミュレーション・学習": ("simulation", "sim-to-real", "reinforcement learning", "シミュレーション", "強化学習"),
    "投資・事業化": ("funding", "investment", "startup", "資金調達", "投資", "事業化", "スタートアップ"),
    "政策・規制": ("policy", "regulation", "government", "政策", "規制", "政府"),
}

DOMESTIC_MARKERS = (
    "日本", "国内", "東京", "大阪", "名古屋", "福岡", "札幌",
    "japan", "tokyo", "osaka", "nagoya", "fukuoka", "sapporo",
    "日経", "itmedia", "monoist", "ascii.jp", "pr times", "prtimes",
    "ロボスタ", "robotstart", "robostart", "impress", "マイナビ", "共同通信",
    "nvidia | japan blog", "japan blog",
)

OVERSEAS_MARKERS = (
    "united states", "u.s.", "usa", "europe", "germany", "france", " uk ",
    "china", "korea", "singapore", "taiwan", "canada", "australia",
    "reuters", "bloomberg", "techcrunch", "the robot report", "venturebeat",
    "ieee spectrum", "robotics 24/7", "siliconangle", "crn", "zdnet", "forbes",
)


def normalize_report_month(value: str) -> str:
    value = (value or "").strip()
    return value if re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", value) else ""


def previous_month(value: str) -> str:
    year, month = (int(part) for part in value.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def item_blob(item: RawItem) -> str:
    return " ".join([
        item.source_name or "", item.title or "", item.raw_summary or "", item.raw_text or "",
    ]).lower()


def item_surface_blob(item: RawItem) -> str:
    return " ".join([
        item.title or "", item.raw_summary or "",
    ]).lower()


def contains_keyword(blob: str, keyword: str) -> bool:
    if keyword == "vla":
        return re.search(r"\bvla\b", blob, flags=re.IGNORECASE) is not None
    return keyword in blob


def is_physical_ai(item: RawItem) -> bool:
    # raw_textにはクローラの検索条件が保存される場合があるため、
    # Physical AI自体の判定には読者に表示される情報だけを使う。
    blob = item_surface_blob(item)
    if any(contains_keyword(blob, keyword) for keyword in PHYSICAL_AI_KEYWORDS):
        return True
    source_name = (item.source_name or "").lower()
    return (
        "physical ai" in source_name
        and any(contains_keyword(blob, keyword) for keyword in PHYSICAL_DOMAIN_KEYWORDS)
    )


def classify_region(item: RawItem) -> str:
    blob = item_blob(item)
    if any(marker in blob for marker in DOMESTIC_MARKERS):
        return "domestic"
    if any(marker in blob for marker in OVERSEAS_MARKERS):
        return "overseas"
    if any("\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff" for char in blob):
        return "domestic"
    return "overseas"


def classify_field(item: RawItem) -> str:
    source_name = (item.source_name or "").strip().lower()
    if item.source_type == "paper":
        return "paper"
    if item.source_type == "event":
        return "event"
    if item.source_type == "policy":
        return "policy"
    if item.source_type == "thinktank":
        return "thinktank"
    if source_name.startswith("startup /"):
        return "startup"
    if item.source_type == "company":
        return "company"
    if item.source_type == "news":
        if "real haptics" in source_name:
            return "real_haptics"
        if "robot makers" in source_name:
            return "robot_makers"
        if is_physical_ai(item):
            return "physical_ai"
        return "other_news"
    return "other"


def _theme_counts(items: Iterable[RawItem]) -> list[dict]:
    counts = Counter()
    for item in items:
        blob = item_blob(item)
        for label, keywords in THEME_KEYWORDS.items():
            if any(contains_keyword(blob, keyword) for keyword in keywords):
                counts[label] += 1
    return [{"label": label, "count": count} for label, count in counts.most_common()]


def _representative_items(items: list[RawItem], limit: int = 5) -> list[RawItem]:
    return sorted(
        items,
        key=lambda item: ((item.published_at or ""), item.id or 0),
        reverse=True,
    )[:limit]


def _top_sources(items: list[RawItem], limit: int = 3) -> list[dict]:
    counts = Counter((item.source_name or "不明").strip() or "不明" for item in items)
    return [{"label": label, "count": count} for label, count in counts.most_common(limit)]


def _build_field_summary(field: dict, top_sources: list[dict]) -> str:
    count = field["count"]
    previous_count = field["previous_count"]
    if count == 0:
        if previous_count:
            return f'{field["label"]}は当月0件で、前月の{previous_count}件から収集がありませんでした。'
        return f'{field["label"]}は当月・前月とも収集がありませんでした。'

    change = field["change"]
    if previous_count == 0:
        comparison = "前月は0件で、当月に新たに収集されました"
    elif change > 0:
        comparison = f"前月から{change}件増加しました"
    elif change < 0:
        comparison = f"前月から{abs(change)}件減少しました"
    else:
        comparison = "前月と同数でした"
    source_text = ""
    if top_sources:
        source_text = " 主な情報源は" + "、".join(
            f'{source["label"]}（{source["count"]}件）' for source in top_sources
        ) + "です。"
    return (
        f'{field["label"]}は{count}件で全体の{field["percentage"]}%を占め、{comparison}。'
        f'{source_text}'
    )


def _build_trend_summary(region_label: str, items: list[RawItem], themes: list[dict]) -> str:
    if not items:
        return f"{region_label}のPhysical AI関連情報は確認できませんでした。"
    if themes:
        top = "、".join(f'{theme["label"]}（{theme["count"]}件）' for theme in themes[:3])
        return f"{region_label}ではPhysical AI関連を{len(items)}件確認しました。主なテーマは{top}です。"
    return f"{region_label}ではPhysical AI関連を{len(items)}件確認しました。"


def build_monthly_report(month: str, items: list[RawItem], previous_items: list[RawItem]) -> dict:
    month = normalize_report_month(month)
    if not month:
        raise ValueError("invalid report month")

    field_counts = Counter(classify_field(item) for item in items)
    previous_field_counts = Counter(classify_field(item) for item in previous_items)
    fields = []
    for key, label in FIELD_LABELS.items():
        count = field_counts.get(key, 0)
        previous_count = previous_field_counts.get(key, 0)
        fields.append({
            "key": key,
            "label": label,
            "count": count,
            "previous_count": previous_count,
            "change": count - previous_count,
        })

    physical_items = [item for item in items if is_physical_ai(item)]
    domestic_items = [item for item in physical_items if classify_region(item) == "domestic"]
    overseas_items = [item for item in physical_items if classify_region(item) == "overseas"]
    domestic_themes = _theme_counts(domestic_items)
    overseas_themes = _theme_counts(overseas_items)
    max_field_count = max((field["count"] for field in fields), default=0)
    for field in fields:
        field["percentage"] = round(field["count"] / len(items) * 100, 1) if items else 0
        field["bar_width"] = round(field["count"] / max_field_count * 100, 1) if max_field_count else 0

    field_analyses = []
    for field in fields:
        field_items = [item for item in items if classify_field(item) == field["key"]]
        top_sources = _top_sources(field_items)
        themes = _theme_counts(field_items)
        field_analyses.append({
            **field,
            "summary": _build_field_summary(field, top_sources),
            "sources": top_sources,
            "themes": themes[:5],
            "items": _representative_items(field_items, limit=3),
        })

    physical_total = len(physical_items)
    domestic_percentage = round(len(domestic_items) / physical_total * 100, 1) if physical_total else 0
    overseas_percentage = round(len(overseas_items) / physical_total * 100, 1) if physical_total else 0

    return {
        "month": month,
        "label": f'{month[:4]}年{int(month[5:])}月',
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(items),
        "previous_month": previous_month(month),
        "previous_total": len(previous_items),
        "total_change": len(items) - len(previous_items),
        "fields": fields,
        "field_analyses": field_analyses,
        "physical_ai_total": physical_total,
        "domestic_percentage": domestic_percentage,
        "overseas_percentage": overseas_percentage,
        "domestic": {
            "count": len(domestic_items),
            "themes": domestic_themes,
            "summary": _build_trend_summary("国内", domestic_items, domestic_themes),
            "items": _representative_items(domestic_items),
        },
        "overseas": {
            "count": len(overseas_items),
            "themes": overseas_themes,
            "summary": _build_trend_summary("海外", overseas_items, overseas_themes),
            "items": _representative_items(overseas_items),
        },
    }


def render_field_chart_svg(report: dict) -> str:
    fields = [field for field in report["fields"] if field["count"]]
    width, row_height = 900, 42
    height = 90 + max(len(fields), 1) * row_height
    chart_x, chart_width = 210, 560
    rows = []
    for index, field in enumerate(fields):
        y = 65 + index * row_height
        bar_width = chart_width * field["bar_width"] / 100
        rows.extend([
            f'<text x="20" y="{y + 17}" font-size="15" fill="#1f2937">{escape(field["label"])}</text>',
            f'<rect x="{chart_x}" y="{y}" width="{chart_width}" height="24" rx="12" fill="#e2e8f0"/>',
            f'<rect x="{chart_x}" y="{y}" width="{bar_width:.1f}" height="24" rx="12" fill="#2563eb"/>',
            f'<text x="{chart_x + chart_width + 15}" y="{y + 17}" font-size="14" fill="#334155">{field["count"]}件 ({field["percentage"]}%)</text>',
        ])
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="分野別件数">',
        '<rect width="100%" height="100%" rx="16" fill="#ffffff"/>',
        '<text x="20" y="35" font-size="22" font-weight="bold" fill="#0f172a">分野別件数</text>',
        *rows, '</svg>',
    ])


def render_region_chart_svg(report: dict) -> str:
    domestic = report["domestic"]["count"]
    overseas = report["overseas"]["count"]
    domestic_percentage = report["domestic_percentage"]
    overseas_percentage = report["overseas_percentage"]
    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="700" height="330" viewBox="0 0 700 330" role="img" aria-label="Physical AIの国内海外比率">',
        '<rect width="100%" height="100%" rx="16" fill="#ffffff"/>',
        '<text x="24" y="38" font-size="22" font-weight="bold" fill="#0f172a">Physical AIの国内・海外比率</text>',
        '<circle cx="175" cy="180" r="92" fill="none" stroke="#e2e8f0" stroke-width="42"/>',
        f'<circle cx="175" cy="180" r="92" fill="none" stroke="#2563eb" stroke-width="42" pathLength="100" stroke-dasharray="{domestic_percentage} {100 - domestic_percentage}" transform="rotate(-90 175 180)"/>',
        f'<circle cx="175" cy="180" r="92" fill="none" stroke="#f59e0b" stroke-width="42" pathLength="100" stroke-dasharray="{overseas_percentage} {100 - overseas_percentage}" stroke-dashoffset="{-domestic_percentage}" transform="rotate(-90 175 180)"/>',
        f'<text x="175" y="176" text-anchor="middle" font-size="34" font-weight="bold" fill="#0f172a">{report["physical_ai_total"]}</text>',
        '<text x="175" y="203" text-anchor="middle" font-size="15" fill="#64748b">合計</text>',
        '<circle cx="370" cy="135" r="8" fill="#2563eb"/>',
        f'<text x="390" y="141" font-size="18" fill="#1f2937">国内 {domestic}件 ({domestic_percentage}%)</text>',
        '<circle cx="370" cy="190" r="8" fill="#f59e0b"/>',
        f'<text x="390" y="196" font-size="18" fill="#1f2937">海外 {overseas}件 ({overseas_percentage}%)</text>',
        '</svg>',
    ])


def render_report_markdown(report: dict, chart_base: str | None = None) -> str:
    chart_base = chart_base or f'/reports/{report["month"]}/charts'
    lines = [
        f'# {report["label"]} TechInfo月次レポート', "",
        f'- 対象件数: {report["total"]}件',
        f'- 前月（{report["previous_month"]}）: {report["previous_total"]}件',
        f'- 前月比: {report["total_change"]:+d}件',
        f'- Physical AI関連: {report["physical_ai_total"]}件', "",
        "## サマリーグラフ", "",
        f'![分野別件数]({chart_base}/fields.svg)', "",
        f'![Physical AIの国内・海外比率]({chart_base}/regions.svg)', "",
        "### Mermaid版", "",
        "```mermaid", "pie showData", "    title Physical AI関連の国内・海外比率",
        f'    "国内" : {report["domestic"]["count"]}',
        f'    "海外" : {report["overseas"]["count"]}',
        "```", "",
        "```mermaid", "pie showData", "    title 分野別件数",
    ]
    for field in report["fields"]:
        if field["count"]:
            lines.append(f'    "{field["label"]}" : {field["count"]}')
    lines.extend([
        "```", "", "*Mermaid非対応のビューアーでは、以下の表で数値を確認できます。*", "",
        "## 分野別件数", "",
        "| 分野 | 件数 | 前月 | 増減 |",
        "|---|---:|---:|---:|",
    ])
    for field in report["fields"]:
        lines.append(f'| {field["label"]} | {field["count"]} | {field["previous_count"]} | {field["change"]:+d} |')

    lines.extend(["", "## 分野別の動向", ""])
    for field in report["field_analyses"]:
        lines.extend([f'### {field["label"]}', "", field["summary"], ""])
        if field["themes"]:
            lines.append("主なテーマ: " + "、".join(
                f'{theme["label"]}（{theme["count"]}件）' for theme in field["themes"]
            ))
            lines.append("")
        if field["items"]:
            lines.append("代表的な情報:")
            lines.append("")
            for item in field["items"]:
                published = f' ({item.published_at})' if item.published_at else ""
                lines.append(f'- [{item.title}]({item.url}){published} — {item.source_name}')
            lines.append("")

    for key, title in (("domestic", "国内Physical AIの動向"), ("overseas", "海外Physical AIの動向")):
        section = report[key]
        lines.extend(["", f"## {title}", "", section["summary"], ""])
        if section["themes"]:
            lines.extend(["### 主なテーマ", ""])
            lines.extend(f'- {theme["label"]}: {theme["count"]}件' for theme in section["themes"])
            lines.append("")
        if section["items"]:
            lines.extend(["### 代表的な情報", ""])
            for item in section["items"]:
                published = f' ({item.published_at})' if item.published_at else ""
                lines.append(f'- [{item.title}]({item.url}){published} — {item.source_name}')

    lines.extend([
        "", "## 判定方法", "",
        "- 集計月は `published_at` の年月を使用しています。",
        "- 分野は `source_type`、`source_name`、タイトル・要約内のキーワードから主分類を1つ付与しています。",
        "- 国内・海外はソース名、タイトル、要約、本文の地名・媒体名と言語から推定しています。",
        "- 動向文は収集データの件数とキーワード出現に基づく自動要約です。",
        "", f'生成日時: {report["generated_at"]}', "",
    ])
    return "\n".join(lines)
