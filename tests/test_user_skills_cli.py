"""Private skill operations through the installed wrapper; payloads only use stdin."""
import json
import os
import subprocess

from test_user_skills import UserSkillsCase


class UserSkillCliTests(UserSkillsCase):
    def command(self, *arguments, content=None, check=True):
        result = subprocess.run(
            ["node", str(self.runtime / "bin/gag-dev-team.cjs"), "skills", *arguments,
             "--project", str(self.project)], input=content, capture_output=True, text=True, timeout=15,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(self.body_marker, " ".join(result.args))
        self.assertNotIn(self.reference_marker, " ".join(result.args))
        return result

    def review_command(self, proposed):
        return self.command(
            "review", proposed["id"], "--decision", "accept", "--reviewer", "Independent synthetic QA reviewer",
            "--reason", "Synthetic compatible skill preserves mandatory plugin checks.",
            "--content-digest", proposed["content_digest"], "--policy-digest", proposed["policy_digest"],
            "--expected-revision", str(proposed["revision"]),
        )

    def test_explicit_skill_add_review_catalog_load_remove_uses_private_stdin_payloads(self):
        proposed = json.loads(self.command("add", content=json.dumps(self.bundle, ensure_ascii=False)).stdout)
        self.assertNotIn(self.body_marker, json.dumps(proposed))
        self.assertNotIn(self.reference_marker, self.command("list").stdout)
        self.assertNotIn(self.body_marker, self.command("catalog").stdout)
        shown = json.loads(self.command("show", proposed["id"]).stdout)
        self.assertEqual(shown["skill"]["skill_md"], self.bundle["skill_md"])
        accepted = json.loads(self.review_command(proposed).stdout)
        catalog = self.command("catalog")
        self.assertIn("user/short-progress", catalog.stdout)
        self.assertNotIn(self.body_marker, catalog.stdout)
        self.assertNotIn(self.reference_marker, catalog.stdout)
        loaded = json.loads(self.command("load", proposed["id"]).stdout)
        self.assertEqual(loaded["skill"]["skill_md"], self.bundle["skill_md"])
        self.assertEqual(loaded["skill"]["references"], self.bundle["references"])
        self.command("remove", proposed["id"], "--expected-revision", str(accepted["revision"]))
        self.assertNotIn("user/short-progress", self.command("catalog").stdout)

    def test_inferred_skill_needs_literal_clarification_before_a_new_review(self):
        bundle = self.make_bundle(source_kind="inferred")
        proposed = json.loads(self.command("add", content=json.dumps(bundle, ensure_ascii=False)).stdout)
        confirmation = "Synthetic person confirms concise project progress updates."
        confirmed_result = self.command(
            "confirm", proposed["id"], "--content-digest", proposed["content_digest"],
            "--policy-digest", proposed["policy_digest"], "--expected-revision", str(proposed["revision"]),
            content=confirmation,
        )
        self.assertNotIn(confirmation, " ".join(confirmed_result.args))
        confirmed = json.loads(confirmed_result.stdout)
        self.assertEqual(confirmed["status"], "pending")
        self.assertNotIn("user/short-progress", self.command("catalog").stdout)
        self.review_command(confirmed)
        self.assertIn("user/short-progress", self.command("catalog").stdout)

    def test_malformed_json_input_does_not_create_a_partial_skill(self):
        rejected = self.command("add", content="{", check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(json.loads(self.command("list").stdout)["skills"], [])

    def test_skill_and_confirmation_roundtrip_unicode_under_ascii_python_locale(self):
        bundle = self.make_bundle(source_kind="inferred")
        bundle["skill_md"] += "\nAção em português, 漢字 e 🙂.\n"
        bundle["origin"] = "Observação operacional: ação, 漢字 e 🙂."
        confirmation = "Sim, prefiro português: ação, 漢字 e 🙂."
        environment = dict(os.environ, PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", LC_ALL="C", LANG="C")

        def invoke(*arguments, payload=None):
            result = subprocess.run(
                ["node", str(self.runtime / "bin/gag-dev-team.cjs"), "skills", *arguments,
                 "--project", str(self.project)], input=payload, capture_output=True, env=environment, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            return json.loads(result.stdout.decode("utf-8"))

        proposed = invoke("add", payload=json.dumps(bundle, ensure_ascii=False).encode("utf-8"))
        shown = invoke("show", proposed["id"])
        self.assertEqual(shown["skill"]["skill_md"], bundle["skill_md"])
        self.assertEqual(shown["skill"]["origin"], bundle["origin"])
        confirmed = invoke("confirm", proposed["id"], "--expected-revision", str(proposed["revision"]),
                           "--content-digest", proposed["content_digest"], "--policy-digest", proposed["policy_digest"],
                           payload=confirmation.encode("utf-8"))
        self.assertEqual(confirmed["status"], "pending")
        shown = invoke("show", proposed["id"])
        self.assertIn(confirmation, json.dumps(shown, ensure_ascii=False))
