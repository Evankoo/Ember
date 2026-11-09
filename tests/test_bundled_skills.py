"""The review and Skill-authoring Skills ship with new workspaces and can be added to older ones."""
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from ember.bootstrap import OPTIONAL_SKILLS, add_bundled_skills, skill_route, verify_workspace_contract
from ember.cli import main
from ember.store import Workspace, WorkspaceError

HAN = re.compile(r"[一-鿿]")


class BundledSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def workspace(self, language="zh"):
        workspace = Workspace(self.root / f"Ember-{language}", language=language)
        workspace.initialize()
        return workspace

    def make_old(self, workspace):
        """Strip the 0.22.0 Skills so the workspace looks like one created by 0.21.0."""
        manifest = workspace._json("skills/manifest.json")
        manifest["skills"] = [item for item in manifest["skills"] if item["name"] not in OPTIONAL_SKILLS]
        (workspace.path / "skills/manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        resolver = workspace.path / "skills/RESOLVER.md"
        lines = [line for line in resolver.read_text().splitlines() if not any(f"/{name}/" in line for name in OPTIONAL_SKILLS)]
        resolver.write_text("\n".join(lines) + "\n")
        for name in OPTIONAL_SKILLS:
            shutil.rmtree(workspace.path / ".agents/skills" / name)

    def test_new_workspaces_register_and_route_both_skills(self):
        for language in ("zh", "en"):
            workspace = self.workspace(language)
            names = verify_workspace_contract(workspace)["skills"]
            resolver = (workspace.path / "skills/RESOLVER.md").read_text()
            root_resolver = (workspace.path / "RESOLVER.md").read_text()
            for name in OPTIONAL_SKILLS:
                self.assertIn(name, names)
                self.assertTrue((workspace.path / ".agents/skills" / name / "SKILL.md").is_file())
                self.assertFalse((workspace.path / ".agents/skills" / name / "locale").exists())
                self.assertIn(skill_route(name, language), resolver.splitlines())
                self.assertIn(f".agents/skills/{name}/SKILL.md", root_resolver)
            if language == "en":
                for name in OPTIONAL_SKILLS:
                    text = (workspace.path / ".agents/skills" / name / "SKILL.md").read_text()
                    self.assertIsNone(HAN.search(text), name)

    def test_an_older_workspace_still_passes_and_gets_the_skills_added_once(self):
        workspace = self.workspace()
        self.make_old(workspace)
        self.assertEqual(verify_workspace_contract(workspace)["skills"], ["ember-init", "ember", "ember-project"])
        result = add_bundled_skills(workspace)
        self.assertEqual(result, {"added": list(OPTIONAL_SKILLS), "already_present": []})
        self.assertEqual(verify_workspace_contract(workspace)["skills"][-2:], list(OPTIONAL_SKILLS))
        resolver = (workspace.path / "skills/RESOLVER.md").read_text().splitlines()
        project = next(index for index, line in enumerate(resolver) if "/ember-project/" in line)
        self.assertEqual(resolver[project + 1:project + 3], [skill_route(name) for name in OPTIONAL_SKILLS])
        before = {path: path.read_bytes() for path in workspace.path.rglob("*") if path.is_file()}
        self.assertEqual(add_bundled_skills(workspace), {"added": [], "already_present": list(OPTIONAL_SKILLS)})
        self.assertEqual(before, {path: path.read_bytes() for path in workspace.path.rglob("*") if path.is_file()})

    def test_adding_never_overwrites_an_unregistered_folder(self):
        workspace = self.workspace()
        self.make_old(workspace)
        own = workspace.path / ".agents/skills/ember-review/SKILL.md"
        own.parent.mkdir(parents=True)
        own.write_text("用户自己的同名 Skill\n")
        with self.assertRaises(WorkspaceError):
            add_bundled_skills(workspace)
        self.assertEqual(own.read_text(), "用户自己的同名 Skill\n")
        self.assertNotIn("ember-review", [item["name"] for item in workspace._json("skills/manifest.json")["skills"]])

    def test_a_registered_skill_must_keep_its_file(self):
        workspace = self.workspace()
        (workspace.path / ".agents/skills/ember-review/SKILL.md").unlink()
        with self.assertRaises(WorkspaceError):
            verify_workspace_contract(workspace)

    def test_cli_adds_the_skills(self):
        workspace = self.workspace()
        self.make_old(workspace)
        self.assertEqual(main(["add-skills", "--workspace", str(workspace.path)]), 0)
        self.assertEqual(verify_workspace_contract(workspace)["skills"][-2:], list(OPTIONAL_SKILLS))

    def test_review_prompts_point_to_the_review_skill(self):
        for language, words in (("zh", "按它的步骤整理"), ("en", "review by its steps")):
            workspace = self.workspace(language)
            task = workspace.create_task({"title": "Plan", "project": "independent", "goal": "A plan"})
            for text in (workspace.build_weekly_context({})["text"], workspace.build_review_context({"task_ids": [task["id"]]})["text"]):
                self.assertIn(".agents/skills/ember-review/SKILL.md", text)
                self.assertIn(words, text)


if __name__ == "__main__":
    unittest.main()
