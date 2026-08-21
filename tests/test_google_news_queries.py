import unittest

from crawlers.google_news_crawler import build_query_groups


class GoogleNewsQueryTests(unittest.TestCase):
    def test_physical_ai_queries_include_vla_and_vtla_models(self):
        groups = dict(build_query_groups())
        physical_ai_queries = groups["Google News / Physical AI"]

        self.assertTrue(any("VLA model" in query for query in physical_ai_queries))
        self.assertTrue(any("VTLA model" in query for query in physical_ai_queries))
        self.assertFalse(any("VLTA model" in query for query in physical_ai_queries))

    def test_robotics_sensing_queries_cover_all_requested_modalities(self):
        groups = dict(build_query_groups())
        sensing_queries = " ".join(groups["Google News / Robotics Sensing"])

        for term in ("視覚センシング", "聴覚センシング", "触覚センシング", "力触覚"):
            self.assertIn(term, sensing_queries)

    def test_robotics_component_queries_cover_requested_components(self):
        groups = dict(build_query_groups())
        component_queries = " ".join(groups["Google News / Robotics Components"])

        for term in ("センサー", "アクチュエータ", "減速機", "ダイレクトドライブモータ"):
            self.assertIn(term, component_queries)


if __name__ == "__main__":
    unittest.main()
