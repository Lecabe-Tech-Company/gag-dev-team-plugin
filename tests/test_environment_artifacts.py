"""Distribution includes dashboard sources while excluding generated and private trees."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from test_project_cli import ProjectCase, ROOT


class EnvironmentArtifactTests(ProjectCase):
    def test_zip_and_npm_exclude_private_and_generated_canaries_but_keep_dashboard_lock(self):
        source = self.project / "synthetic-source"
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(
            ".git", "node_modules", ".next", "__pycache__", "graphify-out", "*.pyc"))
        marker = "SYNTHETIC_PRIVATE_DISTRIBUTION_CANARY_085"
        for name in ("dashboard/node_modules/private.txt", "dashboard/.next/private.txt",
                     "users/private.txt", "events/private.txt", "runtime/private.txt", ".env.private"):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(marker, encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="environment-artifacts-") as temporary:
            artifact, _ = importlib.import_module("build_release").build_release(source, temporary, "v9.9.9")
            with zipfile.ZipFile(artifact) as archive:
                names = archive.namelist()
                self.assertIn("dashboard/package-lock.json", names)
                self.assertIn("dashboard/app/page.tsx", names)
                for name in names:
                    self.assertNotIn(marker.encode(), archive.read(name), name)
                    self.assertFalse(any(part in {"node_modules", ".next", "users", "events", "runtime"}
                                         for part in Path(name).parts), name)
            packed = subprocess.run(["npm", "pack", "--json", "--dry-run"], cwd=source,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(packed.returncode, 0, packed.stderr)
            names = {entry["path"] for entry in json.loads(packed.stdout)[0]["files"]}
            self.assertIn("dashboard/package-lock.json", names)
            self.assertIn("dashboard/app/page.tsx", names)
            for name in names:
                self.assertFalse(any(part in {"node_modules", ".next", "users", "events", "runtime"}
                                     for part in Path(name).parts), name)
                self.assertNotIn(marker.encode(), (source / name).read_bytes(), name)

