"""Private skill files and evidence stay outside public packages and code graphs."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

import test_user_rule_artifacts as rule_artifacts
from test_project_cli import ROOT
from test_releases import release_fixture
from test_user_skills import UserSkillsCase


class UserSkillArtifactTests(UserSkillsCase):
    copy_public_source = rule_artifacts.UserRuleArtifactTests.copy_public_source

    def test_private_skill_and_references_never_enter_git_zip_npm_or_code_graph(self):
        self.copy_public_source()
        self.review_skill(self.propose_skill())
        self.git("add", ".")
        staged = self.git("diff", "--cached", "--binary")
        self.assertNotIn(self.body_marker, staged)
        self.assertNotIn(self.reference_marker, staged)
        markers = [self.body_marker.encode("utf-8"), self.reference_marker.encode("utf-8")]
        builder = importlib.import_module("build_release")
        with tempfile.TemporaryDirectory(prefix="private skill artifacts ") as temp:
            output = Path(temp)
            artifact, _ = builder.build_release(self.project, output, "v9.9.9")
            with zipfile.ZipFile(artifact) as archive:
                self.assertIn("scripts/user_skills.py", archive.namelist())
                self.assertIn("skills/manage-user-skills/SKILL.md", archive.namelist())
                for name in archive.namelist():
                    for marker in markers:
                        self.assertNotIn(marker, archive.read(name), name)
            packaged = subprocess.run(["npm", "pack", "--json", "--pack-destination", str(output)],
                                     cwd=self.project, capture_output=True, text=True, timeout=30)
            self.assertEqual(packaged.returncode, 0, packaged.stderr)
            filename = json.loads(packaged.stdout)[0]["filename"]
            with tarfile.open(output / filename, "r:gz") as archive:
                names = {member.name for member in archive.getmembers()}
                self.assertIn("package/scripts/user_skills.py", names)
                self.assertIn("package/skills/manage-user-skills/SKILL.md", names)
                for member in archive.getmembers():
                    if member.isfile():
                        with archive.extractfile(member) as stream:
                            content = stream.read()
                        for marker in markers:
                            self.assertNotIn(marker, content, member.name)
            binary = shutil.which("graphify") or str(Path.home() / ".local/bin/graphify")
            graph_root = output / "graph"
            extracted = subprocess.run([binary, "extract", str(self.project), "--code-only", "--no-cluster",
                                        "--out", str(graph_root)], capture_output=True, text=True, timeout=90)
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            graph = graph_root / "graphify-out/graph.json"
            self.assertTrue(graph.is_file())
            for marker in markers:
                self.assertNotIn(marker, graph.read_bytes())

    def test_upgrade_preserves_private_skill_bundle_and_provenance(self):
        proposed = self.propose_skill()
        self.review_skill(proposed)
        storage = self.skill_storage()
        before = {path.relative_to(storage): path.read_bytes() for path in storage.rglob("*") if path.is_file()}
        builder = importlib.import_module("build_release")
        releases = importlib.import_module("releases")
        with tempfile.TemporaryDirectory(prefix="private skill upgrade ") as temp:
            artifact, _ = builder.build_release(ROOT, temp, "v9.9.9")
            with zipfile.ZipFile(artifact) as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            release, download = release_fixture(entries, tag="v9.9.9")
            result = releases.update_project(self.project, fetch_json=lambda _: release, fetch_bytes=download)
            self.assertTrue(result["updated"])
        after = {path.relative_to(storage): path.read_bytes() for path in storage.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        shown = self.skills.read_skill(self.project, proposed["id"], plugin_root=self.runtime)["skill"]
        self.assertEqual(shown["skill_md"], self.bundle["skill_md"])
        self.assertEqual(shown["origin"], self.bundle["origin"])
        self.assertEqual(shown["references"], self.bundle["references"])
