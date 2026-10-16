"""The page-by-page comparison with the full workbench must be current for the shipped UI."""
import json
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
PARITY = runpy.run_path(str(ROOT / "tools/check_workbench_parity.py"))


class WorkbenchParityTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "docs/workbench-parity.json").read_text(encoding="utf-8"))
        self.record = json.loads((ROOT / "docs/workbench-parity-record.json").read_text(encoding="utf-8"))

    def test_record_covers_the_shipped_pages(self):
        self.assertEqual(self.record["ui_sha256"], PARITY["ui_sha256"](),
                         "界面文件改过但没有重新对照：运行 tools/check_workbench_parity.py --source <工作台> --write-record")

    def test_record_and_stylesheet_were_checked_against_the_same_workbench(self):
        stylesheet = json.loads((ROOT / "docs/workbench-source.json").read_text(encoding="utf-8"))
        self.assertEqual(self.record["source_commit"], stylesheet["source_commit"])
        self.assertEqual(self.record["pages"], [page["name"] for page in self.config["pages"]])

    def test_every_allowed_difference_says_why(self):
        ids = [entry["id"] for entry in self.config["allowed"]]
        self.assertEqual(len(ids), len(set(ids)))
        for entry in self.config["allowed"]:
            self.assertIn(entry["status"], ("intentional", "pending"), entry)
            self.assertTrue(entry["reason"].strip(), entry)
            self.assertRegex(entry["id"], r"^[\w*-]+:(only-local|only-core|only-\*|style|\*)", entry)

    def test_comparison_never_stores_private_page_addresses(self):
        for page in self.config["pages"]:
            self.assertTrue(page["core"].startswith("#"), page)
            self.assertFalse(page.get("local", "/").startswith(("/tasks/", "/projects/")), page)


if __name__ == "__main__":
    unittest.main()
