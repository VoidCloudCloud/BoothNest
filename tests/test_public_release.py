# SPDX-License-Identifier: GPL-3.0-only
"""Portable release regressions. Synthetic data only; no BOOTH/NAS requests."""
import csv
from contextlib import closing
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from boothlib.api import Api
from boothlib.booth_client import BoothClient, BoothError
from boothlib.config import Config
from boothlib.instance import InstanceLock
from boothlib.pipeline import Pipeline
from boothlib.scanner import scan, probe_items, _probe_unitypackage
from boothlib.server import make_server


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="boothnest-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "downloads"
        self.root.mkdir()
        self.cfg = Config(home=self.base / "home").load()
        self.cfg.ensure_dirs()
        self.cfg.root = str(self.root)
        self.api = Api(self.cfg)
        self.meta = {"id": 1234567, "name": "Synthetic Product", "shop": {"name": "Demo"}}
        self.api.dataset = {
            "root": str(self.root), "schema": 2,
            "items": [{"folder": "demo.zip", "name": "demo.zip", "product_id": "1234567",
                       "size": 3, "n_files": 1}],
            "products": [{"id": "1234567", "title": "=1+2", "local_bytes": 3,
                          "local_folders": ["demo.zip"]}],
            "totItems": 1, "totProds": 1, "totBytes": 3, "identified": 1,
        }

    def server(self):
        srv, url = make_server(self.api, ROOT / "boothlib")
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv, url

    def request(self, url, method="GET", data=None, headers=None):
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(req, timeout=5)
        except urllib.error.HTTPError as e:
            response = e
        with response:
            return response.status, response.read(), response.headers

    def post(self, srv, url, method, args=None, **headers):
        h = {"Content-Type": "application/json", "X-BoothNest-Token": srv.session_token}
        h.update(headers)
        return self.request(url + "api/" + method, "POST",
                            json.dumps({"args": args or []}).encode(), h)

    def test_first_run_is_empty(self):
        cfg = Config(home=self.base / "new").load()
        api = Api(cfg)
        self.assertFalse(cfg.root)
        self.assertFalse(cfg.data("dataset.json").exists())
        self.assertFalse(api.get_state()["root_ok"])
        self.assertFalse(api.refresh()["ok"])

    def test_existing_dataset_untouched_on_load(self):
        self.cfg.data("dataset.json").write_text('{"private": true}', encoding="utf-8")
        before = self.cfg.data("dataset.json").read_bytes()
        self.cfg.load()
        self.assertEqual(before, self.cfg.data("dataset.json").read_bytes())

    def test_session_token_and_security_headers(self):
        srv, url = self.server()
        status, body, headers = self.request(url)
        self.assertEqual(status, 200)
        self.assertIn(srv.session_token.encode(), body)
        self.assertNotIn(b"__BOOTH_SESSION_TOKEN__", body)
        self.assertIn("nonce-" + srv.session_token, headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")

    def test_unauthenticated_post_rejected(self):
        _, url = self.server()
        self.assertEqual(self.request(url + "api/clear_cache", "POST", b'{"args":[]}',
                                     {"Content-Type": "application/json"})[0], 403)

    def test_get_cannot_mutate(self):
        _, url = self.server()
        sentinel = self.cfg.item_file("1234567")
        sentinel.write_text("{}")
        self.assertEqual(self.request(url + "api/clear_cache")[0], 405)
        self.assertTrue(sentinel.exists())

    def test_foreign_origin_and_host_rejected(self):
        srv, url = self.server()
        self.assertEqual(self.post(srv, url, "app_info", Origin="https://untrusted.invalid")[0], 403)
        self.assertEqual(self.request(url, headers={"Host": "untrusted.invalid"})[0], 403)

    def test_authenticated_post(self):
        srv, url = self.server()
        status, body, _ = self.post(srv, url, "get_products")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["rows"]), 1)

    def test_api_body_validation(self):
        srv, url = self.server()
        h = {"Content-Type": "application/json", "X-BoothNest-Token": srv.session_token}
        self.assertEqual(self.request(url + "api/poll", "POST", b'{', h)[0], 400)
        self.assertEqual(self.request(url + "api/poll", "POST", b'{"args":{}}', h)[0], 400)
        self.assertEqual(self.request(url + "api/poll", "POST", b' ' * (1024 * 1024 + 1), h)[0], 413)

    def test_python_sources_not_served(self):
        _, url = self.server()
        self.assertEqual(self.request(url + "config.py")[0], 404)

    def test_huge_declared_body_is_rejected_without_waiting_for_upload(self):
        srv, _ = self.server()
        with closing(http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=3)) as client:
            client.request("POST", "/api/poll", headers={
                "Content-Type": "application/json",
                "X-BoothNest-Token": srv.session_token,
                "Content-Length": str(1024 ** 4),
            })
            response = client.getresponse()
            self.assertEqual(response.status, 413)
            self.assertIn("Invalid body size", json.loads(response.read())["error"])

    def test_launch_file_reveals_instead_of_executes(self):
        (self.root / "demo.zip").write_bytes(b"abc")
        with patch("boothlib.api.os.startfile") as start, patch("boothlib.api.subprocess.Popen") as popen:
            self.assertTrue(self.api.reveal_item("demo.zip")["ok"])
            start.assert_not_called()
            self.assertIn("/select,", popen.call_args.args[0])

    def test_reveal_rejects_arbitrary_and_escaping_paths(self):
        self.assertFalse(self.api.reveal_item(str(self.base))["ok"])
        self.api.dataset["items"].append({"folder": "../home"})
        self.assertFalse(self.api.reveal_item("../home")["ok"])

    def test_reveal_uses_dataset_root(self):
        (self.root / "demo.zip").write_bytes(b"abc")
        self.cfg.root = str(self.base / "different")
        with patch("boothlib.api.subprocess.Popen") as popen:
            self.assertTrue(self.api.reveal_item("demo.zip")["ok"])
            self.assertTrue(Path(popen.call_args.args[0][-1]).samefile(self.root / "demo.zip"))

    def test_external_open_is_restricted(self):
        self.assertFalse(self.api.open_path(str(self.base))["ok"])
        self.assertFalse(self.api.open_url("https://untrusted.invalid")["ok"])
        self.assertFalse(self.api.open_url("file:///C:/test.exe")["ok"])
        with patch("boothlib.api.os.startfile") as start:
            self.assertTrue(self.api.open_url("https://example.booth.pm/items/1234567")["ok"])
            start.assert_called_once()

    def test_preferences_survive_new_api_and_port(self):
        self.assertTrue(self.api.set_preferences({"bs_view": "table", "offline": "true"})["ok"])
        api2 = Api(Config(home=self.cfg.home).load())
        self.assertEqual(api2.get_state()["preferences"]["bs_view"], "table")
        self.assertTrue(api2.get_state()["offline"])

    def test_busy_root_change_rejected(self):
        self.api.task["busy"] = True
        self.assertFalse(self.api.set_root(str(self.base))["ok"])

    def test_directory_picker_bridge(self):
        with patch("boothlib.native_dialogs.pick_folder", return_value=str(self.root)):
            self.assertTrue(self.api.pick_root()["ok"])

    def test_scan_includes_deep_files(self):
        target = self.root / "one" / "two" / "three" / "four" / "five" / "six.bin"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"abcdef")
        result = scan(str(self.root))
        self.assertEqual(sum(i["size"] for i in result["items"]), 6)
        self.assertEqual(result["warnings"], [])

    def test_two_archives_are_separate_from_category_or_parent_root(self):
        category = self.root / "化身"
        category.mkdir()
        files = {"Alpha-1234567.zip": b"a" * 547, "Beta-7654321.zip": b"b" * 142}
        for name, contents in files.items():
            (category / name).write_bytes(contents)
        direct = scan(str(category))["items"]
        parent = scan(str(self.root))
        expected = {"化身/" + item["folder"]: (item["size"], item["ids_strong"])
                    for item in direct}
        self.assertEqual({item["folder"]: (item["size"], item["ids_strong"])
                          for item in parent["items"]}, expected)
        self.assertEqual(parent["containers"], {"化身": 2})
        self.assertEqual({name: (category / name).read_bytes() for name in files}, files)

    def test_two_product_directories_are_not_merged(self):
        for name, size in [("1234567 Alpha", 21), ("7654321 Beta", 88)]:
            folder = self.root / "饰品" / name
            folder.mkdir(parents=True)
            (folder / "asset.unitypackage").write_bytes(b"x" * size)
        items = scan(str(self.root))["items"]
        self.assertEqual({item["folder"]: item["size"] for item in items},
                         {"饰品/1234567 Alpha": 21, "饰品/7654321 Beta": 88})
        self.assertTrue(all(item["is_dir"] for item in items))
        self.assertEqual(sum(item["n_files"] for item in items), 2)

    def test_two_product_container_expands_through_deeper_ancestors(self):
        category = self.root / "整理完" / "素材" / "化身"
        category.mkdir(parents=True)
        for name in ["1234567.zip", "7654321.zip"]:
            (category / name).write_bytes(b"abc")
        items = scan(str(self.root))["items"]
        self.assertEqual({item["folder"] for item in items},
                         {"整理完/素材/化身/1234567.zip", "整理完/素材/化身/7654321.zip"})
        self.assertEqual(sum(item["size"] for item in items), 6)

    def test_same_product_id_across_files_stays_one_download(self):
        package = self.root / "Product"
        package.mkdir()
        for name in ["Alpha-1234567.zip", "Alpha-1234567.fbx", "Alpha-1234567.txt"]:
            (package / name).write_bytes(b"abc")
        result = scan(str(self.root))
        self.assertEqual(result["containers"], {})
        self.assertEqual([(item["folder"], item["size"], item["n_files"])
                          for item in result["items"]], [("Product", 9, 3)])

    def test_single_child_with_multiple_ids_does_not_split_package(self):
        package = self.root / "Product"
        package.mkdir()
        (package / "Alpha-1234567-for-7654321-2345678.zip").write_bytes(b"abc")
        result = scan(str(self.root))
        self.assertEqual(result["containers"], {})
        self.assertEqual([item["folder"] for item in result["items"]], ["Product"])

    def test_shared_product_id_with_avatar_references_stays_one_download(self):
        package = self.root / "Product"
        package.mkdir()
        for name in ["1234567-main.zip", "1234567-for-7654321.zip", "1234567-for-2345678.zip"]:
            (package / name).write_bytes(b"abc")
        result = scan(str(self.root))
        self.assertEqual(result["containers"], {})
        self.assertEqual([(item["folder"], item["size"]) for item in result["items"]],
                         [("Product", 9)])

    def test_three_product_container_preserves_all_bytes_and_loose_files(self):
        category = self.root / "Category"
        category.mkdir()
        for name in ["1234567.zip", "7654321.zip", "2345678.zip", "readme.txt"]:
            (category / name).write_bytes(b"abc")
        result = scan(str(self.root))
        self.assertEqual(result["containers"], {"Category": 3})
        self.assertEqual(len(result["items"]), 4)
        self.assertEqual(sum(item["size"] for item in result["items"]), 12)
        self.assertEqual(sum(item["n_files"] for item in result["items"]), 4)

    def test_nested_products_keep_separate_ids_and_sizes_through_pipeline(self):
        category = self.root / "化身"
        category.mkdir()
        for product_id, title, size in [("1234567", "Alpha", 547), ("7654321", "Beta", 142)]:
            with zipfile.ZipFile(category / (product_id + ".zip"), "w") as archive:
                archive.writestr("readme.txt", b"x" * size)
            self.api.client._write_json(self.cfg.item_file(product_id),
                                        {"id": int(product_id), "name": title})
        expected = {str(path.stem): path.stat().st_size for path in category.iterdir()}
        before = {path.name: path.read_bytes() for path in category.iterdir()}
        pipe = Pipeline(self.cfg, self.api.client)
        dataset = pipe.run(offline=True)
        self.assertEqual(dataset["totProds"], 2)
        self.assertEqual({product["id"]: product["local_bytes"] for product in dataset["products"]},
                         expected)
        self.assertEqual({item["product_id"] for item in dataset["items"]}, set(expected))
        self.assertEqual(dataset["totBytes"], sum(expected.values()))
        self.assertEqual({path.name: path.read_bytes() for path in category.iterdir()}, before)
        # Incremental refresh must rebuild the units instead of retaining the old merged category.
        again = pipe.run(offline=True, use_cache=True)
        self.assertEqual(again["products"], dataset["products"])

    def test_scan_reports_permission_errors(self):
        bad = self.root / "denied"
        bad.mkdir()
        original = os.listdir
        def listing(path):
            if Path(path) == bad:
                raise PermissionError("synthetic denial")
            return original(path)
        with patch("boothlib.scanner.os.listdir", side_effect=listing):
            self.assertTrue(scan(str(self.root))["warnings"])

    def test_scan_cancel(self):
        with self.assertRaises(InterruptedError):
            scan(str(self.root), cancel=lambda: True)

    def test_cancel_does_not_commit_partial_results(self):
        (self.root / "DistinctAlpha.zip").write_bytes(b"abc")
        (self.root / "DistinctBeta.zip").write_bytes(b"abc")
        old = b'{"previous":true}'
        self.cfg.data("dataset.json").write_bytes(old)
        pipe = Pipeline(self.cfg, self.api.client)
        def match(*args, **kwargs):
            pipe.stop()
            return None
        with patch.object(pipe, "_match_cluster", side_effect=match):
            with self.assertRaises(InterruptedError):
                pipe.run(offline=True)
        self.assertEqual(self.cfg.data("dataset.json").read_bytes(), old)

    def test_probe_cache_tracks_same_size_changes(self):
        folder = self.root / "package"
        folder.mkdir()
        path = folder / "archive.zip"
        def archive(name):
            with zipfile.ZipFile(path, "w") as z:
                z.writestr(name, "same")
        archive("alpha.txt")
        items = scan(str(self.root))["items"]
        cache = {}
        first = probe_items(str(self.root), items, cache)
        old_mtime = path.stat().st_mtime_ns
        archive("bravo.txt")
        os.utime(path, ns=(old_mtime + 1000000000, old_mtime + 1000000000))
        second = probe_items(str(self.root), items, cache)
        self.assertNotEqual(first["package"][0]["paths"], second["package"][0]["paths"])

    def test_temporary_network_failure_not_cached_as_404(self):
        pipe = Pipeline(self.cfg, self.api.client)
        with patch.object(self.api.client, "_get", side_effect=BoothError("offline")):
            self.assertIsNone(pipe._verify_get("1234567"))
        self.assertFalse((self.cfg.cache_dir / "verify" / "1234567.json").exists())

    def test_verified_candidate_promoted_to_disk(self):
        with patch.object(self.api.client, "_get", return_value=json.dumps(self.meta)):
            self.assertIsNotNone(self.api.client.get_item("1234567", write_cache=False))
            self.assertFalse(self.cfg.item_file("1234567").exists())
            self.api.client.get_item("1234567", write_cache=True)
            self.assertTrue(self.cfg.item_file("1234567").exists())

    def test_force_refresh_updates_metadata(self):
        self.api.client._write_json(self.cfg.item_file("1234567"), self.meta)
        updated = dict(self.meta, name="Updated")
        with patch.object(self.api.client, "_get", return_value=json.dumps(updated)) as get:
            self.api.client.fetch_many(["1234567"], force=True)
        get.assert_called_once()
        self.assertEqual(json.loads(self.cfg.item_file("1234567").read_text())["name"], "Updated")

    def test_offline_does_not_request_metadata_or_images(self):
        self.cfg.set("offline", True)
        with patch.object(self.api.client, "_get") as get, patch("urllib.request.build_opener") as opener:
            self.assertIsNone(self.api.client.get_item("1234567"))
            self.assertIsNone(self.api.client.fetch_image("https://booth.pximg.net/test.jpg", "test.jpg"))
            self.assertEqual(self.api.client.search_cards("demo"), [])
            get.assert_not_called()
            opener.assert_not_called()

    def test_invalid_product_id_cannot_escape_cache(self):
        with self.assertRaises(ValueError):
            self.api.client.get_item("../private")

    def test_empty_filter_exports_zero_rows(self):
        result = self.api.export_filtered("products", [], "no matches")
        with (Path(result["dir"]) / result["files"][0]).open(encoding="utf-8-sig", newline="") as f:
            self.assertEqual(len(list(csv.reader(f))), 1)
        self.assertEqual(result["count"], 1)

    def test_export_formula_escaped_and_unique(self):
        first = self.api.export_filtered("products", ["1234567"], "same")
        second = self.api.export_filtered("products", ["1234567"], "same")
        self.assertNotEqual(first["files"], second["files"])
        with (Path(first["dir"]) / first["files"][0]).open(encoding="utf-8-sig", newline="") as f:
            self.assertEqual(list(csv.reader(f))[1][1], "'=1+2")

    def test_empty_auxiliary_exports_remain_empty(self):
        self.api.dataset["items"].append({"folder": "unknown.zip", "size": 2})
        for kind in ("unid", "dups"):
            result = self.api.export_filtered(kind, [], "no matches")
            with (Path(result["dir"]) / result["files"][0]).open(encoding="utf-8-sig", newline="") as f:
                self.assertEqual(len(list(csv.reader(f))), 1)

    def test_export_all_keeps_previous_export(self):
        one = self.api.export_excel()
        two = self.api.export_excel()
        self.assertTrue(one["ok"] and two["ok"])
        self.assertNotEqual(one["dir"], two["dir"])
        self.assertTrue((Path(one["dir"]) / one["files"][0]).exists())

    def test_corrupt_config_not_silently_overwritten(self):
        self.cfg.config_file.write_text("{broken", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            Config(home=self.cfg.home).load()
        self.assertEqual(self.cfg.config_file.read_text(), "{broken")

    def test_future_or_invalid_dataset_rejected(self):
        from boothlib.migrate import load_migrated
        for value in [[], {"items": "bad", "products": []},
                      {"schema": 100, "items": [], "products": []}]:
            self.cfg.data("dataset.json").write_text(json.dumps(value))
            self.assertIsNone(load_migrated(self.cfg.data("dataset.json"))[0])

    def test_negative_metadata_cache_expires(self):
        file = self.cfg.item_file("1234567")
        self.api.client._write_json(file, {"__notfound__": True, "id": "1234567"})
        os.utime(file, (1, 1))
        with patch.object(self.api.client, "_get", return_value=json.dumps(self.meta)) as get:
            self.assertIsNotNone(self.api.client.get_item("1234567"))
            get.assert_called_once()

    def test_legacy_verification_failure_recovers(self):
        pipe = Pipeline(self.cfg, self.api.client)
        file = self.cfg.cache_dir / "verify" / "1234567.json"
        file.write_text('{"__notfound__":true}')
        with patch.object(self.api.client, "_get", return_value=json.dumps(self.meta)):
            self.assertIsNotNone(pipe._verify_get("1234567"))
        self.assertEqual(json.loads(file.read_text())["id"], 1234567)

    def test_archive_limit_counts_decompressed_bytes(self):
        file = self.root / "fixture.unitypackage"
        file.write_bytes(gzip.compress(b"\0" * 100000))
        result = _probe_unitypackage(file, max_decomp=4096)
        self.assertTrue(result["truncated"])

    def test_image_redirect_cannot_reach_private_host(self):
        from boothlib.booth_client import BoothRedirect
        request = urllib.request.Request("https://booth.pximg.net/demo.jpg")
        with self.assertRaises(BoothError):
            BoothRedirect().redirect_request(request, None, 302, "", {}, "http://127.0.0.1/private")

    def test_atomic_cache_write_preserves_old_data_on_failure(self):
        file = self.cfg.item_file("1234567")
        self.api.client._write_json(file, self.meta)
        before = file.read_bytes()
        with patch("boothlib.booth_client.os.replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.api.client._write_json(file, {"new": True})
        self.assertEqual(file.read_bytes(), before)
        self.assertFalse(list(file.parent.glob("*.tmp")))

    def test_window_close_exits_and_reload_invalidates_close(self):
        from unittest.mock import Mock
        exit_handler = Mock()
        self.api._exit_handler = exit_handler
        with patch("boothlib.api.threading.Timer") as timer:
            self.api.window_closed()
            close = timer.call_args.args[1]
            self.api.heartbeat()  # a refreshed page reconnects during grace
            close()
            exit_handler.assert_not_called()
            self.api.window_closed()
            timer.call_args.args[1]()
        exit_handler.assert_called_once_with()

    def test_window_close_cancels_worker_and_rechecks_reload(self):
        from unittest.mock import Mock
        self.api._exit_handler = Mock()
        self.api.task["busy"] = True
        def cancelled():
            self.api.task["busy"] = False
            self.api.heartbeat()  # reconnect while worker is cancelling
        with patch("boothlib.api.threading.Timer") as timer, \
             patch.object(self.api, "cancel", side_effect=cancelled) as cancel:
            self.api.window_closed()
            timer.call_args.args[1]()
        cancel.assert_called_once_with()
        self.api._exit_handler.assert_not_called()

    def test_heartbeat_watchdog_allows_background_throttling(self):
        from boothlib.app import _watch_client
        self.api.last_heartbeat = 100
        with patch("boothlib.app.time.sleep"), \
             patch("boothlib.app.time.monotonic", side_effect=[160, 221]), \
             patch.object(self.api, "window_closed", side_effect=SystemExit) as close:
            with self.assertRaises(SystemExit):
                _watch_client(self.api, lambda message: None)
        close.assert_called_once_with()

    def test_instance_lock(self):
        one, two = InstanceLock(self.cfg.home), InstanceLock(self.cfg.home)
        self.addCleanup(one.release)
        self.addCleanup(two.release)
        self.assertTrue(one.acquire())
        self.assertFalse(two.acquire())
        one.release()
        self.assertTrue(two.acquire())

    def test_scan_and_probe_preserve_source_hashes(self):
        path = self.root / "demo.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Assets/Demo/readme.txt", "fixture")
        before = hashlib.sha256(path.read_bytes()).digest()
        items = scan(str(self.root))["items"]
        probe_items(str(self.root), items, {})
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).digest())


if __name__ == "__main__":
    unittest.main()
