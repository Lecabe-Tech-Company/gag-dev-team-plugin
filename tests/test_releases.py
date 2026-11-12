"""ESP-066 v2 release validation using local bytes, never the network."""
import hashlib
import importlib
import io
import json
import re
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def release_fixture(entries=None, tag="v0.3.0", bad_checksum=False):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        entries = entries if entries is not None else {"plugin.json": '{"name":"qa-plugin"}', "package.json": '{"version":"0.3.0"}', "scripts/fixture.py": "# fixture\n"}
        for name, data in entries.items():
            archive.writestr(name, data)
    archive_bytes = stream.getvalue()
    filename = "gag-dev-team-plugin-" + tag + ".zip"
    base = "https://github.com/Lecabe-Tech-Company/gag-dev-team-plugin/releases/download/" + tag + "/"
    checksum = "0" * 64 if bad_checksum else hashlib.sha256(archive_bytes).hexdigest()
    downloads = {base + filename: archive_bytes, base + "SHA256SUMS": (checksum + "  " + filename + "\n").encode()}
    release = {"tag_name": tag, "draft": False, "prerelease": False, "assets": [
        {"name": name, "browser_download_url": base + name, "size": len(downloads[base + name])}
        for name in (filename, "SHA256SUMS")]}
    return release, lambda url, *args, **kwargs: downloads[url]


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.releases = importlib.import_module("releases")
        self.temp = tempfile.TemporaryDirectory(prefix="gag release qa ")
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / "unpacked"

    def test_latest_rejects_draft_prerelease_and_nonstable_tags(self):
        for overrides in ({"draft": True}, {"prerelease": True}, {"tag_name": "master"}, {"tag_name": "v1.0.0-rc.1"}):
            release, _ = release_fixture()
            release.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises((ValueError, RuntimeError)):
                self.releases.latest_release(fetch_json=lambda *args, **kwargs: release)

    def test_latest_failure_does_not_fall_back_to_branch_source(self):
        calls = []
        def unavailable(url, *args, **kwargs):
            calls.append(url)
            raise OSError("offline fixture")
        with self.assertRaises((OSError, RuntimeError)):
            self.releases.latest_release(fetch_json=unavailable)
        self.assertEqual(len(calls), 1)
        self.assertIn("/releases/latest", calls[0])

    def test_checksum_mismatch_refuses_all_extraction(self):
        release, fetch = release_fixture(bad_checksum=True)
        with self.assertRaises((ValueError, RuntimeError)):
            self.releases.extract_release(release, self.destination, fetch_bytes=fetch)
        self.assertFalse(self.destination.exists() and any(self.destination.rglob("*")))

    def test_path_traversal_and_absolute_members_are_rejected(self):
        for name in ("../escaped.txt", "/absolute.txt", "..\\escaped.txt", "C:/escaped.txt"):
            release, fetch = release_fixture({name: "unsafe"})
            with self.subTest(name=name), self.assertRaises((ValueError, RuntimeError)):
                self.releases.extract_release(release, self.destination, fetch_bytes=fetch)
            self.assertFalse((self.destination.parent / "escaped.txt").exists())


    def test_valid_checked_archive_extracts_expected_bytes(self):
        entries = {"plugin.json": "{}", "scripts/project_install.py": "# qa source\n"}
        release, download = release_fixture(entries)
        self.assertEqual(self.releases.extract_release(release, self.destination, fetch_bytes=download), self.destination)
        self.assertEqual((self.destination / "scripts/project_install.py").read_text(), "# qa source\n")

    def test_symlink_archive_member_is_rejected_before_extraction(self):
        link = zipfile.ZipInfo("linked")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        release, download = release_fixture({link: "../../outside"})
        with self.assertRaises((ValueError, RuntimeError)):
            self.releases.extract_release(release, self.destination, fetch_bytes=download)
        self.assertFalse(self.destination.exists() and any(self.destination.rglob("*")))

