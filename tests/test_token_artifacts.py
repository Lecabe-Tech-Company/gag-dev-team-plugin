"""Synthetic token metadata never enters versioned source or distributed artifacts."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from test_project_cli import ROOT
from token_usage_fixtures import TokenUsageCase, PRIVATE_MARKER, record, response


class TokenArtifactTests(TokenUsageCase):
    def test_private_goals_sources_and_usage_stay_outside_git_packages_and_code_graphs(self):
        for name in ("agents", "skills", "hooks", "scripts", "ui", "mcp", "bin", "dashboard"):
            shutil.copytree(ROOT / name, self.project / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", ".next", "tests", "*.tsbuildinfo"))
        for name in ("package.json", "plugin.json", "mcp.json", "README.md", ".npmignore"):
            shutil.copyfile(ROOT / name, self.project / name)
        marker = "SYNTHETIC_PRIVATE_GOAL_METADATA_086"
        path = self.create_source()
        self.add_context(path)
        self.start_goal(name=marker)
        self.append_records(path, record("response_item", {"role": "user", "content": PRIVATE_MARKER}), response())
        self.tokens.sync_usage(self.binding, {})
        self.assertEqual(self.own()["total_tokens"], 120)
        self.git("add", ".")
        staged = self.git("diff", "--cached", "--binary")
        self.assertNotIn(marker, staged)
        self.assertNotIn(PRIVATE_MARKER, staged)
        with tempfile.TemporaryDirectory(prefix="token-artifact-proof-") as temporary:
            artifact, _checksum = importlib.import_module("build_release").build_release(self.project, temporary, "v9.9.9")
            with zipfile.ZipFile(artifact) as archive:
                self.assertIn("scripts/token_usage.py", archive.namelist())
                for name in archive.namelist():
                    data = archive.read(name)
                    self.assertNotIn(marker.encode(), data, name)
                    self.assertNotIn(PRIVATE_MARKER.encode(), data, name)
            packed = subprocess.run(["npm", "pack", "--json", "--dry-run"], cwd=self.project,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(packed.returncode, 0, packed.stderr)
            names = {item["path"] for item in json.loads(packed.stdout)[0]["files"]}
            self.assertIn("scripts/token_usage.py", names)
            for name in names:
                data = (self.project / name).read_bytes()
                self.assertNotIn(marker.encode(), data, name)
                self.assertNotIn(PRIVATE_MARKER.encode(), data, name)
            graphify = shutil.which("graphify")
            self.assertIsNotNone(graphify, "The required Graphify runtime is unavailable")
            output = Path(temporary) / "code-graph"
            extracted = subprocess.run([graphify, "extract", str(self.project), "--code-only", "--no-cluster", "--out", str(output)],
                                       capture_output=True, text=True, timeout=90)
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            graph = (output / "graphify-out/graph.json").read_bytes()
            self.assertNotIn(marker.encode(), graph)
            self.assertNotIn(PRIVATE_MARKER.encode(), graph)

