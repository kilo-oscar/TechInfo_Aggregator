from crawlers.thinktank_common import ThinkTankCrawlerConfig, run_thinktank_crawler


CONFIG = ThinkTankCrawlerConfig(
    source_name="日本総合研究所",
    seed_urls=[
        "https://www.jri.co.jp/page.jsp?id=101417",
        "https://www.jri.co.jp/page.jsp?id=103194",
        "https://www.jri.co.jp/page.jsp?id=101419",
    ],
    allowed_domains=["jri.co.jp"],
    allowed_path_keywords=["page.jsp", "/file/", "/publication/"],
    extra_keywords=[
        "physical ai",
        "フィジカルai",
        "生成ai",
        "ロボット",
        "humanoid",
        "ヒューマノイド",
        "robot",
        "robotics",
        "embodied",
        "自動運転",
        "省人化",
        "製造業",
    ],
)


def main() -> None:
    run_thinktank_crawler(CONFIG)


if __name__ == "__main__":
    main()
