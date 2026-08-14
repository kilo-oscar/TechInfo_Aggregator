import unittest

from crawlers.google_news_filters import should_keep_japanese_robotics_media_item


class JapaneseRoboticsMediaFilterTests(unittest.TestCase):
    def test_keeps_robotics_pr_times_item(self):
        self.assertTrue(should_keep_japanese_robotics_media_item(
            query='site:prtimes.jp "ロボット"',
            publisher="PR TIMES",
            title="倉庫ロボットの新サービスを開始",
            summary="物流現場向けに提供します。",
        ))

    def test_rejects_unrelated_pr_times_item_even_if_google_news_returns_it(self):
        self.assertFalse(should_keep_japanese_robotics_media_item(
            query='site:prtimes.jp "ロボット"',
            publisher="PR TIMES",
            title="秋の新作スイーツを発売",
            summary="限定キャンペーンのお知らせです。",
        ))

    def test_rejects_wrong_publisher_for_pr_times_query(self):
        self.assertFalse(should_keep_japanese_robotics_media_item(
            query='site:prtimes.jp "フィジカルAI"',
            publisher="別のニュースサイト",
            title="フィジカルAIを活用したロボット",
            summary="製造業で実証。",
        ))

    def test_keeps_physical_ai_au_web_portal_item(self):
        self.assertTrue(should_keep_japanese_robotics_media_item(
            query='site:article.auone.jp "フィジカルAI"',
            publisher="au Webポータル",
            title="フィジカルAIで変わるロボット開発",
            summary="最新動向を解説。",
        ))

    def test_rejects_unrelated_au_web_portal_item(self):
        self.assertFalse(should_keep_japanese_robotics_media_item(
            query='site:article.auone.jp "フィジカルAI"',
            publisher="au Webポータル",
            title="週末の天気予報",
            summary="各地で晴れの見込みです。",
        ))

    def test_rejects_robotics_only_au_item_for_physical_ai_query(self):
        self.assertFalse(should_keep_japanese_robotics_media_item(
            query='site:article.auone.jp "フィジカルAI"',
            publisher="au Webポータル",
            title="家庭用ロボットの新製品",
            summary="便利な新機能を紹介します。",
        ))


if __name__ == "__main__":
    unittest.main()
