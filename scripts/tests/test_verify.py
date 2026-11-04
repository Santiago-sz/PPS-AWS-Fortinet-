"""Pruebas del contrato del runner: fallos, aislamiento y evidencia."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "verify.py"
spec = importlib.util.spec_from_file_location("verify", SCRIPT)
verify = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify
spec.loader.exec_module(verify)


class VerificationTests(unittest.TestCase):
    def test_environment_replaces_credentials_and_disables_metadata(self):
        with patch.dict(
            os.environ,
            {
                "AWS_PROFILE": "real",
                "AWS_SESSION_TOKEN": "secret",
                "AWS_ACCESS_KEY_ID": "real",
                "PYTHONPATH": "other",
            },
        ):
            env = verify.verification_env()
        self.assertNotIn("AWS_PROFILE", env)
        self.assertNotIn("AWS_SESSION_TOKEN", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["AWS_ACCESS_KEY_ID"], "testing")
        self.assertEqual(env["AWS_EC2_METADATA_DISABLED"], "true")
        self.assertEqual(env["AWS_SHARED_CREDENTIALS_FILE"], os.devnull)

    def test_real_child_failure_is_recorded(self):
        step = verify.Step(
            "failure",
            ".",
            (sys.executable, "-c", "print('evidence'); raise SystemExit(7)"),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = verify.run_step(step, Path(directory), 10)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["returncode"], 7)
            self.assertIn("evidence", Path(result["log"]).read_text())

    def test_missing_tool_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = verify.run_step(
                verify.Step("missing", ".", ("pps-nonexistent-tool-572",)),
                Path(directory),
                10,
            )
            self.assertEqual(result["status"], "unavailable")

    def test_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            step = verify.Step(
                "timeout", ".", (sys.executable, "-c", "import time; time.sleep(30)")
            )
            result = verify.run_step(step, Path(directory), 0.05)
            self.assertEqual(result["status"], "timeout")

    def test_failure_does_not_skip_remaining_steps_and_sets_exit_code(self):
        steps = [
            verify.Step("first", ".", ("unused",)),
            verify.Step("second", ".", ("unused",)),
        ]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(verify, "profiles", return_value={"sample": steps}),
            patch.object(
                verify,
                "run_step",
                side_effect=[{"status": "failed"}, {"status": "passed"}],
            ) as run,
        ):
            self.assertEqual(verify.main(["sample", "--report-dir", directory]), 1)
            self.assertEqual(run.call_count, 2)
            report = json.loads((Path(directory) / "verification.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(len(report["steps"]), 2)

    def test_list_is_read_only_and_unknown_profile_is_rejected(self):
        with patch.object(verify, "run_step") as run:
            self.assertEqual(verify.main(["pipeline", "--list"]), 0)
            run.assert_not_called()
            with self.assertRaises(SystemExit) as error:
                verify.main(["unknown"])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
