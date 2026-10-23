import json

import pytest

from trendradar.ops import maintenance


def test_finalize_exposes_only_finite_clock_and_normalized_timestamps():
    error = maintenance.FinalizeHealthError({
        "status": "unhealthy", "errors": ["future_heartbeat:bot"],
        "heartbeats": {
            "bot": {"age_seconds": -0.125, "updated_at": "2026-10-23T10:00:00+08:00",
                    "sampled_at": "private must-not-print", "token": "must-not-print"},
            "worker": {"age_seconds": float("nan")},
            "must-not-print": {"age_seconds": 1},
        },
    })
    assert error.diagnostics["heartbeat_clocks"] == {
        "bot": {"age_seconds": -0.125, "updated_at": "2026-10-23T02:00:00+00:00"},
    }
    assert "must-not-print" not in json.dumps(error.diagnostics)


@pytest.mark.parametrize("error", [
    OSError(2, "private path and credential must-not-print"),
    RuntimeError("private provider details must-not-print"),
    maintenance.FinalizeHealthError({
        "status": "unhealthy", "errors": ["missing_heartbeat:must-not-print"],
        "warnings": ["stale_source:must-not-print"],
    }),
])
def test_finalize_cli_reports_bounded_diagnostics_without_secret(error, monkeypatch, capsys):
    def fail(_database):
        raise error

    monkeypatch.setattr(maintenance, "finalize_deployment", fail)
    assert maintenance.main(["finalize-deployment", "--database", "unused.db"]) == 2
    output = capsys.readouterr().out
    assert "must-not-print" not in output
    result = json.loads(output)
    assert result["error"] == "finalize_confirmation_failed"
    assert result["error_type"] == type(error).__name__
    if isinstance(error, maintenance.FinalizeHealthError):
        assert result["health"] == {"status": "unhealthy", "errors": ["missing_heartbeat"],
                                    "warnings": ["stale_source"]}
