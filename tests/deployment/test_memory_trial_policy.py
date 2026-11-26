"""Offline candidate policy: unknown prerequisites always keep the current budget."""
import importlib.util
import math
import sys
from pathlib import Path

import pytest

from scripts.ops.memory_trial_policy import may_trial

VALID = {"hours": 6, "min_available_mib": 512, "all_workloads": True,
             "worker_explained": True, "other_sli_known": True, "oom": 0}


@pytest.mark.parametrize("hours,available", [(6, 512), (12, 736), (6.5, 512.25)])
def test_complete_review_candidate(hours, available):
    assert may_trial(**(VALID | {"hours": hours, "min_available_mib": available})) is True


@pytest.mark.parametrize("changes", [
    {"hours": 5.99}, {"min_available_mib": 511.99}, {"all_workloads": False},
    {"worker_explained": False}, {"other_sli_known": False}, {"oom": 1},
    {"hours": 12, "min_available_mib": 736, "other_sli_known": False},
    # A skipped AI attempt is not actual AI workload coverage.
    {"all_workloads": None},
])
def test_incomplete_or_failed_prerequisites(changes):
    assert may_trial(**(VALID | changes)) is False


@pytest.mark.parametrize("key", ["hours", "min_available_mib"])
@pytest.mark.parametrize("value", [None, True, False, "12", "", -1, math.inf,
                                   -math.inf, math.nan, [], {}, 10**1000])
def test_invalid_numeric_inputs_fail_closed(key, value):
    assert may_trial(**(VALID | {key: value})) is False


@pytest.mark.parametrize("key", ["all_workloads", "worker_explained", "other_sli_known"])
@pytest.mark.parametrize("value", [None, False, 1, 0, "true", [], {}, math.nan])
def test_only_exact_true_proves_prerequisite(key, value):
    assert may_trial(**(VALID | {key: value})) is False


@pytest.mark.parametrize("value", [None, True, False, -1, 1, 0.0, "0",
                                   math.nan, math.inf, [], {}])
def test_oom_requires_nonnegative_integer_zero(value):
    assert may_trial(**(VALID | {"oom": value})) is False


def test_missing_inputs_fail_closed():
    assert may_trial() is False
    for key in VALID:
        assert may_trial(**{k: v for k, v in VALID.items() if k != key}) is False


def test_profile_import_has_no_sdk_side_effect(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/ops/profile_sdk_import.py"
    before = {name for name in sys.modules if name == "lark_oapi"
              or name.startswith("lark_oapi.")}
    spec = importlib.util.spec_from_file_location("offline_sdk_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {name for name in sys.modules if name == "lark_oapi"
            or name.startswith("lark_oapi.")} == before
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(RuntimeError, match="Linux"):
        module.profile_import()


def test_profile_linux_output_contract(monkeypatch):
    import resource
    from types import SimpleNamespace

    from scripts.ops import profile_sdk_import as profile

    # Pure fakes: never import the real SDK in a test process.
    for name in list(sys.modules):
        if name == "lark_oapi" or name.startswith("lark_oapi."):
            monkeypatch.delitem(sys.modules, name)
    rss = iter([100, 125])
    monkeypatch.setattr(resource, "getrusage",
                        lambda who: SimpleNamespace(ru_maxrss=next(rss)))
    monkeypatch.setattr(profile.importlib.metadata, "version", lambda name: "test-version")
    calls = []

    def fake_import(name):
        calls.append(name)
        monkeypatch.setitem(sys.modules, name, SimpleNamespace())

    monkeypatch.setattr(profile.importlib, "import_module", fake_import)
    result = profile.profile_import()
    assert calls == ["lark_oapi"]
    assert result["rss_unit"] == "KiB"
    assert result["platform"] == "linux"
    assert result["lark_oapi_version"] == "test-version"
    assert result["ru_maxrss_before_kib"] == 100
    assert result["ru_maxrss_after_kib"] == 125
    assert result["ru_maxrss_delta_kib"] == 25
    assert result["lark_modules_count"] == 1
    assert type(result["process_cpu_seconds"]) is float
    assert result["process_cpu_seconds"] >= 0
    with pytest.raises(RuntimeError, match="fresh process"):
        profile.profile_import()
