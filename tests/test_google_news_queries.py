import unittest

from crawlers.google_news_crawler import build_query_groups


class GoogleNewsQueryTests(unittest.TestCase):
    def test_physical_ai_queries_include_vla_and_vtla_models(self):
        groups = dict(build_query_groups())
        physical_ai_queries = groups["Google News / Physical AI"]

        self.assertTrue(any("VLA model" in query for query in physical_ai_queries))
        self.assertTrue(any("VTLA model" in query for query in physical_ai_queries))
        self.assertFalse(any("VLTA model" in query for query in physical_ai_queries))


if __name__ == "__main__":
    unittest.main()
