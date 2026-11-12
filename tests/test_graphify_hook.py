"""Gate de PR em repositórios temporários; nenhum PR remoto é criado."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("graphify_hook", ROOT / "hooks/scripts/graphify_hook.py")
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class RequestTests(unittest.TestCase):
    def event(self, command):
        return {"tool_name": "exec_command", "cwd": "/tmp/example",
                "tool_input": {"cmd": command, "workdir": "/tmp/feature"}}

    def test_read_only_pr_commands_are_not_intercepted(self):
        for command in ["gh pr view 42", "gh pr list", "git status"]:
            self.assertIsNone(hook.pr_request(self.event(command)))

    def test_cli_create_includes_base_head_repo_and_workdir(self):
        request = hook.pr_request(self.event("gh pr create --base stage --head codex/feature/test -R owner/repo"))
        self.assertEqual(request, {"base": "stage", "head": "codex/feature/test",
                                  "repo": "owner/repo", "cwd": "/tmp/feature"})

    def test_shell_wrapper_is_not_assumed_to_target_current_directory(self):
        with self.assertRaises(hook.GateError):
            hook.pr_request(self.event("cd /other && gh pr create -B prod"))

    def test_mcp_create_is_intercepted(self):
        request = hook.pr_request({"tool_name": "mcp__github__create_pull_request",
                                  "cwd": "/tmp/repo",
                                  "tool_input": {"owner": "owner", "repo": "repo",
                                                 "base": "prod", "head": "feature"}})
        self.assertEqual(request["repo"], "owner/repo")

    def test_github_remote_formats(self):
        self.assertEqual(hook.repository_slug("git@github.com:Owner/Repo.git"), "owner/repo")
        self.assertEqual(hook.repository_slug("https://github.com/Owner/Repo.git"), "owner/repo")
        self.assertIsNone(hook.repository_slug("https://elsewhere.example/Owner/Repo"))


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "worktree with spaces"
        self.root.mkdir()
        self.git("init", "-b", "prod")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.root / ".gitignore").write_text("graphify-out/\n", encoding="utf-8")
        (self.root / "old.py").write_text("def old():\n    return 1\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("remote", "add", "origin", "https://github.com/owner/repo.git")
        for branch in ["prod", "stage"]:
            self.git("update-ref", "refs/remotes/origin/" + branch, self.base)
        self.git("checkout", "-b", "codex/feature/test")
        (self.root / "new file.py").write_text("def hello():\n    return 2\n", encoding="utf-8")
        (self.root / "guide.md").write_text("# Documento\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "feature")
        self.request = {"cwd": str(self.root), "base": "prod", "head": None, "repo": "owner/repo"}
        self.calls = []
        self.original_run = hook.run

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.DEVNULL).decode()

    def fake_run(self, args, **kwargs):
        self.calls.append(args)
        if args[:2] == ["git", "fetch"]:
            return b""
        if args[:2] == ["git", "ls-remote"]:
            return (self.git("rev-parse", "HEAD").strip() + "\trefs/heads/codex/feature/test\n").encode()
        if args[0] == "fake-graphify":
            corpus = Path(args[2])
            self.assertEqual(sorted(p.name for p in corpus.iterdir()), ["new file.py"])
            self.assertEqual((corpus / "new file.py").read_text(), "def hello():\n    return 2\n")
            output = Path(args[args.index("--out") + 1]) / "graphify-out"
            output.mkdir(parents=True)
            (output / "graph.json").write_text(json.dumps({
                "nodes": [{"id": "hello", "source_file": str(corpus / "new file.py")}],
                "edges": [],
            }), encoding="utf-8")
            return b""
        return self.original_run(args, **kwargs)

    def analyze(self):
        with patch.object(hook, "run", side_effect=self.fake_run):
            return hook.analyze_pr(self.request, "fake-graphify")

    def test_only_committed_changed_code_is_submitted(self):
        self.analyze()
        output = self.root / "graphify-out/pr-check/prod"
        record = json.loads((output / "check.json").read_text())
        self.assertEqual(record["analyzed"], ["new file.py"])
        self.assertEqual(record["skipped"], ["guide.md"])
        graph = json.loads((output / "graph.json").read_text())
        self.assertEqual(graph["nodes"][0]["source_file"], "new file.py")
        self.assertEqual(self.git("status", "--porcelain").strip(), "")

    def test_dirty_worktree_is_blocked(self):
        (self.root / "new file.py").write_text("changed\n")
        with self.assertRaises(hook.GateError):
            self.analyze()

    def test_wrong_repository_is_blocked(self):
        self.request["repo"] = "other/repo"
        with self.assertRaises(hook.GateError):
            self.analyze()

    def test_wrong_head_or_missing_base_is_blocked(self):
        self.request["head"] = "other-branch"
        with self.assertRaises(hook.GateError):
            self.analyze()
        self.request["head"] = None
        self.request["base"] = None
        with self.assertRaises(hook.GateError):
            self.analyze()

    def test_deleted_files_are_recorded(self):
        self.git("rm", "old.py")
        self.git("commit", "-m", "remove")
        self.analyze()
        record = json.loads((self.root / "graphify-out/pr-check/prod/check.json").read_text())
        self.assertIn("old.py", record["removed"])

    def test_graphify_failure_blocks_check(self):
        def fail(args, **kwargs):
            if args[0] == "fake-graphify":
                raise hook.GateError("failed")
            return self.fake_run(args, **kwargs)
        with patch.object(hook, "run", side_effect=fail):
            with self.assertRaises(hook.GateError):
                hook.analyze_pr(self.request, "fake-graphify")

    @unittest.skipUnless(shutil.which("graphify"), "Graphify não instalado no ambiente de teste")
    def test_real_graphify_extracts_changed_python(self):
        def offline_fetch(args, **kwargs):
            if args[:2] == ["git", "fetch"]:
                return b""
            if args[:2] == ["git", "ls-remote"]:
                return (self.git("rev-parse", "HEAD").strip() + "\trefs/heads/codex/feature/test\n").encode()
            return self.original_run(args, **kwargs)
        with patch.object(hook, "run", side_effect=offline_fetch):
            hook.analyze_pr(self.request, shutil.which("graphify"))
        graph = json.loads((self.root / "graphify-out/pr-check/prod/graph.json").read_text())
        self.assertTrue(any("hello" in json.dumps(node) for node in graph["nodes"]))


class InstallerTests(unittest.TestCase):
    def test_existing_graphify_is_not_reinstalled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "graphify"
            binary.write_text("#!/bin/sh\necho graphify-test\n")
            binary.chmod(0o755)
            env = dict(os.environ, HOME=temp, PATH=str(root))
            result = subprocess.run(["/bin/bash", str(ROOT / "hooks/scripts/install-graphify.sh")],
                                    env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), str(binary))

    def test_missing_graphify_uses_uv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "graphify"
            uv = root / "uv"
            uv.write_text(
                "#!/bin/bash\n"
                "if [[ \"$*\" == \"tool install graphifyy\" ]]; then\n"
                "  printf '#!/bin/sh\\necho graphify-test\n' > \"$HOME/graphify\"\n"
                "  /bin/chmod +x \"$HOME/graphify\"\n"
                "elif [[ \"$*\" == \"tool dir --bin\" ]]; then\n"
                "  printf '%s\\n' \"$HOME\"\n"
                "else exit 1; fi\n"
            )
            uv.chmod(0o755)
            result = subprocess.run(["/bin/bash", str(ROOT / "hooks/scripts/install-graphify.sh")],
                                    env=dict(os.environ, HOME=temp, PATH=temp),
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), str(binary))


if __name__ == "__main__":
    unittest.main()
