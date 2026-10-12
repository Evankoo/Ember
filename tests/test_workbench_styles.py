import hashlib
import json
from pathlib import Path
import re
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/gstudio_core/web"
SYNC = runpy.run_path(str(ROOT / "tools/sync_workbench_styles.py"))


class WorkbenchStyleTests(unittest.TestCase):
    def setUp(self):
        self.css = (WEB / "assets/workbench.css").read_text(encoding="utf-8")

    def test_copied_stylesheet_has_no_private_markers(self):
        self.assertEqual(SYNC["sensitive"](self.css), [])
        self.assertEqual(SYNC["sensitive"]("url(/Volumes/x) Studio", ("studio",)), ["/Volumes/", "studio"])

    def test_record_matches_the_shipped_copy(self):
        record = json.loads((ROOT / "docs/workbench-source.json").read_text(encoding="utf-8"))
        self.assertEqual(record["stylesheet_sha256"], hashlib.sha256(self.css.encode()).hexdigest())
        self.assertRegex(record["source_commit"], r"^[0-9a-f]{40}$")

    def test_display_font_is_the_bundled_file_not_embedded_data(self):
        self.assertNotIn("data:font", self.css)
        self.assertIn("url('../fonts/gstudio-display.woff2')", self.css)
        self.assertTrue((WEB / "fonts/gstudio-display.woff2").is_file())

    def test_page_loads_only_local_relative_assets(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for reference in re.findall(r'(?:href|src)="([^"#]+)"', html):
            self.assertFalse(reference.startswith(("/", "http:", "https:", "//")), reference)
            self.assertTrue((WEB / reference).is_file(), reference)


if __name__ == "__main__":
    unittest.main()
