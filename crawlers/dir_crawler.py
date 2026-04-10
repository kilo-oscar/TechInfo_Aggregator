from crawlers.thinktank_common import ThinkTankCrawlerConfig, run_thinktank_crawler


CONFIG = ThinkTankCrawlerConfig(
    source_name="大和総研",
    seed_urls=[
        "https://www.dir.co.jp/report/",
        "https://www.dir.co.jp/report/pick-up/index.html",
        "https://www.dir.co.jp/report/pick-up/pu-ai/index.html",
    ],
    allowed_domains=["dir.co.jp"],
    allowed_path_keywords=["/report/", "/column/", "/pick-up/"],
    extra_keywords=[
        "physical ai",
        "フィジカルai",
        "ai agent",
        "aiエージェント",
        "ロボット",
        "robot",
        "robotics",
        "humanoid",
        "ヒューマノイド",
        "人型ロボット",
        "自律",
        "産業用ロボット",
    ],
)


def main() -> None:
    run_thinktank_crawler(CONFIG)


if __name__ == "__main__":
    main()
