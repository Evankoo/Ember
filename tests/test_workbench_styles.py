import base64
import hashlib
import json
from pathlib import Path
import re
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/ember/web"
SHARED = ROOT / "src/ember/ember_ui"
SYNC = runpy.run_path(str(ROOT / "tools/sync_workbench_styles.py"))


class WorkbenchStyleTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / "docs/workbench-source.json").read_text(encoding="utf-8"))
        self.files = {path.relative_to(SHARED).as_posix(): path.read_bytes() for path in sorted(SHARED.rglob("*"))
                      if path.is_file() and "__pycache__" not in path.parts}

    def test_copied_interface_has_no_private_markers(self):
        for name, data in {**self.files, "workbench-pages.css": (WEB / "assets/workbench-pages.css").read_bytes()}.items():
            self.assertEqual(SYNC["sensitive"](data.decode("utf-8")), [], name)
        self.assertEqual(SYNC["sensitive"]("url(/Volumes/x) Studio", ("studio",)), ["/Volumes/", "studio"])
        self.assertEqual(SYNC["sensitive"]("url(data:font/woff2;base64,AAAA/Users/BB)"), [])
        self.assertEqual(SYNC["sensitive"]("cd /home/someone"), ["/home/"])
        self.assertEqual(SYNC["sensitive"]('fetch("/api/home/search") <svg xmlns="http://www.w3.org/2000/svg">'), [])
        self.assertEqual(SYNC["sensitive"]('<a href="http://example">'), ["http://"])

    def test_record_matches_the_shipped_copy(self):
        self.assertEqual(self.record["source_dir"], "ui/ember_ui")
        self.assertEqual(self.record["files"], {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()})
        self.assertEqual(self.record["page_styles_sha256"], hashlib.sha256((WEB / "assets/workbench-pages.css").read_bytes()).hexdigest())
        self.assertRegex(self.record["source_commit"], r"^[0-9a-f]{40}$")
        self.assertIn("static/workbench.css", self.files)
        self.assertIn("pages/task_detail.py", self.files)

    def test_embedded_display_font_is_the_bundled_ofl_font(self):
        css = self.files["static/workbench.css"].decode("utf-8")
        fonts = re.findall(r"url\(data:font/woff2;base64,([^)]+)\)", css)
        self.assertTrue(fonts)
        bundled = (WEB / "fonts/ember-display.woff2").read_bytes()
        for font in fonts:
            self.assertEqual(base64.b64decode(font), bundled)
        self.assertTrue((WEB / "fonts/OFL.txt").is_file())
        # The stylesheet's embedded font is allowed by the page policy; nothing else may load data: URLs.
        from ember.server import CSP
        self.assertIn("font-src 'self' data:;", CSP)
        self.assertEqual(CSP.count("data:"), 1)

    def test_page_loads_only_local_relative_assets(self):
        from ember.pages import render_index
        html = render_index()
        references = re.findall(r'(?:href|src)="([^"#]+)"', html)
        for reference in references:
            self.assertFalse(reference.startswith(("/", "http:", "https:", "//")), reference)
            local = SHARED / "static" / reference.removeprefix("ember_ui/") if reference.startswith("ember_ui/") else WEB / reference
            self.assertTrue(local.is_file(), reference)
        for name in self.files:
            if name.startswith("static/"):
                self.assertIn(name.replace("static/", "ember_ui/", 1), references, name)
        scripts = [reference for reference in references if reference.endswith(".js")]
        self.assertEqual(scripts[-1], "app.js", "app.js runs after the shared scripts it configures")


if __name__ == "__main__":
    unittest.main()
