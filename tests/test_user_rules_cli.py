"""Run the installed rule commands through their real noninteractive CLI."""
import json
import os
import subprocess
import sys

from test_user_rules import UserRulesCase


class UserRuleCliTests(UserRulesCase):
    def command(self, *arguments, content=None, check=True):
        result = subprocess.run(
            [sys.executable, str(self.runtime / "scripts/gag_dev_team.py"), "rules", *arguments,
             "--project", str(self.project)], input=content, capture_output=True, text=True, timeout=15,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(self.marker, " ".join(result.args))
        return result

    def test_add_review_context_and_remove_work_without_terminal_confirmation(self):
        added = self.command("add", content=self.content)
        self.assertNotIn(self.marker, added.stdout + added.stderr)
        proposed = json.loads(added.stdout)
        self.assertEqual(proposed["rule"]["status"], "pending")
        identifier = proposed["rule"]["id"]
        listed = self.command("list")
        self.assertNotIn(self.marker, listed.stdout + listed.stderr)
        self.assertEqual(len(json.loads(listed.stdout)["rules"]), 1)
        shown = json.loads(self.command("show", identifier).stdout)
        self.assertEqual(shown["rule"]["content"], self.content)
        reviewed = self.command(
            "review", identifier, "--decision", "accept", "--reviewer", "Independent synthetic QA reviewer",
            "--reason", "Compatible synthetic progress preference; plugin obligations remain effective.",
            "--content-digest", proposed["rule"]["content_digest"],
            "--policy-digest", proposed["policy_digest"], "--expected-revision", str(proposed["revision"]),
        )
        self.assertNotIn(self.marker, reviewed.stdout + reviewed.stderr)
        accepted = json.loads(reviewed.stdout)
        context = self.command("context")
        self.assertIn(self.content, context.stdout)
        removed = self.command("remove", identifier, "--expected-revision", str(accepted["revision"]))
        self.assertTrue(json.loads(removed.stdout)["removed"])
        self.assertNotIn(self.marker, self.command("context").stdout)

    def test_policy_inspection_has_no_private_payload_and_stale_review_fails(self):
        proposed = json.loads(self.command("add", content=self.content).stdout)
        policy = json.loads(self.command("policy").stdout)
        self.assertEqual(policy["policy_digest"], proposed["policy_digest"])
        self.assertTrue(policy["manifest"])
        self.assertNotIn(self.marker, json.dumps(policy))
        rejected = self.command(
            "review", proposed["rule"]["id"], "--decision", "accept", "--reviewer", "QA",
            "--reason", "Synthetic stale evidence test.", "--content-digest", "0" * 64,
            "--policy-digest", proposed["policy_digest"], "--expected-revision", str(proposed["revision"]),
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertNotIn(self.marker, rejected.stdout + rejected.stderr)
        self.assertNotIn(self.marker, self.command("context").stdout)

    def test_invalid_input_is_not_echoed_and_creates_no_rule(self):
        invalid = self.content + "\0"
        rejected = self.command("add", content=invalid, check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertNotIn(self.marker, rejected.stdout + rejected.stderr)
        self.assertEqual(json.loads(self.command("list").stdout)["rules"], [])

    def test_node_wrapper_roundtrips_unicode_when_python_locale_is_ascii(self):
        content = "Use português: ação, 漢字 e 🙂."
        environment = dict(os.environ, PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", LC_ALL="C", LANG="C")

        def invoke(*arguments, payload=None):
            result = subprocess.run(
                ["node", str(self.runtime / "bin/gag-dev-team.cjs"), "rules", *arguments,
                 "--project", str(self.project)], input=payload, capture_output=True, env=environment, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            return json.loads(result.stdout.decode("utf-8"))

        proposed = invoke("add", payload=content.encode("utf-8"))
        shown = invoke("show", proposed["rule"]["id"])
        self.assertEqual(shown["rule"]["content"], content)
