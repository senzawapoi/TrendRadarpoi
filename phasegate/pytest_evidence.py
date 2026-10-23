"""Capture actual pytest collection and all three runtest phases, without tracebacks."""

import json
from pathlib import Path

_STATE = {}


def pytest_addoption(parser):
    parser.addoption("--phasegate-evidence", required=False)
    parser.addoption("--phasegate-nonce", required=False)


def pytest_sessionstart(session):
    _STATE.clear()
    _STATE.update(
        schema=1,
        nonce=session.config.getoption("--phasegate-nonce"),
        collected=[],
        events=[],
        collection_errors=[],
        deselected=[],
        finished=False,
    )


def pytest_collection_finish(session):
    _STATE["collected"] = [item.nodeid for item in session.items]


def pytest_collectreport(report):
    if report.failed:
        _STATE["collection_errors"].append(report.nodeid)


def pytest_deselected(items):
    _STATE["deselected"].extend(item.nodeid for item in items)


def pytest_runtest_logreport(report):
    _STATE["events"].append(
        {
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "xfail": hasattr(report, "wasxfail"),
            "duration": report.duration,
        }
    )


def pytest_sessionfinish(session, exitstatus):
    path = session.config.getoption("--phasegate-evidence")
    if path:
        _STATE.update(finished=True, pytest_exit=int(exitstatus))
        Path(path).write_text(json.dumps(_STATE, ensure_ascii=False, indent=2), encoding="utf-8")
