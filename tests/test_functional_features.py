# SPDX-License-Identifier: GPL-3.0-only
"""Functional regressions for user corrections and read-only content checks."""
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from boothlib.api import Api
from boothlib.config import Config
from boothlib.curation import OverrideStore, product_id
from boothlib.duplicates import DuplicateVerifier
from boothlib.pipeline import Pipeline


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="boothnest-features-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "中文 downloads"
        self.root.mkdir()
        self.cfg = Config(home=self.base / "home").load()
        self.cfg.root = str(self.root)
        self.cfg.set("offline", True)
        self.api = Api(self.cfg)
        (self.root / "Original-1234567.txt").write_bytes(b"demo")
        (self.root / "Unrecognized.txt").write_bytes(b"other")
        self.api.client._write_json(self.cfg.item_file("1234567"), {"id": 1234567, "name": "Original"})
        self.api.client._write_json(self.cfg.item_file("7654321"), {"id": 7654321, "name": "Corrected"})
        self.api.dataset = Pipeline(self.cfg, self.api.client).run(offline=True)

    def item(self, folder="Original-1234567.txt"):
        return next(x for x in self.api.dataset["items"] if x["folder"] == folder)

    def check(self, files):
        root = self.base / "hash-files"
        root.mkdir(exist_ok=True)
        for name, value in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        dataset = {"root": str(root), "items": [{"folder": p.name} for p in root.iterdir()]}
        return root, dataset, DuplicateVerifier().run(dataset)

    def wait_task(self):
        deadline = time.monotonic() + 10
        while self.api.busy and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.api.busy)
        return self.api.task["result"]

    def test_binding_survives_full_refresh_restart_and_cache_clear(self):
        result = self.api.set_item_override(["Original-1234567.txt"], "bind", "https://demo.booth.pm/items/7654321")
        self.assertTrue(result["ok"])
        self.assertEqual(self.item()["product_id"], "7654321")
        self.api.clear_cache()
        self.api.dataset = Pipeline(self.cfg, self.api.client).run(offline=True, use_cache=False)
        self.assertEqual(self.item()["product_id"], "7654321")
        other = Api(self.cfg)
        self.assertTrue(other.load_dataset()["ok"])
        self.assertEqual(other.dataset["items"], self.api.dataset["items"])

    def test_unmatch_ignore_and_reset_have_distinct_meanings(self):
        folder = "Original-1234567.txt"
        self.api.set_item_override([folder], "unmatch")
        self.assertIsNone(self.item()["product_id"])
        self.assertEqual(len(self.api.get_unidentified()["rows"]), 2)
        self.api.set_item_override([folder], "ignore")
        self.assertTrue(self.item()["ignored"])
        summary = self.api.get_summary()["summary"]
        self.assertEqual((summary["totItems"], summary["ignored"], summary["unidentified"]), (2, 1, 1))
        self.assertEqual(summary["totBytes"], 9)
        self.api.set_item_override([folder], "reset")
        self.assertEqual(self.item()["product_id"], "1234567")
        self.assertNotIn("manual", self.item())
        self.assertNotIn(folder, OverrideStore(self.cfg).rules(str(self.root)))

    def test_batch_binding_reaggregates_products_and_preserves_file_bytes(self):
        folders = [x["folder"] for x in self.api.dataset["items"]]
        original = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertTrue(self.api.set_item_override(folders, "bind", "7654321")["ok"])
        self.assertEqual(self.api.dataset["totProds"], 1)
        product = self.api.dataset["products"][0]
        self.assertEqual((product["title"], product["local_bytes"], product["local_files"]), ("Corrected", 9, 2))
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, original)

    def test_rules_are_scoped_to_inventory_root_not_current_config(self):
        self.cfg.root = str(self.base / "another-root")
        self.assertTrue(self.api.set_item_override(["Original-1234567.txt"], "bind", "7654321")["ok"])
        self.assertFalse(OverrideStore(self.cfg).rules(self.cfg.root))
        self.assertTrue(OverrideStore(self.cfg).rules(str(self.root)))

    def test_invalid_inputs_and_busy_state_do_not_mutate(self):
        before = copy.deepcopy(self.api.dataset)
        for folders, action, target in [([], "bind", "123"), (["../other"], "ignore", ""),
                                         (["Original-1234567.txt"], "unknown", ""),
                                         (["Original-1234567.txt"], "bind", "https://evil.test/items/123")]:
            self.assertFalse(self.api.set_item_override(folders, action, target)["ok"])
        self.api.task["busy"] = True
        self.assertFalse(self.api.set_item_override(["Original-1234567.txt"], "ignore")["ok"])
        self.assertEqual(self.api.dataset, before)

    def test_product_link_validation_and_legacy_short_id(self):
        for value in ("123456", "https://booth.pm/ja/items/123456/?ref=test", "https://demo.booth.pm/items/123456"):
            self.assertEqual(product_id(value), "123456")
        for value in ("0", "../123", "http://booth.pm/items/123", "https://booth.pm.evil.test/items/123",
                      "https://user@booth.pm/items/123", "https://booth.pm:444/items/123", "https://booth.pm/items/123/extra"):
            with self.assertRaises(ValueError, msg=value):
                product_id(value)

    def test_corrupt_rule_file_is_not_overwritten(self):
        store = OverrideStore(self.cfg)
        store.path.write_text("{broken", encoding="utf-8")
        self.assertFalse(self.api.set_item_override(["Unrecognized.txt"], "ignore")["ok"])
        self.assertEqual(store.path.read_text(), "{broken")
        with self.assertRaises(ValueError):
            Pipeline(self.cfg, self.api.client).run(offline=True)

    def test_failed_rule_write_preserves_current_dataset(self):
        before = copy.deepcopy(self.api.dataset)
        with patch("boothlib.curation.os.replace", side_effect=OSError("synthetic failure")):
            self.assertFalse(self.api.set_item_override(["Unrecognized.txt"], "ignore")["ok"])
        self.assertEqual(self.api.dataset, before)
        self.assertFalse(list(self.cfg.data_dir.glob("*.tmp")))

    def test_saved_rules_recover_if_derived_dataset_write_fails(self):
        with patch("boothlib.api.atomic_json", side_effect=OSError("synthetic failure")):
            result = self.api.set_item_override(["Original-1234567.txt"], "bind", "7654321")
        self.assertTrue(result["ok"] and result["warning"])
        restarted = Api(self.cfg)
        restarted.load_dataset()
        item = next(x for x in restarted.dataset["items"] if x["folder"] == "Original-1234567.txt")
        self.assertEqual(item["product_id"], "7654321")

    def test_correction_keeps_existing_metadata_after_cache_clear(self):
        self.api.clear_cache()
        self.api.set_item_override(["Unrecognized.txt"], "ignore")
        self.assertEqual(self.api.dataset["products"][0]["title"], "Original")
        detail = self.api.get_product_detail("1234567")
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["detail"]["local_folders"], ["Original-1234567.txt"])

    def test_sha256_distinguishes_same_size_and_finds_nested_identical_files(self):
        root, dataset, report = self.check({"a.zip": b"identical", "nested/b.zip": b"identical",
                                             "c.zip": b"different", "unique.zip": b"length"})
        self.assertEqual(report["files"], 4)
        self.assertEqual(report["candidates"], 3)
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(report["groups"][0]["paths"], ["a.zip", "nested/b.zip"])
        self.assertEqual(report["groups"][0]["sha256"], hashlib.sha256(b"identical").hexdigest())
        self.assertEqual(report["extra_bytes"], 9)
        self.assertEqual((root / "a.zip").read_bytes(), b"identical")

    def test_hardlinks_do_not_inflate_extra_logical_size(self):
        root, dataset, _ = self.check({"a": b"data"})
        os.link(root / "a", root / "alias")
        dataset["items"].append({"folder": "alias"})
        report = DuplicateVerifier().run(dataset)
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(report["extra_bytes"], 0)
        self.assertEqual(report["groups"][0]["hardlink_paths"], 1)

    def test_missing_or_outside_items_are_reported_without_reading_them(self):
        root, dataset, _ = self.check({"a": b"data"})
        (self.base / "outside").write_bytes(b"data")
        dataset["items"] += [{"folder": "../outside"}, {"folder": "missing"}]
        report = DuplicateVerifier().run(dataset)
        self.assertEqual(report["files"], 1)
        self.assertEqual(report["warning_count"], 2)
        self.assertEqual(report["groups"], [])

    def test_symbolic_links_are_skipped(self):
        root, dataset, _ = self.check({"a": b"data", "nested/b": b"data"})
        try:
            os.symlink(root / "nested", root / "link", target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("Symlink privilege not available")
            result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/c", "mklink", "/J",
                                     str(root / "link"), str(root / "nested")], capture_output=True)
            if result.returncode:
                self.skipTest("Neither symlinks nor directory junctions available")
        dataset["items"].append({"folder": "link/b"})
        report = DuplicateVerifier().run(dataset)
        self.assertEqual(report["files"], 2)
        self.assertTrue(report["warning_count"])

    def test_file_changed_during_check_is_not_reported_identical(self):
        root, dataset, _ = self.check({"a": b"same", "b": b"same"})
        changed = False
        def progress(phase, done, total):
            nonlocal changed
            if phase.startswith("读取") and not changed:
                changed = True
                (root / "a").write_bytes(b"changed")
        report = DuplicateVerifier().run(dataset, progress=progress)
        self.assertFalse(report["groups"])
        self.assertTrue(report["warning_count"])

    def test_cancelled_check_preserves_previous_report(self):
        before = copy.deepcopy(self.api.dataset)
        before["duplicate_check"] = {"checked_at": "previous"}
        self.api.dataset = before
        with patch.object(DuplicateVerifier, "run", side_effect=InterruptedError):
            self.assertTrue(self.api.check_duplicate_files()["ok"])
            self.assertTrue(self.wait_task()["cancelled"])
        self.assertEqual(self.api.dataset, before)

    def test_check_task_export_and_refresh_invalidation(self):
        (self.root / "Unrecognized.txt").write_bytes(b"demo")
        self.assertTrue(self.api.check_duplicate_files()["ok"])
        self.assertTrue(self.wait_task()["ok"])
        self.assertEqual(self.api.get_duplicate_check()["report"]["extra_bytes"], 4)
        export = self.api.export_duplicate_check()
        with (Path(export["dir"]) / export["files"][0]).open(encoding="utf-8-sig", newline="") as f:
            self.assertEqual(len(list(csv.reader(f))), 3)
        self.api.set_item_override(["Unrecognized.txt"], "ignore")
        self.assertIsNotNone(self.api.get_duplicate_check()["report"])
        self.api.dataset = Pipeline(self.cfg, self.api.client).run(offline=True)
        self.assertIsNone(self.api.get_duplicate_check()["report"])
        self.assertFalse(self.api.reveal_verified_file("../outside")["ok"])


if __name__ == "__main__":
    unittest.main()
