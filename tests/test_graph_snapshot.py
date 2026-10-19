import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from scripts.graph_snapshot import FORMAT, audit, encoded, identifier, import_snapshot, sha256, validate_snapshot


class GraphSnapshotTests(unittest.TestCase):
    def fixture(self, root):
        manifest = {"format": FORMAT, "counts": {"nodes": 2, "relationships": 1}, "schema": [], "files": []}
        records = {"nodes": [{"id": 0, "labels": ["Institution"], "properties": {"name": "测试院校", "rank": 100}}, {"id": 1, "labels": ["MajorL3"], "properties": {"name": "计算机", "code": "080901"}}],
                   "relationships": [{"id": 0, "start": 0, "end": 1, "type": "TEST", "properties": {"source": "公开资料"}}]}
        for kind, rows in records.items():
            content = b"".join(map(encoded, rows))
            path = root / (kind + ".jsonl.gz")
            path.write_bytes(gzip.compress(content))
            manifest["files"].append({"name": path.name, "kind": kind, "count": len(rows), "bytes": path.stat().st_size, "sha256": sha256(path), "content_sha256": hashlib.sha256(content).hexdigest()})
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def test_valid_snapshot_preserves_unicode_and_text_codes(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            expected = self.fixture(root)
            self.assertEqual(validate_snapshot(root), expected)
            with gzip.open(root / "nodes.jsonl.gz", "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            self.assertEqual(rows[1]["properties"]["code"], "080901")

    def test_corrupt_compressed_file_is_rejected_before_database_access(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            with (root / "nodes.jsonl.gz").open("ab") as stream:
                stream.write(b"corrupt")
            client = Mock()
            with self.assertRaisesRegex(ValueError, "校验失败"):
                import_snapshot(client, root)
            client.run.assert_not_called()
            client.run_rows.assert_not_called()

    def test_nonempty_database_is_never_deleted(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            client = Mock()
            client.run_rows.return_value = [{"total": 10}]
            with self.assertRaisesRegex(ValueError, "非空"):
                import_snapshot(client, root)
            client.run.assert_not_called()

    def test_manifest_path_traversal_is_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self.fixture(root)
            manifest["files"][0]["name"] = "../private.env"
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "文件名"):
                validate_snapshot(root)

    def test_audit_accepts_public_urls_but_rejects_private_paths_and_secrets(self):
        audit({"properties": {"source": "https://example.org/major", "number": 1, "flag": True}})
        for properties in [{"source": "D:/Project/private/data"}, {"token": "sk-" + "x" * 32}, {"api_key": "example"}, {"__vrs_import_id": 1}, {"value": {"unsupported":"map"}}]:
            with self.subTest(fields=list(properties)), self.assertRaises(ValueError):
                audit({"properties": properties})

    def test_counts_must_match_manifest_and_content(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self.fixture(root)
            manifest["counts"]["nodes"] += 1
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "内容校验失败"):
                validate_snapshot(root)

    def test_identifier_quotes_embedded_backticks(self):
        self.assertEqual(identifier("A`B"), "`A``B`")


if __name__ == "__main__":
    unittest.main()
