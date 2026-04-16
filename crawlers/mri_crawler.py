from crawlers.thinktank_common import ThinkTankCrawlerConfig, run_thinktank_crawler


CONFIG = ThinkTankCrawlerConfig(
    source_name="三菱総合研究所",
    seed_urls=[
        "https://www.mri.co.jp/knowledge/",
        "https://www.mri.co.jp/knowledge/opinion/2026/index.html",
        "https://www.mri.co.jp/knowledge/opinion/2025/index.html",
        "https://www.mri.co.jp/knowledge/insight/index.html",
    ],
    allowed_domains=["mri.co.jp"],
    allowed_path_keywords=["/knowledge/", "/newsrelease/"],
    extra_keywords=[
        "physical ai",
        "フィジカルai",
        "ai agent",
        "agent ai",
        "agentic ai",
        "aiエージェント",
        "ai エージェント",
        "エージェントai",
        "エージェント ai",
        "aiロボティクス",
        "ai・ロボティクス",
        "embodied ai",
        "robot",
        "robotics",
        "ロボット",
        "humanoid",
        "ヒューマノイド",
        "自動化",
        "工場",
        "製造",
    ],
)


def main() -> None:
    run_thinktank_crawler(CONFIG)


if __name__ == "__main__":
    main()
