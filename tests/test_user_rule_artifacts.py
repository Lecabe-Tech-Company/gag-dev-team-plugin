"""Synthetic private payloads stay outside public source, packages and code graphs."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

from test_project_cli import ROOT
from test_releases import release_fixture
from test_user_rules import UserRulesCase


class UserRuleArtifactTests(UserRulesCase):
    def copy_public_source(self):
        for directory in ("agents", "skills", "hooks", "scripts", "ui", "mcp", "bin"):
            shutil.copytree(ROOT / directory, self.project / directory, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("package.json", "plugin.json", "mcp.json", "README.md"):
            shutil.copyfile(ROOT / name, self.project / name)

    def test_private_rule_never_enters_git_zip_npm_or_the_code_graph(self):
        self.copy_public_source()
        self.review(self.propose())
        self.git("add", ".")
        self.assertNotIn(self.marker, self.git("diff", "--cached", "--binary"))
        marker = self.marker.encode("utf-8")
        builder = importlib.import_module("build_release")
        with tempfile.TemporaryDirectory(prefix="private rule artifacts ") as temp:
            output = Path(temp)
            artifact, _ = builder.build_release(self.project, output, "v9.9.9")
            with zipfile.ZipFile(artifact) as archive:
                self.assertIn("scripts/user_rules.py", archive.namelist())
                self.assertIn("skills/manage-user-rules/SKILL.md", archive.namelist())
                for name in archive.namelist():
                    self.assertNotIn(marker, archive.read(name), name)
            packaged = subprocess.run(["npm", "pack", "--json", "--pack-destination", str(output)],
                                     cwd=self.project, capture_output=True, text=True, timeout=30)
            self.assertEqual(packaged.returncode, 0, packaged.stderr)
            filename = json.loads(packaged.stdout)[0]["filename"]
            with tarfile.open(output / filename, "r:gz") as archive:
                names = {member.name for member in archive.getmembers()}
                self.assertIn("package/scripts/user_rules.py", names)
                self.assertIn("package/skills/manage-user-rules/SKILL.md", names)
                for member in archive.getmembers():
                    if member.isfile():
                        with archive.extractfile(member) as stream:
                            self.assertNotIn(marker, stream.read(), member.name)
            binary = shutil.which("graphify") or str(Path.home() / ".local/bin/graphify")
            graph_root = output / "graph"
            extracted = subprocess.run([binary, "extract", str(self.project), "--code-only", "--no-cluster",
                                        "--out", str(graph_root)], capture_output=True, text=True, timeout=90)
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            graph = graph_root / "graphify-out/graph.json"
            self.assertTrue(graph.is_file())
            self.assertNotIn(marker, graph.read_bytes())

    def test_real_release_update_preserves_private_records_outside_managed_runtime(self):
        proposed = self.propose()
        self.review(proposed)
        storage = self.rules.storage_root(self.project)
        before = {path.relative_to(storage): path.read_bytes() for path in storage.rglob("*") if path.is_file()}
        builder = importlib.import_module("build_release")
        releases = importlib.import_module("releases")
        with tempfile.TemporaryDirectory(prefix="private rule update ") as temp:
            artifact, _ = builder.build_release(ROOT, temp, "v9.9.9")
            with zipfile.ZipFile(artifact) as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            release, download = release_fixture(entries, tag="v9.9.9")
            result = releases.update_project(self.project, fetch_json=lambda _: release, fetch_bytes=download)
            self.assertTrue(result["updated"])
        after = {path.relative_to(storage): path.read_bytes() for path in storage.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        record = self.rules.read_rule(self.project, proposed["rule"]["id"], plugin_root=self.runtime)
        self.assertEqual(record["rule"]["content"], self.content)