class UpdateTests(unittest.TestCase):
    def setUp(self):
        import subprocess
        self.releases = importlib.import_module("releases")
        self.installer = importlib.import_module("project_install")
        self.temp = tempfile.TemporaryDirectory(prefix="gag update qa ")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.installer.install(self.project, source=ROOT, harnesses=["codex"], release_tag="v0.2.0")
        self.installer.configure_scripta(self.project, "qa-update-secret-never-real")

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes() for path in self.project.rglob("*") if path.is_file() and ".git" not in path.parts}

    def package(self, tag="v0.3.0", changed=False, new_guidance=False):
        entries = {}
        for name in ("agents", "skills", "hooks", "scripts", "ui", "mcp", "bin"):
            for path in (ROOT / name).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    entries[path.relative_to(ROOT).as_posix()] = path.read_bytes()
        for name in ("plugin.json", "mcp.json", "package.json"):
            entries[name] = (ROOT / name).read_bytes()
        if changed:
            entries["plugin.json"] += b"\n"
        if new_guidance:
            entries["scripts/harness_adapters.py"] = entries["scripts/harness_adapters.py"].replace("Orquestrador / Planejador".encode(), "QA_NEXT_RELEASE_GUIDANCE Orquestrador / Planejador".encode())
        return release_fixture(entries, tag)

    def test_equal_or_older_release_is_noop_without_download(self):
        from unittest.mock import Mock
        before = self.snapshot()
        for tag in ("v0.2.0", "v0.1.9"):
            release, _ = self.package(tag)
            download = Mock(side_effect=AssertionError("should not download"))
            result = self.releases.update_project(self.project, fetch_json=lambda *args: release, fetch_bytes=download)
            self.assertFalse(result["updated"])
            download.assert_not_called()
            self.assertEqual(self.snapshot(), before)

    def test_update_preserves_secret_preferences_and_selection_and_is_idempotent(self):
        config = self.project / ".codex/config.toml"
        config.write_text(re.sub(r'(?m)^model\s*=\s*.*$', 'model = "qa-custom-model"', config.read_text(), count=1))
        release, download = self.package()
        result = self.releases.update_project(self.project, fetch_json=lambda *args: release, fetch_bytes=download)
        self.assertTrue(result["updated"])
        self.assertEqual((self.project / ".gag-dev-team/scripta-token").read_text(), "qa-update-secret-never-real")
        self.assertIn('model = "qa-custom-model"', config.read_text())
        state = json.loads((self.project / ".gag-dev-team/install.json").read_text())
        self.assertEqual(state["release_tag"], "v0.3.0")
        self.assertEqual(state["harnesses"], ["codex"])
        before = self.snapshot()
        self.assertFalse(self.releases.update_project(self.project, fetch_json=lambda *args: release, fetch_bytes=download)["updated"])
        self.assertEqual(self.snapshot(), before)

    def test_conflict_and_network_failure_preserve_working_installation(self):
        path = self.project / ".codex/agents/gag-documentador.toml"
        path.write_text("# user-customized\n" + path.read_text())
        before = self.snapshot()
        release, download = self.package()
        with self.assertRaises((ValueError, RuntimeError)):
            self.releases.update_project(self.project, fetch_json=lambda *args: release, fetch_bytes=download)
        self.assertEqual(self.snapshot(), before)
        def unavailable(*args):
            raise OSError("offline fixture")
        with self.assertRaises((OSError, RuntimeError)):
            self.releases.update_project(self.project, fetch_json=unavailable, fetch_bytes=download)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.project / ".gag-dev-team/update.lock").exists())

    def test_concurrent_update_does_not_download_or_install_twice(self):
        import threading
        release, _ = self.package("v0.2.0")
        entered, release_fetch = threading.Event(), threading.Event()
        results, errors = [], []
        def fetch(*args):
            entered.set()
            if not release_fetch.wait(3):
                raise RuntimeError("test fetch wait expired")
            return release
        def update():
            try:
                results.append(self.releases.update_project(self.project, fetch_json=fetch))
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=update)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            second = self.releases.update_project(self.project, fetch_json=lambda *args: self.fail("second fetch is forbidden"))
            self.assertFalse(second["updated"])
            self.assertEqual(second["reason"], "in-progress")
        finally:
            release_fetch.set()
            worker.join(4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)

    def test_write_failure_rolls_back_new_runtime_and_manifest(self):
        from unittest.mock import patch
        release, download = self.package(changed=True)
        before = self.snapshot()
        original = self.installer.atomic_write
        failed = []
        def fail_manifest_once(path, contents, *args, **kwargs):
            if Path(path) == self.project / ".gag-dev-team/install.json" and not failed:
                failed.append(True)
                raise OSError("fixture disk failure after runtime writes")
            return original(path, contents, *args, **kwargs)
        with tempfile.TemporaryDirectory(prefix="gag rollback source ") as temp:
            source = self.releases.extract_release(release, temp, fetch_bytes=download)
            with patch.object(self.installer, "atomic_write", side_effect=fail_manifest_once):
                with self.assertRaises(OSError):
                    self.installer.install(self.project, source=source, harnesses=["codex"], release_tag="v0.3.0")
        self.assertEqual(failed, [True])
        self.assertEqual(self.snapshot(), before)

    def test_update_applies_adapter_logic_from_incoming_release(self):
        release, download = self.package(new_guidance=True)
        result = self.releases.update_project(self.project, fetch_json=lambda *args: release, fetch_bytes=download)
        self.assertTrue(result["updated"])
        self.assertIn("QA_NEXT_RELEASE_GUIDANCE", (self.project / ".gag-dev-team/plugin/scripts/harness_adapters.py").read_text())
        self.assertIn("QA_NEXT_RELEASE_GUIDANCE", (self.project / "AGENTS.md").read_text())

if __name__ == "__main__":
    unittest.main()
