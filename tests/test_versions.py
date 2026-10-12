"""Every place that names the release version must agree, or installs fetch the wrong package."""
from pathlib import Path
import re
import unittest

from gstudio_core import __version__, locator
from gstudio_core.bootstrap import PACKAGE

ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTests(unittest.TestCase):
    def test_package_installer_and_skill_name_the_same_release(self):
        pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        installer = re.search(r'^VERSION = "([^"]+)"', (PACKAGE / "skills/gstudio-init/scripts/bootstrap.py").read_text(), re.M).group(1)
        self.assertEqual({pyproject, installer}, {__version__})
        skill = (PACKAGE / "skills/gstudio-init/SKILL.md").read_text()
        self.assertIn(f"gstudio_core-{__version__}-py3-none-any.whl", skill)
        self.assertIn(f"v{__version__}", skill)
        self.assertNotRegex(skill.replace(__version__, ""), r"gstudio_core-\d+\.\d+\.\d+-py3")

    def test_changelog_describes_the_current_release(self):
        self.assertRegex((ROOT / "CHANGELOG.md").read_text(), rf"(?m)^## {re.escape(__version__)}[：:]")

    def test_daily_skill_content_never_reuses_a_released_version_number(self):
        skill = (PACKAGE / "skills/gstudio-core/SKILL.md").read_text()
        current = re.search(r"^version: (\S+)", skill, re.M).group(1)
        released = {version: value for version, value in locator._official_fingerprints().items()
                    if version.split()[0] == current}
        if released:
            self.assertIn(locator.fingerprint(locator._source_tree()), released.values(),
                          "gstudio-core content changed; bump its version")

if __name__ == "__main__":
    unittest.main()
