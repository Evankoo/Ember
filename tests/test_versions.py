"""Every place that names the release version must agree, or installs fetch the wrong package."""
from pathlib import Path
import re
import unittest

from ember import __version__, locator
from ember.bootstrap import PACKAGE

ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTests(unittest.TestCase):
    def test_package_installer_and_skill_name_the_same_release(self):
        pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        installer = re.search(r'^VERSION = "([^"]+)"', (PACKAGE / "skills/ember-init/scripts/bootstrap.py").read_text(), re.M).group(1)
        self.assertEqual({pyproject, installer}, {__version__})
        skill = (PACKAGE / "skills/ember-init/SKILL.md").read_text()
        self.assertIn(f"ember-{__version__}-py3-none-any.whl", skill)
        self.assertIn(f"v{__version__}", skill)
        self.assertNotRegex(skill.replace(__version__, ""), r"ember-\d+\.\d+\.\d+-py3")

    def test_changelog_describes_the_current_release(self):
        self.assertRegex((ROOT / "CHANGELOG.md").read_text(), rf"(?m)^## {re.escape(__version__)}[：:]")

    def test_daily_skill_content_never_reuses_a_released_version_number(self):
        skill = (PACKAGE / "skills/ember/SKILL.md").read_text()
        current = re.search(r"^version: (\S+)", skill, re.M).group(1)
        released = {version: value for version, value in locator._official_fingerprints().items()
                    if version.split()[0] == current}
        if released:
            self.assertIn(locator.fingerprint(locator._source_tree()), released.values(),
                          "ember content changed; bump its version")

    def test_bundled_skills_follow_the_documented_structure(self):
        guide = (ROOT / "docs/skill-authoring.md").read_text()
        headings = re.findall(r"(?m)^## ([A-Z][a-z].+)$", guide)
        self.assertEqual(headings, ["Contract", "When to Use", "References", "Phases", "Output Format", "Anti-Patterns", "Tools Used"])
        for skill in (PACKAGE / "skills").glob("*/SKILL.md"):
            text = skill.read_text()
            self.assertTrue(text.startswith("---\n"), skill)
            self.assertEqual(re.findall(r"(?m)^## ([A-Z][a-z].+)$", text), headings, skill)

if __name__ == "__main__":
    unittest.main()
