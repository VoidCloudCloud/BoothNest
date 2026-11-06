"""Automatic name discovery regressions; no network or private library needed."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from boothlib import matching as M
from boothlib.booth_client import BoothClient
from boothlib.config import Config
from boothlib.pipeline import Pipeline


class AutomaticIdentificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = Config(home=Path(self.temp.name)).load()
        self.cfg.ensure_dirs()
        self.cfg.root = str(Path(self.temp.name) / "downloads")
        self.client = BoothClient(self.cfg)
        self.pipe = Pipeline(self.cfg, self.client)

    def test_dotted_directory_discovers_full_title_without_manual_rule(self):
        name = "【17人适配】LV.16 Yoi_Koi"
        product = {"id": 8562969, "name": "【19アバター対応】 𝐋𝐕.𝟏𝟔 Yoi_Koi 🎐",
                   "shop": {"name": "LookVook", "subdomain": "lookvook"},
                   "category": {"name": "3D衣装"}}
        queries = []

        def search(query, **kwargs):
            queries.append(query)
            if set(query.casefold().split()) == {"yoi", "koi"}:
                return [{"id": "8562969", "name": "【19アバター対応】 𝐋𝐕.𝟏𝟔 Yoi…",
                         "shop": "lookvook"}]
            return []

        item = {"folder": name, "name": name, "ids_strong": [],
                "size": 100, "n_files": 15, "is_dir": True}
        with patch.object(self.client, "search_cards", side_effect=search), \
                patch.object(self.client, "get_item", return_value=product):
            resolved = self.pipe._resolve_no_id([item], {})
            dataset = self.pipe._build([item], {}, resolved)
        self.assertEqual(dataset["items"][0]["product_id"], "8562969")
        self.assertEqual(dataset["products"][0]["title"], product["name"])
        self.assertNotIn("manual", dataset["items"][0])
        self.assertTrue(any(set(q.casefold().split()) == {"yoi", "koi"} for q in queries))

    def test_styled_short_title_matches_cached_product(self):
        name = "【8人适配】Wing Veil"
        result = self.pipe._match_cluster(M.tokens(name), M.raw_chunks(name), [],
                    [("8680416", "✨8アバター対応✨ଘ 𝑾𝒊𝒏𝒈 𝑽𝒆𝒊𝒍", "balgu", "balgu")],
                    offline=True)
        self.assertEqual(result["id"], "8680416")

    def test_same_short_title_from_two_shops_is_not_guessed(self):
        name = "Wing Veil"
        pool = [("8680416", "Wing Veil", "balgu", "balgu"),
                ("1234567", "Wing Veil", "another", "another")]
        self.assertIsNone(self.pipe._match_cluster(M.tokens(name), M.raw_chunks(name),
                                                 [], pool, offline=True))
        result = self.pipe._match_cluster(M.tokens(name), M.raw_chunks(name),
                                         ["balgu"], pool, offline=True)
        self.assertEqual(result["id"], "8680416")

    def test_short_name_requires_full_metadata(self):
        name = "Sexy Bomb"
        with patch.object(self.client, "search_cards", return_value=[
                {"id": "8916133", "name": "Sexy Bomb 【19アバター対応】", "shop": "overay"}]), \
                patch.object(self.client, "get_item", return_value=None):
            result = self.pipe._match_cluster(M.tokens(name), M.raw_chunks(name), [], [])
        self.assertIsNone(result)

    def test_query_budget_is_not_spent_on_case_duplicates(self):
        name = "_Ene_Collection__Devil_Cadet_Materials_v1.0.zip"
        queries = M.search_queries(M.tokens(name), M.raw_chunks(name))
        self.assertEqual(len(queries), len({q.casefold() for q in queries}))
        self.assertTrue(any(set(q.casefold().split()) == {"devil", "cadet"} for q in queries))

    def test_dotted_directories_keep_product_words(self):
        self.assertEqual(M.tokens("【17人适配】LV.16 Yoi_Koi"), ["yoi", "koi"])
        self.assertEqual(M.tokens("__00.VECTORIAL_STRUCT_PSD"), ["vectorial", "struct"])
        self.assertEqual(M.tokens("Yoi_Koi_v1.0.ZIP"), ["yoi", "koi"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
