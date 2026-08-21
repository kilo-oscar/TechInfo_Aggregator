from __future__ import annotations

from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, Line, Polygon, PolyLine, Rect, String
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    PageBreak,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape


FONT_CANDIDATES = [
    Path("/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
]
REPOSITORY_URL = "https://github.com/kilo-oscar/TechInfo_Aggregator"


class LinkedDrawing(Drawing):
    """A ReportLab drawing that can add clickable URL rectangles."""

    def __init__(self, width, height, *args, **kwargs):
        super().__init__(width, height, *args, **kwargs)
        object.__setattr__(self, "_url_links", [])

    def add_url_link(self, url: str, rect: tuple[float, float, float, float]) -> None:
        if url.startswith(("http://", "https://")):
            self._url_links.append((url, rect))

    def drawOn(self, canvas, x, y, _sW=0):
        from reportlab.pdfbase.pdfdoc import PDFName

        adjusted_x = self._hAlignAdjust(x, _sW)
        super().drawOn(canvas, adjusted_x, y, 0)
        for url, (x1, y1, x2, y2) in self._url_links:
            canvas.linkURL(
                url,
                (adjusted_x + x1, y + y1, adjusted_x + x2, y + y2),
                relative=0,
                thickness=0,
                H=PDFName("I"),
            )


def register_japanese_font() -> str:
    font_path = next((path for path in FONT_CANDIDATES if path.exists()), None)
    if font_path is None:
        raise RuntimeError("PDF生成に必要な日本語フォントが見つかりません。")
    font_name = "DailyNewsJapanese"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    return font_name


def render_daily_news_pdf(
    report_date: str,
    category_groups: list[dict],
    *,
    report_title: str = "Physical-AIデイリー情報収集レポート",
    scope_description: str = "指定日に取得したすべての情報を種別ごとに整理しています。",
    footer_label: str = "Physical-AI情報収集クローラ",
    group_items_by_year: bool = False,
    include_yearly_event_calendar: bool = False,
) -> bytes:
    font_name = register_japanese_font()
    created_date_jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    buffer = BytesIO()
    width, height = A4
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"{report_title}（{report_date}）",
        author="Physical-AI情報収集クローラ",
    )
    summary_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="summary")
    column_gap = 5 * mm
    column_width = (doc.width - column_gap) / 2
    detail_frames = [
        Frame(doc.leftMargin, doc.bottomMargin, column_width, doc.height, id="left-column"),
        Frame(doc.leftMargin + column_width + column_gap, doc.bottomMargin, column_width, doc.height, id="right-column"),
    ]

    def draw_page(canvas, document):
        canvas.saveState()
        if document.page == 1:
            canvas.bookmarkPage("report-top")
        header_link_text = "先頭ページへ戻る"
        header_link_x = 12 * mm
        header_link_y = height - 8 * mm
        canvas.setFont(font_name, 7.5)
        canvas.setFillColor(colors.HexColor("#1d4ed8"))
        canvas.drawString(header_link_x, header_link_y, header_link_text)
        header_link_width = canvas.stringWidth(header_link_text, font_name, 7.5)
        canvas.linkRect(
            "",
            "report-top",
            (header_link_x, header_link_y - 1.5 * mm, header_link_x + header_link_width, header_link_y + 2.5 * mm),
            relative=0,
            thickness=0,
        )
        if document.page == 1:
            canvas.setFont(font_name, 7.5)
            canvas.setFillColor(colors.HexColor("#475569"))
            canvas.drawRightString(width - 12 * mm, header_link_y, f"作成日: {created_date_jst}（日本時間）")
        canvas.setFont(font_name, 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(12 * mm, 6 * mm, f"{footer_label} / {report_date}")
        canvas.drawRightString(width - 12 * mm, 6 * mm, f"{document.page}ページ")
        repository_y = 10 * mm
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#1d4ed8"))
        repository_width = canvas.stringWidth(REPOSITORY_URL, "Helvetica", 6.5)
        repository_x = (width - repository_width) / 2
        canvas.drawString(repository_x, repository_y, REPOSITORY_URL)
        canvas.linkURL(
            REPOSITORY_URL,
            (repository_x, repository_y - 1.2 * mm, repository_x + repository_width, repository_y + 2.2 * mm),
            relative=0,
            thickness=0,
        )
        canvas.restoreState()

    doc.addPageTemplates([
        PageTemplate(id="summary", frames=[summary_frame], onPage=draw_page),
        PageTemplate(id="details", frames=detail_frames, onPage=draw_page),
    ])
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "JapaneseTitle", parent=styles["Title"], fontName=font_name,
        fontSize=18, leading=23, alignment=TA_CENTER, textColor=colors.HexColor("#0f172a"),
        spaceAfter=4 * mm,
    )
    heading_style = ParagraphStyle(
        "JapaneseHeading", parent=styles["Heading2"], fontName=font_name,
        fontSize=11, leading=14, textColor=colors.HexColor("#1d4ed8"),
        spaceBefore=3 * mm, spaceAfter=1.5 * mm,
    )
    subheading_style = ParagraphStyle(
        "JapaneseSubheading", parent=styles["Heading3"], fontName=font_name,
        fontSize=8.5, leading=11, textColor=colors.HexColor("#334155"),
        backColor=colors.HexColor("#f1f5f9"), borderPadding=(2, 3, 2, 3),
        spaceBefore=2 * mm, spaceAfter=1.2 * mm,
    )
    year_heading_style = ParagraphStyle(
        "JapaneseYearHeading", parent=styles["Heading4"], fontName=font_name,
        fontSize=8, leading=10, textColor=colors.HexColor("#7c3aed"),
        borderColor=colors.HexColor("#c4b5fd"), borderWidth=0, borderPadding=(1, 2, 1, 2),
        spaceBefore=1.8 * mm, spaceAfter=1 * mm, keepWithNext=True,
    )
    article_title_style = ParagraphStyle(
        "ArticleTitle", parent=styles["Heading3"], fontName=font_name,
        fontSize=8, leading=10.5, textColor=colors.HexColor("#0f172a"), spaceAfter=0.6 * mm,
    )
    body_style = ParagraphStyle(
        "JapaneseBody", parent=styles["BodyText"], fontName=font_name,
        fontSize=6.8, leading=9.2, textColor=colors.HexColor("#334155"), spaceAfter=0.7 * mm,
    )
    meta_style = ParagraphStyle(
        "JapaneseMeta", parent=body_style, fontSize=6.2, leading=8,
        textColor=colors.HexColor("#64748b"),
    )

    def trend_chart(trend: dict) -> Drawing:
        chart_width = column_width - 5 * mm
        chart_height = 35 * mm
        left = 9 * mm
        bottom = 7 * mm
        plot_width = chart_width - left - 2 * mm
        plot_height = chart_height - bottom - 2 * mm
        drawing = Drawing(chart_width, chart_height)
        for interest in (0, 50, 100):
            y = bottom + interest / 100 * plot_height
            drawing.add(Line(left, y, left + plot_width, y, strokeColor=colors.HexColor("#e2e8f0"), strokeWidth=0.5))
            drawing.add(String(1 * mm, y - 2, str(interest), fontName="Helvetica", fontSize=5.5, fillColor=colors.HexColor("#64748b")))
        values = trend.get("values") or []
        if values:
            denominator = max(len(values) - 1, 1)
            points = [
                (left + index / denominator * plot_width, bottom + max(0, min(100, value)) / 100 * plot_height)
                for index, value in enumerate(values)
            ]
            drawing.add(PolyLine(points, strokeColor=colors.HexColor("#db2777"), strokeWidth=1.4, fillColor=None))
        drawing.add(String(left, 1.2 * mm, trend.get("start_date") or "", fontName="Helvetica", fontSize=5.2, fillColor=colors.HexColor("#64748b")))
        drawing.add(String(left + plot_width, 1.2 * mm, trend.get("end_date") or "", textAnchor="end", fontName="Helvetica", fontSize=5.2, fillColor=colors.HexColor("#64748b")))
        return drawing

    def published_date_key(item: dict) -> tuple[int, str]:
        value = str(item.get("published_at") or "")
        match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", value)
        if not match:
            return (0, "")
        year, month, day = match.groups()
        return (1, f"{year}-{int(month):02d}-{int(day):02d}")

    def published_year(item: dict) -> str:
        date_key = published_date_key(item)
        return f"{date_key[1][:4]}年" if date_key[0] else "日付不明"

    def yearly_event_calendar_flowables() -> list:
        events_by_year: dict[int, list[tuple]] = {}
        undated_count = 0
        for group in category_groups:
            for item in group.get("items", []):
                start_text = item.get("event_start_date") or ""
                end_text = item.get("event_end_date") or start_text
                try:
                    start = datetime.strptime(start_text, "%Y-%m-%d").date()
                    end = datetime.strptime(end_text, "%Y-%m-%d").date()
                except (TypeError, ValueError):
                    undated_count += 1
                    continue
                if end < start:
                    end = start
                # Events crossing New Year are clipped into one arrow per year.
                for year in range(start.year, end.year + 1):
                    segment_start = max(start, datetime(year, 1, 1).date())
                    segment_end = min(end, datetime(year, 12, 31).date())
                    events_by_year.setdefault(year, []).append((segment_start, segment_end, item))

        if not events_by_year:
            return [Paragraph("開催日を特定できるイベントがないため、年間カレンダーを表示できません。", body_style)]
        calendar_flowables = []

        country_colors = {
            "日本": "#2563eb", "米国": "#7c3aed", "中国": "#dc2626",
            "韓国": "#059669", "その他": "#64748b",
        }
        legend = Drawing(doc.width, 20)
        legend.add(String(4, 12, "矢羽根の色:", fontName=font_name, fontSize=6.5, fillColor=colors.HexColor("#475569")))
        legend_x = 72
        for country in ("日本", "米国", "中国", "韓国", "その他"):
            color = colors.HexColor(country_colors[country])
            legend.add(Line(legend_x, 13, legend_x + 18, 13, strokeColor=color, strokeWidth=2.2))
            legend.add(Polygon([legend_x + 18, 13, legend_x + 14, 15.5, legend_x + 14, 10.5], fillColor=color, strokeColor=color))
            legend.add(String(legend_x + 22, 11, country, fontName=font_name, fontSize=6.5, fillColor=colors.HexColor("#334155")))
            legend_x += 76
        legend.add(String(4, 1, "薄い青色のイベント名はクリック可能な外部リンクです。", fontName=font_name, fontSize=5.8, fillColor=colors.HexColor("#1d4ed8")))
        calendar_flowables.extend([legend, Spacer(1, 1 * mm)])
        for year in sorted(events_by_year):
            events = sorted(events_by_year[year], key=lambda value: (value[0], value[1], value[2].get("title", "")))
            lane_height = 8.2
            header_height = 24
            chart_width = doc.width
            chart_height = header_height + len(events) * lane_height + 7
            drawing = LinkedDrawing(chart_width, chart_height)
            axis_left = 4
            axis_right = chart_width - 4
            axis_width = axis_right - axis_left
            year_start = datetime(year, 1, 1).date()
            year_end = datetime(year + 1, 1, 1).date()
            days_in_year = (year_end - year_start).days

            drawing.add(String(axis_left, chart_height - 8, f"{year}年 年間イベントカレンダー", fontName=font_name, fontSize=9, fillColor=colors.HexColor("#1d4ed8")))
            axis_top = chart_height - header_height
            drawing.add(Rect(axis_left, 0, axis_width, axis_top, fillColor=colors.HexColor("#ffffff"), strokeColor=colors.HexColor("#cbd5e1"), strokeWidth=0.5))
            for month in range(1, 13):
                month_start = datetime(year, month, 1).date()
                x = axis_left + (month_start - year_start).days / days_in_year * axis_width
                next_month = datetime(year + 1, 1, 1).date() if month == 12 else datetime(year, month + 1, 1).date()
                next_x = axis_left + (next_month - year_start).days / days_in_year * axis_width
                if month % 2 == 0:
                    drawing.add(Rect(x, 0, next_x - x, axis_top, fillColor=colors.HexColor("#f8fafc"), strokeColor=None))
                drawing.add(Line(x, 0, x, axis_top, strokeColor=colors.HexColor("#cbd5e1"), strokeWidth=0.35))
                drawing.add(String((x + next_x) / 2, axis_top + 5, f"{month}月", textAnchor="middle", fontName=font_name, fontSize=6.2, fillColor=colors.HexColor("#334155")))
            drawing.add(Line(axis_right, 0, axis_right, axis_top, strokeColor=colors.HexColor("#cbd5e1"), strokeWidth=0.35))

            for lane, (start, end, item) in enumerate(events):
                y = axis_top - (lane + 1) * lane_height + 3
                start_x = axis_left + (start - year_start).days / days_in_year * axis_width
                end_x = axis_left + ((end - year_start).days + 1) / days_in_year * axis_width
                end_x = max(end_x, start_x + 5)
                color = colors.HexColor(country_colors.get(item.get("event_country", "その他"), "#64748b"))
                drawing.add(Line(start_x, y, end_x, y, strokeColor=color, strokeWidth=2.2))
                drawing.add(Polygon([end_x, y, end_x - 4, y + 2.5, end_x - 4, y - 2.5], fillColor=color, strokeColor=color))
                raw_title = str(item.get("title") or "タイトルなし")
                title = raw_title if len(raw_title) <= 27 else raw_title[:26] + "…"
                date_label = start.strftime("%m/%d") if start == end else f'{start.strftime("%m/%d")}–{end.strftime("%m/%d")}'
                label = f"{title} ({date_label})"
                label_width = pdfmetrics.stringWidth(label, font_name, 5.2)
                text_y = y - 1.7
                link_color = colors.HexColor("#1d4ed8")
                link_background = colors.HexColor("#eff6ff")
                if end_x > axis_left + axis_width * 0.72:
                    link_left = max(axis_left, start_x - 2 - label_width)
                    link_right = min(axis_right, end_x + 2)
                    drawing.add(Rect(link_left - 1, y - 3.5, min(label_width + 2, start_x - link_left), 7, fillColor=link_background, strokeColor=None))
                    drawing.add(String(start_x - 2, text_y, label, textAnchor="end", fontName=font_name, fontSize=5.2, fillColor=link_color))
                    drawing.add(Line(link_left, text_y - 0.7, start_x - 2, text_y - 0.7, strokeColor=link_color, strokeWidth=0.35))
                else:
                    link_left = max(axis_left, start_x - 2)
                    link_right = min(axis_right, end_x + 2 + label_width)
                    drawing.add(Rect(end_x + 1, y - 3.5, max(link_right - end_x, 1), 7, fillColor=link_background, strokeColor=None))
                    drawing.add(String(end_x + 2, text_y, label, fontName=font_name, fontSize=5.2, fillColor=link_color))
                    drawing.add(Line(end_x + 2, text_y - 0.7, link_right, text_y - 0.7, strokeColor=link_color, strokeWidth=0.35))
                drawing.add_url_link(str(item.get("url") or ""), (link_left, y - 4, link_right, y + 4))
            calendar_flowables.extend([drawing, Spacer(1, 1.5 * mm)])
        if undated_count:
            calendar_flowables.append(Paragraph(f"開催日不明: {undated_count}件（詳細一覧に掲載）", meta_style))
        return calendar_flowables

    total = sum(group["count"] for group in category_groups)
    for group_index, group in enumerate(category_groups):
        group["pdf_anchor"] = f"category-{group_index}"
        for subcategory_index, subcategory in enumerate(group.get("subcategories", [])):
            subcategory["pdf_anchor"] = f"category-{group_index}-subcategory-{subcategory_index}"

    def summary_link(value: str, anchor: str) -> Paragraph:
        return Paragraph(
            f'<link href="#{anchor}" color="#1d4ed8">{escape(value)}</link>',
            ParagraphStyle(
                f"SummaryLink-{anchor}", parent=body_style, fontSize=7.5,
                leading=9, textColor=colors.HexColor("#1d4ed8"), spaceAfter=0,
            ),
        )

    story = [
        Paragraph(escape(report_title), title_style),
        Paragraph(f"{escape(scope_description)} / 対象件数: {total}件", body_style),
        Spacer(1, 3 * mm),
    ]
    summary_rows = [["大カテゴリ", "小カテゴリ", "件数"]]
    major_row_indexes = []
    for group in category_groups:
        major_row_indexes.append(len(summary_rows))
        summary_rows.append([
            summary_link(group["category"], group["pdf_anchor"]),
            summary_link("合計", group["pdf_anchor"]),
            summary_link(f'{group["count"]}件', group["pdf_anchor"]),
        ])
        summary_rows.extend([
            [
                "",
                summary_link(subcategory["label"], subcategory["pdf_anchor"]),
                summary_link(f'{subcategory["count"]}件', subcategory["pdf_anchor"]),
            ]
            for subcategory in group.get("subcategories", [])
        ])
    summary_table = Table(summary_rows, colWidths=[42 * mm, 118 * mm, 24 * mm], repeatRows=1)
    summary_style = [
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for row_index in major_row_indexes:
        summary_style.extend([
            ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#eff6ff")),
            ("TEXTCOLOR", (0, row_index), (-1, row_index), colors.HexColor("#1e3a8a")),
        ])
    summary_table.setStyle(TableStyle(summary_style))
    story.append(summary_table)
    if include_yearly_event_calendar:
        story.append(Spacer(1, 2 * mm))
        story.extend(yearly_event_calendar_flowables())
    story.extend([NextPageTemplate("details"), PageBreak()])

    for group in category_groups:
        story.append(Paragraph(
            f'<a name="{group["pdf_anchor"]}"/>{escape(group["category"])}（{group["count"]}件）',
            heading_style,
        ))
        if not group["items"]:
            story.append(Paragraph("該当する情報はありません。", body_style))
            continue
        for subcategory in group.get("subcategories", []):
            subcategory_items = [
                item for item in group["items"]
                if item.get("subcategory") == subcategory["label"]
            ]
            story.append(Paragraph(
                f'<a name="{subcategory["pdf_anchor"]}"/>{escape(subcategory["label"])}（{subcategory["count"]}件）',
                subheading_style,
            ))
            subcategory_items.sort(key=published_date_key, reverse=True)
            current_year = None
            for index, item in enumerate(subcategory_items, start=1):
                item_year = published_year(item)
                if group_items_by_year and item_year != current_year:
                    story.append(Paragraph(item_year, year_heading_style))
                    current_year = item_year
                title = escape(item["title"] or "タイトルなし")
                url = escape(item["url"] or "")
                title_markup = f'{index}. <link href="{url}" color="#1d4ed8">{title}</link>' if url else f"{index}. {title}"
                summary = escape(item["summary"] or "要約なし")
                meta = " / ".join(filter(None, [item["source_name"], item["published_at"]]))
                article = [
                    Paragraph(title_markup, article_title_style),
                    Paragraph(escape(meta), meta_style),
                ]
                trend = item.get("trend")
                if trend:
                    article.extend([
                        Paragraph(
                            f'最終更新: <b>{escape(str(trend.get("last_updated_at", "未取得")))}</b>',
                            meta_style,
                        ),
                        Paragraph(
                            "過去7日間の検索関心度: "
                            f'最新値 <b>{escape(str(trend.get("latest_value", "-")))}</b> / '
                            f'平均値 <b>{escape(str(trend.get("average_value", "-")))}</b> / '
                            f'最高値 <b>{escape(str(trend.get("peak_value", "-")))}</b>',
                            body_style,
                        ),
                        trend_chart(trend),
                        Paragraph(
                            f'横軸: 過去7日間（{escape(str(trend.get("interval_label", "")))}、'
                            f'{escape(str(trend.get("point_count", 0)))}点） / 縦軸: 検索関心度（0〜100）',
                            meta_style,
                        ),
                    ])
                    rankings = trend.get("rankings") or []
                    if rankings:
                        ranking_text = "<br/>".join(
                            f'{ranking.get("rank", rank)}位 {escape(str(ranking.get("name", "地域名不明")))}'
                            f'（{escape(str(ranking.get("value", 0)))}）'
                            for rank, ranking in enumerate(rankings[:5], start=1)
                        )
                        article.append(Paragraph(
                            f'<b>地域別インタレスト 上位5件（{escape(str(trend.get("region", "")))}）</b><br/>{ranking_text}',
                            body_style,
                        ))
                    else:
                        article.append(Paragraph("地域別インタレストは取得できませんでした。", body_style))
                else:
                    article.append(Paragraph(summary, body_style))
                article.append(Spacer(1, 1.2 * mm))
                story.append(KeepTogether(article))

    doc.build(story)
    return buffer.getvalue()
