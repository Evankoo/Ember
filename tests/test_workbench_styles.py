import base64
import hashlib
import json
from pathlib import Path
import re
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/ember/web"
SHARED = WEB / "ember_ui"
SYNC = runpy.run_path(str(ROOT / "tools/sync_workbench_styles.py"))


class WorkbenchStyleTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / "docs/workbench-source.json").read_text(encoding="utf-8"))
        self.files = {path.name: path.read_bytes() for path in sorted(SHARED.iterdir()) if path.is_file()}

    def test_copied_interface_has_no_private_markers(self):
        for name, data in {**self.files, "workbench-pages.css": (WEB / "assets/workbench-pages.css").read_bytes()}.items():
            self.assertEqual(SYNC["sensitive"](data.decode("utf-8")), [], name)
        self.assertEqual(SYNC["sensitive"]("url(/Volumes/x) Studio", ("studio",)), ["/Volumes/", "studio"])
        self.assertEqual(SYNC["sensitive"]("url(data:font/woff2;base64,AAAA/Users/BB)"), [])

    def test_record_matches_the_shipped_copy(self):
        self.assertEqual(self.record["source_dir"], "ui/ember_ui/static")
        self.assertEqual(self.record["files"], {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()})
        self.assertEqual(self.record["page_styles_sha256"], hashlib.sha256((WEB / "assets/workbench-pages.css").read_bytes()).hexdigest())
        self.assertRegex(self.record["source_commit"], r"^[0-9a-f]{40}$")
        self.assertIn("workbench.css", self.files)

    def test_embedded_display_font_is_the_bundled_ofl_font(self):
        css = self.files["workbench.css"].decode("utf-8")
        fonts = re.findall(r"url\(data:font/woff2;base64,([^)]+)\)", css)
        self.assertTrue(fonts)
        bundled = (WEB / "fonts/gstudio-display.woff2").read_bytes()
        for font in fonts:
            self.assertEqual(base64.b64decode(font), bundled)
        self.assertTrue((WEB / "fonts/OFL.txt").is_file())
        # The page's font-src policy does not load data: fonts, so app.css declares the bundled file last.
        self.assertIn('src:url("fonts/gstudio-display.woff2")', (WEB / "app.css").read_text(encoding="utf-8"))

    def test_page_loads_only_local_relative_assets(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        references = re.findall(r'(?:href|src)="([^"#]+)"', html)
        for reference in references:
            self.assertFalse(reference.startswith(("/", "http:", "https:", "//")), reference)
            self.assertTrue((WEB / reference).is_file(), reference)
        for name in self.files:
            self.assertIn(f"ember_ui/{name}", references, name)
        scripts = [reference for reference in references if reference.endswith(".js")]
        self.assertEqual(scripts[-1], "app.js", "app.js runs after the shared scripts it configures")


if __name__ == "__main__":
    unittest.main()
