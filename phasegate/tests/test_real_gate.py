"""Regression tests for the evidence tool, independent of application fixtures."""

import copy
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import phase7_gate as gate  # noqa: E402 -- standalone stdlib test entrypoint


def events(outcome="passed", when="call", xfail=False):
    return {
        "schema": 1,
        "nonce": "current",
        "finished": True,
        "pytest_exit": 1 if outcome == "failed" else 0,
        "collected": ["tests/test_example.py::test_one"],
        "collection_errors": [],
        "events": [
            {
                "nodeid": "tests/test_example.py::test_one",
                "when": stage,
                "outcome": outcome if stage == when else "passed",
                "xfail": xfail if stage == when else False,
                "duration": 0,
            }
            for stage in ("setup", "call", "teardown")
        ],
    }


class EventTests(unittest.TestCase):
    def classify(self, value):
        return gate.classify_events(
            value, "current", value["pytest_exit"], ["tests/test_example.py"]
        )

    def test_complete_actual_call_passes(self):
        self.assertEqual(self.classify(events())["status"], "PASS")

    def test_call_failure_is_fail(self):
        self.assertEqual(self.classify(events("failed"))["status"], "FAIL")

    def test_setup_failure_is_blocked(self):
        self.assertEqual(self.classify(events("failed", "setup"))["status"], "BLOCKED")

    def test_teardown_failure_is_blocked(self):
        self.assertEqual(self.classify(events("failed", "teardown"))["status"], "BLOCKED")

    def test_skip_is_not_pass(self):
        self.assertEqual(self.classify(events("skipped"))["status"], "BLOCKED")

    def test_xfail_and_xpass_are_not_pass(self):
        for outcome in ("passed", "skipped"):
            self.assertEqual(self.classify(events(outcome, xfail=True))["status"], "BLOCKED")

    def test_missing_call_is_blocked(self):
        value = events()
        value["events"] = [x for x in value["events"] if x["when"] != "call"]
        self.assertEqual(self.classify(value)["status"], "BLOCKED")

    def test_zero_collection_rejected(self):
        value = events()
        value["collected"] = []
        with self.assertRaises(gate.GateError):
            self.classify(value)

    def test_stale_nonce_rejected(self):
        value = events()
        value["nonce"] = "previous"
        with self.assertRaises(gate.GateError):
            self.classify(value)

    def test_incomplete_session_rejected(self):
        value = events()
        value["finished"] = False
        with self.assertRaises(gate.GateError):
            self.classify(value)

    def test_collection_error_rejected(self):
        value = events()
        value["collection_errors"] = ["tests/test_broken.py"]
        with self.assertRaises(gate.GateError):
            self.classify(value)

    def test_duplicate_test_event_rejected(self):
        value = events()
        value["events"].append(dict(value["events"][1]))
        with self.assertRaises(gate.GateError):
            self.classify(value)

    def test_unexpected_collected_test_rejected(self):
        value = events()
        value["collected"].append("other/test_unrequested.py::test_one")
        with self.assertRaises(gate.GateError):
            self.classify(value)

    def test_partial_selector_not_enough(self):
        with self.assertRaises(gate.GateError):
            gate.classify_events(
                events(), "current", 0, ["tests/test_example.py", "tests/test_missing.py"]
            )

    def test_process_nonzero_cannot_become_pass(self):
        value = events()
        value["pytest_exit"] = 1
        self.assertEqual(self.classify(value)["status"], "BLOCKED")

    def test_abnormal_process_exit_invalidates_passing_nodes(self):
        value = events()
        value["pytest_exit"] = 2
        self.assertFalse(self.classify(value)["execution_valid"])

    def test_false_zero_exit_invalidates_failure_evidence(self):
        value = events("failed")
        value["pytest_exit"] = 0
        self.assertFalse(self.classify(value)["execution_valid"])

    def test_deselection_cannot_reduce_required_scope(self):
        value = events()
        value["deselected"] = ["tests/test_example.py::test_two"]
        with self.assertRaisesRegex(gate.GateError, "deselection"):
            self.classify(value)


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "id": "TEST-01",
            "coverage": "reviewed",
            "note": "test-only",
            "layers": ["W", "L"],
            "selectors": ["tests/test_example.py"],
        }
        self.run = {
            "layer": "W",
            "selectors": ["tests/test_example.py"],
            "tests": {"tests/test_example.py::test_one": {"status": "PASS"}},
            "status": "PASS",
            "execution_valid": True,
            "findings": [],
            "integrity": "example",
        }

    def test_windows_cannot_satisfy_linux(self):
        self.assertEqual(gate.assess_case(self.case, [self.run])["status"], "BLOCKED")

    def test_both_required_layers_satisfy_mapped_checks(self):
        linux = {**self.run, "layer": "L"}
        self.assertEqual(gate.assess_case(self.case, [self.run, linux])["status"], "PASS")

    def test_passing_supporting_checks_do_not_close_partial_coverage(self):
        self.case.update(layers=["W"], coverage="partial")
        self.assertEqual(gate.assess_case(self.case, [self.run])["status"], "REVIEW_REQUIRED")

    def test_missing_external_evidence_stays_blocked(self):
        self.case.update(layers=["V"], coverage="external", selectors=[])
        self.assertEqual(gate.assess_case(self.case, [self.run])["status"], "BLOCKED")

    def test_subset_cannot_stand_for_whole_module(self):
        self.case["layers"] = ["W"]
        self.run["selectors"] = ["tests/test_example.py::test_one"]
        self.assertEqual(gate.assess_case(self.case, [self.run])["status"], "BLOCKED")

    def test_health_subset_cannot_stand_for_full_regression(self):
        self.case.update(layers=["W"], selectors=["tests"])
        self.assertEqual(gate.assess_case(self.case, [self.run])["status"], "BLOCKED")

    def test_failed_run_is_not_hidden_by_later_pass(self):
        self.case["layers"] = ["W"]
        failed = copy.deepcopy(self.run)
        failed["tests"]["tests/test_example.py::test_one"]["status"] = "FAIL"
        self.assertEqual(gate.assess_case(self.case, [failed, self.run])["status"], "FAIL")

    def test_source_drift_invalidates_individual_evidence(self):
        self.case["layers"] = ["W"]
        self.run["findings"] = [{"code": "INPUT_DRIFT"}]
        self.assertEqual(gate.assess_case(self.case, [self.run])["status"], "BLOCKED")

    def test_linux_does_not_automatically_prove_systemd(self):
        self.case["layers"] = ["S"]
        self.run["layer"] = "L"
        self.assertEqual(gate.assess_case(self.case, [self.run])["status"], "BLOCKED")

    def test_invalid_execution_cannot_produce_case_pass(self):
        self.case["layers"] = ["W"]
        self.run.update(status="BLOCKED", execution_valid=False)
        self.assertEqual(gate.assess_case(self.case, [self.run])["status"], "BLOCKED")

    def test_unexecuted_full_scope_cannot_promote_passing_subset(self):
        self.case["layers"] = ["W"]
        incomplete = {**self.run, "execution_valid": False, "tests": {}, "status": "BLOCKED"}
        self.run["selectors"] = ["tests/test_example.py::test_one"]
        result = gate.assess_case(self.case, [self.run, incomplete])
        self.assertEqual(result["status"], "BLOCKED")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phasegate-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        for folder in ("app", "tests", "phasegate"):
            (self.root / folder).mkdir()
        for name in ("phase7_gate.py", "pytest_evidence.py"):
            shutil.copy2(TOOL / name, self.root / "phasegate" / name)
        (self.root / "PROJECT.md").write_text("Project rules", encoding="utf-8")
        (self.root / "PLAN.md").write_text("Phase rules", encoding="utf-8")
        (self.root / "app/value.txt").write_text("original", encoding="utf-8")
        (self.root / "tests/test_example.py").write_text(
            "def test_one():\n    assert True\n", encoding="utf-8"
        )
        self.config = {
            "sources": ["PROJECT.md", "PLAN.md"],
            "input_roots": ["app", "tests"],
            "suites": {"sample": {"selectors": ["tests/test_example.py"], "timeout_seconds": 30}},
            "cases": [],
        }

    def baseline(self):
        files = gate.snapshot(self.root, self.config)
        return gate.seal(
            {
                "kind": "phasegate-real-baseline",
                "config": self.config,
                "files": files,
                "candidate_id": gate.digest(files),
            }
        )

    def invoke(self):
        original = tempfile.mkdtemp
        with patch.object(
            gate.tempfile,
            "mkdtemp",
            side_effect=lambda prefix, dir=None: original(prefix=prefix, dir=self.temp.name),
        ):
            return gate.run(self.root, self.baseline(), "sample")

    def test_parent_escape_rejected(self):
        with self.assertRaises(gate.GateError):
            gate.confined(self.root, "../runtime.db")

    def test_protected_runtime_is_not_hashed(self):
        (self.root / "output").mkdir()
        (self.root / "output/secret.db").write_text("private")
        self.assertNotIn("output/secret.db", gate.snapshot(self.root, self.config))

    def test_credential_file_is_excluded(self):
        (self.root / "app/.env").write_text("SECRET=private")
        self.assertNotIn("app/.env", gate.snapshot(self.root, self.config))

    def test_new_source_invalidates_baseline(self):
        baseline = self.baseline()
        (self.root / "app/new.py").write_text("pass")
        self.assertIn("app/new.py", gate.drift(self.root, baseline))

    def test_contract_edit_invalidates_baseline(self):
        baseline = self.baseline()
        (self.root / "PLAN.md").write_text("changed standard")
        self.assertIn("PLAN.md", gate.drift(self.root, baseline))

    def test_deleted_source_invalidates_baseline(self):
        baseline = self.baseline()
        (self.root / "app/value.txt").unlink()
        self.assertIn("app/value.txt", gate.drift(self.root, baseline))

    def test_evidence_overwrite_refused(self):
        output = self.root / ".phasegate/existing.json"
        gate.write(output, {})
        with self.assertRaises(gate.GateError):
            gate.output_path(self.root, output)

    def test_write_itself_refuses_overwrite(self):
        output = self.root / ".phasegate/existing.json"
        gate.write(output, {"original": True})
        with self.assertRaises(FileExistsError):
            gate.write(output, {"replacement": True})
        self.assertEqual(gate.read(output), {"original": True})

    def test_report_cannot_overwrite_source(self):
        with self.assertRaises(gate.GateError):
            gate.output_path(self.root, self.root / "app/source.json")

    def test_report_integrity_detects_tampering(self):
        value = self.baseline()
        value["candidate_id"] = "changed"
        with self.assertRaises(gate.GateError):
            gate.verified(value, "phasegate-real-baseline")

    def test_environment_drops_live_credentials(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "private",
                "LARK_APP_SECRET": "private",
                "PYTEST_ADDOPTS": "-k nothing",
            },
        ):
            clean = gate.clean_environment(Path(self.temp.name))
        self.assertNotIn("GEMINI_API_KEY", clean)
        self.assertNotIn("LARK_APP_SECRET", clean)
        self.assertNotIn("PYTEST_ADDOPTS", clean)

    def test_only_active_user_packages_are_retained(self):
        user_site = str(Path(self.temp.name).resolve())
        with (
            patch.object(gate.site, "ENABLE_USER_SITE", True),
            patch.object(gate.site, "getusersitepackages", return_value=user_site),
            patch.object(gate.sys, "path", [user_site]),
        ):
            self.assertEqual(gate.dependency_paths(), [user_site])
        with (
            patch.object(gate.site, "ENABLE_USER_SITE", True),
            patch.object(gate.site, "getusersitepackages", return_value=user_site),
            patch.object(gate.sys, "path", []),
        ):
            self.assertEqual(gate.dependency_paths(), [])

    def test_disabled_user_site_is_not_added(self):
        with patch.object(gate.site, "ENABLE_USER_SITE", False):
            self.assertEqual(gate.dependency_paths(), [])

    @unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest required for integration")
    def test_actual_user_dependency_survives_home_isolation(self):
        user_site = Path(self.temp.name) / "user-packages"
        user_site.mkdir()
        (user_site / "phasegate_sample_dependency.py").write_text("VALUE = 42\n", encoding="utf-8")
        (self.root / "tests/test_example.py").write_text(
            "import phasegate_sample_dependency\ndef test_one():\n"
            "    assert phasegate_sample_dependency.VALUE == 42\n",
            encoding="utf-8",
        )
        with (
            patch.object(gate.site, "ENABLE_USER_SITE", True),
            patch.object(gate.site, "getusersitepackages", return_value=str(user_site)),
            patch.object(gate.sys, "path", [*sys.path, str(user_site)]),
        ):
            result = self.invoke()
        self.assertEqual(result["status"], "PASS", result["findings"])
        self.assertEqual(result["dependency_paths"], [str(user_site.resolve())])

    @unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest required for integration")
    def test_real_pytest_event_capture_and_source_isolation(self):
        result = self.invoke()
        self.assertEqual(result["status"], "PASS", result["findings"])
        self.assertEqual(result["counts"], {"PASS": 1})
        self.assertFalse(result["fixture"])
        self.assertFalse(result["phase7_accepted"])
        self.assertNotEqual(Path(result["arena"]), self.root)

    @unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest required for integration")
    def test_actual_input_mutation_blocks_and_original_survives(self):
        (self.root / "tests/test_example.py").write_text(
            "from pathlib import Path\ndef test_one():\n"
            "    Path('app/value.txt').write_text('mutated')\n",
            encoding="utf-8",
        )
        result = self.invoke()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual((self.root / "app/value.txt").read_text(), "original")
        self.assertEqual(result["findings"][0]["code"], "INPUT_DRIFT")

    @unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest required for integration")
    def test_actual_skipped_test_blocks(self):
        (self.root / "tests/test_example.py").write_text(
            "import pytest\ndef test_one():\n    pytest.skip('required missing environment')\n"
        )
        result = self.invoke()
        self.assertEqual(result["status"], "BLOCKED")

    @unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest required for integration")
    def test_actual_failure_is_fail(self):
        (self.root / "tests/test_example.py").write_text("def test_one():\n    assert False\n")
        result = self.invoke()
        self.assertEqual(result["status"], "FAIL")

    @unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest required for integration")
    def test_actual_abnormal_session_exit_blocks_passing_case(self):
        (self.root / "tests/conftest.py").write_text(
            "def pytest_sessionfinish(session):\n    session.exitstatus = 2\n", encoding="utf-8"
        )
        result = self.invoke()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["execution_valid"])

    @unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest required for integration")
    def test_actual_deselection_blocks_partial_collection(self):
        (self.root / "tests/test_example.py").write_text(
            "def test_one():\n    assert True\ndef test_two():\n    assert True\n", encoding="utf-8"
        )
        (self.root / "tests/conftest.py").write_text(
            "def pytest_collection_modifyitems(config, items):\n"
            "    removed = items.pop()\n    config.hook.pytest_deselected(items=[removed])\n",
            encoding="utf-8",
        )
        result = self.invoke()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("deselection", result["findings"][0]["reason"])

    def test_expired_report_rejected(self):
        baseline = self.baseline()
        report = gate.seal(
            {
                "kind": "phasegate-real-run",
                "baseline_id": baseline["integrity"],
                "candidate_id": baseline["candidate_id"],
                "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            }
        )
        with self.assertRaisesRegex(gate.GateError, "expired"):
            gate.summarize(self.root, baseline, [report])

    def test_mixed_candidate_rejected(self):
        baseline = self.baseline()
        report = gate.seal(
            {
                "kind": "phasegate-real-run",
                "baseline_id": baseline["integrity"],
                "candidate_id": "another-candidate",
            }
        )
        with self.assertRaisesRegex(gate.GateError, "mixed"):
            gate.summarize(self.root, baseline, [report])


if __name__ == "__main__":
    unittest.main()
