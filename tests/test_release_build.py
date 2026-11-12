"""Build real release artifacts in temporary storage, without touching sources."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from test_project_cli import ProjectCase, ROOT


class ReleaseBuildTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.builder = importlib.import_module("build_release")

    def test_next_tag_uses_declared_upgrade_or_increments_latest_patch(self):
        cases = [("0.3.0", None, "v0.3.0"), ("1.0.0", "v0.9.9", "v1.0.0"), ("0.3.0", "v0.3.0", "v0.3.1"), ("0.2.0", "v0.3.4", "v0.3.5"), ("v2.0.0", "v1.99.99", "v2.0.0")]
        for current, latest, expected in cases:
            with self.subTest(current=current, latest=latest):
                self.assertEqual(self.builder.next_tag(current, latest), expected)
        for invalid in ("master", "v1.0.0-rc.1", "1.2"):
            with self.subTest(tag=invalid), self.assertRaises(ValueError):
                self.builder.next_tag(invalid)

    def test_zip_checksum_versions_and_required_runtime_assets_are_shippable(self):
        originals = {name: (ROOT / name).read_bytes() for name in ("package.json", "plugin.json")}
        with tempfile.TemporaryDirectory(prefix="gag build qa ") as temp:
            artifact, checksum = self.builder.build_release(ROOT, temp, "v0.9.7")
            self.assertEqual(artifact.name, "gag-dev-team-plugin-v0.9.7.zip")
            self.assertEqual(checksum.read_text(), hashlib.sha256(artifact.read_bytes()).hexdigest() + "  " + artifact.name + "\n")
            with zipfile.ZipFile(artifact) as archive:
                names = set(archive.namelist())
                required = {"package.json", "plugin.json", "scripts/project_install.py", "scripts/harness_adapters.py", "scripts/releases.py", "scripts/sdd_gate.py", "hooks/scripts/team_hooks.py", "bin/runtime.cjs", "bin/gag-dev-team.cjs", "mcp/scripta_bridge.cjs", "mcp/scripta_headers.cjs", "ui/brand/scripta-icon.png", "skills/caveman/SKILL.md", "skills/caveman/LICENSE"}
                self.assertTrue(required <= names, required - names)
                self.assertFalse(any(name.startswith((".git/", ".gag-dev-team/", "tests/")) or "__pycache__" in name for name in names))
                for name in originals:
                    self.assertEqual(json.loads(archive.read(name))["version"], "0.9.7")
                archive.extractall(Path(temp) / "source")
            installed = subprocess.run(["python3", "-c", "from project_install import install; import sys; install(sys.argv[1], harnesses=['codex'], release_tag='v0.9.7')", str(self.project)], cwd=Path(temp) / "source/scripts", capture_output=True, text=True, timeout=10)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            manifest = json.loads((self.project / ".gag-dev-team/install.json").read_text())
            self.assertEqual(manifest["release_tag"], "v0.9.7")
            self.assertEqual(manifest["harnesses"], ["codex"])
        self.assertEqual({name: (ROOT / name).read_bytes() for name in originals}, originals)

    def test_workflow_tag_output_is_a_real_newline_delimited_record(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        command = next(line.strip() for line in workflow.splitlines() if "python -c" in line and "GITHUB_OUTPUT" in line)
        command = command.replace("python -c", "python3 -c", 1)
        with tempfile.TemporaryDirectory(prefix="gag workflow qa ") as temp:
            directory = Path(temp)
            (directory / "release-result.json").write_text('{"tag":"v0.9.7"}')
            output = directory / "github-output"
            environment = dict(os.environ, GITHUB_OUTPUT=str(output))
            result = subprocess.run(command, shell=True, cwd=directory, env=environment, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), b"tag=v0.9.7\n")
