#!/usr/bin/env python3
"""Real-workspace Phase 7 evidence runner. Standard library; pytest is external.

This sidecar never writes GSD state, commits, deploys or repairs application code.
The snapshot is an explicit source/input boundary, not the entire machine.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import site
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

VERSION = "0.2.0"
HERE = Path(__file__).resolve().parent
EXIT = {"PASS": 0, "FROZEN": 0, "FAIL": 1, "BLOCKED": 2, "REVIEW_REQUIRED": 3}
OMIT = {"__pycache__", ".pytest_cache", ".ruff_cache", ".git", ".venv", "node_modules"}
FORBIDDEN = {"output", "test/runtime", "dist", ".env"}


class GateError(Exception):
    """A missing or inconsistent piece of required evidence."""


def need(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(value: dict) -> dict:
    value = {k: v for k, v in value.items() if k != "integrity"}
    return {**value, "integrity": digest(value)}


def verified(value: dict, kind: str) -> dict:
    need(isinstance(value, dict) and value.get("kind") == kind, f"expected {kind}")
    need(value == seal(value), "evidence integrity mismatch")
    return value


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects historical evidence even if another writer races us.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def relative(name: str) -> str:
    need(
        isinstance(name, str) and name and "\\" not in name and ":" not in name,
        "paths must be POSIX project-relative names",
    )
    path = PurePosixPath(name)
    need(
        not path.is_absolute() and not any(p in {"", ".", ".."} for p in name.split("/")),
        "path traversal or empty component",
    )
    return name


def confined(root: Path, name: str) -> Path:
    path = root / relative(name)
    need(path.resolve().is_relative_to(root.resolve()), "path escapes project")
    current = path
    while current != root:
        need(not current.is_symlink(), f"input symlink not supported: {name}")
        current = current.parent
    return path


def excluded(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return (
        any(p in OMIT for p in parts)
        or name.endswith((".pyc", ".db", ".db-wal", ".db-shm"))
        or any(name == p or name.startswith(p + "/") for p in FORBIDDEN)
        or (parts[-1].startswith(".env") and parts[-1] != ".env.example")
    )


def snapshot(root: Path, config: dict) -> dict:
    """Hash only declared source trees/files; reject links, never visit runtime roots."""
    result = {}
    entries = set(config["input_roots"]) | set(config["sources"]) | {"phasegate"}
    for entry in sorted(entries):
        need(not excluded(entry), f"protected/runtime input forbidden: {entry}")
        path = confined(root, entry)
        need(path.exists(), f"required input absent: {entry}")
        candidates = [path]
        if path.is_dir():
            candidates = []
            for folder, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [
                    d for d in dirs if not excluded((Path(folder) / d).relative_to(root).as_posix())
                ]
                for d in dirs:
                    confined(root, (Path(folder) / d).relative_to(root).as_posix())
                candidates.extend(Path(folder) / f for f in files)
        for item in candidates:
            name = item.relative_to(root).as_posix()
            if not excluded(name):
                item = confined(root, name)
                need(item.is_file(), f"input not a regular file: {name}")
                result[name] = sha(item)
    return dict(sorted(result.items()))


def selector_exists(root: Path, selector: str) -> bool:
    pieces = selector.split("::")
    path = confined(root, pieces[0])
    if len(pieces) == 1:
        return path.exists()
    if len(pieces) != 2 or not path.is_file():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == pieces[1]
        for node in tree.body
    )


def matches(selector: str, node: str) -> bool:
    return (
        node == selector
        or node.startswith(selector + "[")
        or node.startswith(selector + "::")
        or node.startswith(selector.rstrip("/") + "/")
    )


def load_config(root: Path) -> dict:
    config = read(confined(root, "phasegate/phase7.json"))
    need(config.get("schema") == 1, "unsupported configuration schema")
    need(config.get("project") == "TrendRadarpoi", "wrong project")
    need(len(config.get("sources", [])) >= 2, "project and Phase constraints required")
    for source in config["sources"]:
        need(confined(root, source).is_file(), f"missing constraint source: {source}")
    plan = confined(root, config["plan"]).read_text(encoding="utf-8-sig")
    expected = set(re.findall(r"^\| ((?:ENV|HEALTH|PERM|GUARD|RG|V)-\d{2}) \|", plan, re.M))
    cases = config["cases"]
    ids = [c["id"] for c in cases]
    need(
        len(ids) == len(set(ids)) and set(ids) == expected and len(ids) == 34,
        "case map must cover exactly the plan's 28 offline + 6 target scenarios",
    )
    for case in cases:
        need(
            case.get("source") == config["plan"] and case.get("anchor") in plan,
            f"plan assertion changed or missing: {case['id']}",
        )
        need(case["coverage"] in {"reviewed", "partial", "external"}, "invalid coverage state")
        need(
            case["layers"] and all(x in {"W", "L", "S", "V"} for x in case["layers"]),
            "invalid evidence layers",
        )
        for selector in case["selectors"]:
            need(selector_exists(root, selector), f"missing mapped test: {selector}")
        for layer, selectors in case.get("layer_selectors", {}).items():
            need(layer in case["layers"] and selectors, "invalid per-layer test map")
            for selector in selectors:
                need(selector_exists(root, selector), f"missing layer test: {selector}")
    for name, suite in config["suites"].items():
        need(suite["selectors"], f"empty suite: {name}")
        for selector in suite["selectors"]:
            need(selector_exists(root, selector), f"missing suite selector: {selector}")
    return config


def git_metadata(root: Path) -> dict:
    result = {}
    for key, arguments in {
        "head": ["rev-parse", "HEAD"],
        "status": ["status", "--porcelain", "--untracked-files=normal"],
    }.items():
        try:
            process = subprocess.run(
                ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            result[key] = process.stdout.strip() if process.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            result[key] = None
    result["dirty"] = bool(result["status"]) if result["status"] is not None else None
    return result


def environment() -> dict:
    return {
        "os": platform.system(),
        "release": platform.release(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "machine": platform.machine(),
        "executable": str(Path(sys.executable).resolve()),
        "uid": os.geteuid() if hasattr(os, "geteuid") else None,
        "gid": os.getegid() if hasattr(os, "getegid") else None,
    }


def freeze(root: Path) -> dict:
    config = load_config(root)
    files = snapshot(root, config)
    for name in ("phase7_gate.py", "pytest_evidence.py"):
        need(
            sha(HERE / name) == files.get("phasegate/" + name),
            "invoked runner differs from project runner",
        )
    return seal(
        {
            "kind": "phasegate-real-baseline",
            "schema": 1,
            "version": VERSION,
            "created_at": now(),
            "status": "FROZEN",
            "project": config["project"],
            "root": str(root),
            "config": config,
            "files": files,
            "candidate_id": digest(files),
            "git": git_metadata(root),
            "note": "Frozen source boundary; not semantic coverage approval or phase acceptance.",
        }
    )


def drift(root: Path, baseline: dict) -> list[str]:
    actual = snapshot(root, baseline["config"])
    expected = baseline["files"]
    return sorted(
        name for name in set(actual) | set(expected) if actual.get(name) != expected.get(name)
    )


def classify_events(data: dict, nonce: str, returncode: int, selectors: list[str]) -> dict:
    need(
        data.get("schema") == 1 and data.get("nonce") == nonce and data.get("finished") is True,
        "missing, incomplete or stale pytest event evidence",
    )
    need(data.get("pytest_exit") == returncode, "pytest exit mismatch")
    nodes = data.get("collected", [])
    need(nodes and len(nodes) == len(set(nodes)), "zero or duplicate collected tests")
    need(not data.get("collection_errors"), "pytest collection failed")
    need(not data.get("deselected"), "selected scope was reduced by pytest deselection")
    need(
        all(any(matches(s, n) for n in nodes) for s in selectors),
        "requested selector collected no tests",
    )
    need(all(any(matches(s, n) for s in selectors) for n in nodes), "unexpected collected test")
    grouped = {n: {} for n in nodes}
    for event in data.get("events", []):
        node, when = event.get("nodeid"), event.get("when")
        need(node in grouped and when in {"setup", "call", "teardown"}, "unexpected test event")
        need(when not in grouped[node], "duplicate/rerun test phase is not accepted")
        need(event.get("outcome") in {"passed", "failed", "skipped"}, "invalid test outcome")
        grouped[node][when] = event
    results = {}
    for node, phases in grouped.items():
        if any(p["outcome"] == "failed" for p in phases.values()):
            status = "FAIL" if phases.get("call", {}).get("outcome") == "failed" else "BLOCKED"
        elif any(p["outcome"] == "skipped" or p.get("xfail") for p in phases.values()):
            status = "BLOCKED"
        elif set(phases) == {"setup", "call", "teardown"}:
            status = "PASS"
        else:
            status = "BLOCKED"
        results[node] = {"status": status, "phases": phases}
    status = aggregate([v["status"] for v in results.values()])
    has_failure = any(
        p["outcome"] == "failed" for phases in grouped.values() for p in phases.values()
    )
    execution_valid = returncode in (0, 1) and (returncode == 1) == has_failure
    if not execution_valid:
        status = "BLOCKED"
    return {
        "status": status,
        "execution_valid": execution_valid,
        "tests": results,
        "counts": dict(Counter(v["status"] for v in results.values())),
    }


def aggregate(statuses: list[str]) -> str:
    for status in ("FAIL", "BLOCKED", "REVIEW_REQUIRED"):
        if status in statuses:
            return status
    return "PASS" if statuses else "BLOCKED"


def check_capability(suite: dict, allow_systemd: bool) -> None:
    for capability in suite.get("requires", []):
        if capability == "windows":
            need(sys.platform == "win32", "this suite requires Windows")
        elif capability == "linux":
            need(sys.platform == "linux", "this suite requires Linux; no portable fallback")
        elif capability == "root":
            need(
                hasattr(os, "geteuid") and os.geteuid() == 0,
                "real service UID tests require Linux root",
            )
        elif capability == "systemd":
            need(allow_systemd, "real systemd tests require explicit --allow-systemd")
            need(Path("/proc/1/comm").read_text().strip() == "systemd", "PID 1 is not systemd")
        else:
            raise GateError(f"unknown capability: {capability}")


def clean_environment(arena: Path) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL"}
    }
    for folder in ("home", "temp"):
        (arena / folder).mkdir()
    env.update(
        HOME=str(arena / "home"),
        USERPROFILE=str(arena / "home"),
        TEMP=str(arena / "temp"),
        TMP=str(arena / "temp"),
        TMPDIR=str(arena / "temp"),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        GEMINI_ENABLED="false",
        LARK_ENABLED="false",
        INTELLIGENCE_RESEARCH_ENABLED="false",
    )
    return env


def dependency_paths() -> list[str]:
    """Retain active user-installed packages without restoring the real HOME or credentials."""
    if site.ENABLE_USER_SITE is not True:
        return []
    user_sites = site.getusersitepackages()
    if isinstance(user_sites, str):
        user_sites = [user_sites]
    active = {Path(entry).resolve() for entry in sys.path if entry}
    return [
        str(Path(entry).resolve())
        for entry in user_sites
        if Path(entry).is_dir() and Path(entry).resolve() in active
    ]


def run(root: Path, baseline: dict, suite_name: str, allow_systemd: bool = False) -> dict:
    baseline = verified(baseline, "phasegate-real-baseline")
    need(suite_name in baseline["config"]["suites"], "unknown suite")
    suite = baseline["config"]["suites"][suite_name]
    report = {
        "kind": "phasegate-real-run",
        "schema": 1,
        "version": VERSION,
        "created_at": now(),
        "baseline_id": baseline["integrity"],
        "candidate_id": baseline["candidate_id"],
        "suite": suite_name,
        "selectors": suite["selectors"],
        "environment": environment(),
        "root": str(root),
        "fixture": False,
        "phase7_accepted": False,
        "status": "BLOCKED",
        "execution_valid": False,
        "tests": {},
        "counts": {},
        "findings": [],
    }
    try:
        need(
            not drift(root, baseline),
            "source/contract changed since freeze; create a reviewed new baseline",
        )
        for name in ("phase7_gate.py", "pytest_evidence.py"):
            need(
                sha(HERE / name) == baseline["files"].get("phasegate/" + name),
                "invoked runner differs from frozen runner",
            )
        check_capability(suite, allow_systemd)
        # Real service units cannot see a /tmp source tree when PrivateTmp=yes.
        parent = "/var/lib" if sys.platform == "linux" and os.geteuid() == 0 else None
        arena = Path(tempfile.mkdtemp(prefix="phasegate-run-", dir=parent))
        if os.name == "posix":
            arena.chmod(0o755)
        source = arena / "source"
        source.mkdir()
        for name, expected in baseline["files"].items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(confined(root, name), target)
            need(sha(target) == expected, f"source changed while copying: {name}")
        need(not drift(root, baseline), "original workspace changed while copying")
        nonce = uuid.uuid4().hex
        evidence_path, log_path = arena / "pytest-events.json", arena / "pytest.log"
        command = [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            *suite["selectors"],
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "-p",
            "pytest_evidence",
            "--tb=short",
            "--basetemp",
            str(arena / "cases"),
            "--phasegate-evidence",
            str(evidence_path),
            "--phasegate-nonce",
            nonce,
        ]
        env = clean_environment(arena)
        dependencies = dependency_paths()
        env["PYTHONPATH"] = os.pathsep.join([str(source / "phasegate"), str(source), *dependencies])
        start = time.monotonic()
        report.update(
            arena=str(arena),
            command=command,
            nonce=nonce,
            dependency_paths=dependencies,
            layer="W" if sys.platform == "win32" else "L" if sys.platform == "linux" else "OTHER",
            systemd_evidence="systemd" in suite.get("requires", []),
            isolation="copied declared sources; no runtime/.env; sanitized environment; not an OS network sandbox",
        )
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=source,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
            )
            try:
                code = process.wait(timeout=suite.get("timeout_seconds", 600))
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
                raise GateError(
                    "suite timed out; private arena retained; no passing evidence"
                ) from None
        report.update(
            returncode=code,
            duration_seconds=round(time.monotonic() - start, 3),
            log_path=str(log_path),
            log_sha256=sha(log_path),
        )
        report.update(classify_events(read(evidence_path), nonce, code, suite["selectors"]))
        if not report["execution_valid"]:
            report["findings"].append({"code": "PYTEST_EXIT_INCONSISTENT", "returncode": code})
        report["events_sha256"] = sha(evidence_path)
        changed_copy = drift(source, baseline)
        changed_original = drift(root, baseline)
        if changed_copy or changed_original:
            report["findings"].append(
                {"code": "INPUT_DRIFT", "copy": changed_copy, "original": changed_original}
            )
            report["status"] = "BLOCKED"
    except (GateError, OSError, ValueError, KeyError, TypeError) as exc:
        report["findings"].append({"code": "EVIDENCE_BLOCKED", "reason": str(exc)})
        report["status"] = "BLOCKED"
    return seal(report)


def assess_case(case: dict, reports: list[dict]) -> dict:
    observations = []
    missing = []
    statuses = []
    for layer in case["layers"]:
        for selector in case.get("layer_selectors", {}).get(layer, case["selectors"]):
            eligible = [
                r
                for r in reports
                if r.get("layer") == layer or (layer == "S" and r.get("systemd_evidence"))
            ]
            items = [
                (r, node, value)
                for r in eligible
                for node, value in r["tests"].items()
                if matches(selector, node)
            ]
            selection_covers = any(
                r.get("execution_valid")
                and not r["findings"]
                and any(matches(selected, selector) for selected in r["selectors"])
                and any(matches(selector, node) for node in r["tests"])
                for r in eligible
            )
            if not items or not selection_covers:
                missing.append({"layer": layer, "selector": selector})
            for report, node, result in items:
                state = result["status"]
                if report["findings"] or not report.get("execution_valid"):
                    state = "BLOCKED"
                statuses.append(state)
                observations.append(
                    {
                        "layer": layer,
                        "nodeid": node,
                        "status": state,
                        "report_id": report["integrity"],
                    }
                )
    if missing or not case["selectors"]:
        statuses.append("BLOCKED")
    if case["coverage"] != "reviewed":
        statuses.append("REVIEW_REQUIRED" if case["coverage"] == "partial" else "BLOCKED")
    return {
        "id": case["id"],
        "status": aggregate(statuses),
        "coverage": case["coverage"],
        "coverage_note": case["note"],
        "missing": missing,
        "observations": observations,
    }


def summarize(root: Path, baseline: dict, reports: list[dict]) -> dict:
    baseline = verified(baseline, "phasegate-real-baseline")
    need(reports, "provide at least one current run report")
    for report in reports:
        verified(report, "phasegate-real-run")
        need(
            report["baseline_id"] == baseline["integrity"]
            and report["candidate_id"] == baseline["candidate_id"],
            "mixed baseline/candidate evidence",
        )
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(report["created_at"])
        ).total_seconds()
        need(-5 <= age <= 86400, "run evidence expired or timestamp invalid; rerun selected scope")
    need(len({r["integrity"] for r in reports}) == len(reports), "duplicate report input")
    changes = drift(root, baseline)
    cases = [assess_case(c, reports) for c in baseline["config"]["cases"]]
    offline = [c for c in cases if not c["id"].startswith("V-")]
    state = aggregate(
        [c["status"] for c in cases]
        + [r["status"] for r in reports]
        + (["BLOCKED"] if changes else [])
    )
    return seal(
        {
            "kind": "phasegate-real-summary",
            "schema": 1,
            "created_at": now(),
            "status": state,
            "baseline_id": baseline["integrity"],
            "candidate_id": baseline["candidate_id"],
            "report_ids": sorted(r["integrity"] for r in reports),
            "run_results": [
                {
                    "suite": r["suite"],
                    "status": r["status"],
                    "counts": r["counts"],
                    "layer": r.get("layer"),
                    "duration_seconds": r.get("duration_seconds"),
                }
                for r in reports
            ],
            "offline_status": aggregate([c["status"] for c in offline]),
            "phase7_accepted": False,
            "can_close": False,
            "fixture": False,
            "source_changes": changes,
            "cases": cases,
            "note": "Advisory integration: no new Phase 7 prerequisite. Counts are not semantic coverage. "
            "External acceptance/clean candidate/CI and independent review remain separate.",
        }
    )


def review_packet(root: Path, baseline: dict, summary: dict) -> dict:
    verified(baseline, "phasegate-real-baseline")
    verified(summary, "phasegate-real-summary")
    need(summary["baseline_id"] == baseline["integrity"], "review baseline mismatch")
    need(not drift(root, baseline), "source changed; stale review packet")
    return {
        "kind": "phasegate-real-review-packet",
        "schema": 1,
        "baseline_id": baseline["integrity"],
        "candidate_id": baseline["candidate_id"],
        "summary_id": summary["integrity"],
        "sources": baseline["config"]["sources"],
        "cases": summary["cases"],
        "rules": [
            "Read actual project/Phase rules and mapped assertions, including positive paths.",
            "Separate stale handoff prose from fresh execution; do not declare either automatically correct.",
            "Do not turn skipped/missing/Linux/systemd/VPS evidence into PASS.",
            "Do not override deterministic failures or alter acceptance standards to fit code.",
            "This version exports review context only; it never auto-imports model PASS as phase acceptance.",
        ],
    }


def markdown(value: dict) -> str:
    lines = [
        "# PhaseGate 真实工作区报告",
        "",
        f"- 状态：{value.get('status', 'REVIEW_PACKET')}",
        f"- 候选：`{value.get('candidate_id', '')}`",
        "- 不自动关闭 Phase 7；不修改 GSD。",
        "",
    ]
    if value.get("kind") == "phasegate-real-run":
        lines += [
            f"- Suite：{value['suite']}",
            f"- 结果计数：{value['counts']}",
            f"- 环境：{value['environment']}",
            f"- 隔离目录：{value.get('arena', '未运行')}",
            "",
            "| 测试 | 结果 |",
            "|---|---|",
        ]
        lines += [f"| `{n}` | {r['status']} |" for n, r in value["tests"].items()]
        lines += [
            "",
            "## 执行阻断",
            "",
            json.dumps(value["findings"], ensure_ascii=False, indent=2),
        ]
    if "cases" in value:
        lines += ["| 场景 | 状态 | 断言覆盖 | 说明 |", "|---|---|---|---|"]
        lines += [
            f"| {c['id']} | {c['status']} | {c['coverage']} | {c['coverage_note']} |"
            for c in value["cases"]
        ]
    return "\n".join(lines) + "\n"


def output_path(root: Path, path: Path) -> Path:
    path = path.resolve()
    need(path.suffix == ".json", "output must end with .json")
    if path.is_relative_to(root):
        need(
            path.relative_to(root).parts[0] == ".phasegate",
            "project outputs must be inside .phasegate/",
        )
    need(
        not path.exists() and not path.with_suffix(".md").exists(),
        "output already exists; use a new run name to retain history",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PhaseGate real-workspace sidecar 0.2")
    parser.add_argument(
        "action", choices=["inspect", "freeze", "run", "summarize", "review-packet", "close"]
    )
    parser.add_argument("--root", type=Path, default=HERE.parent)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--suite")
    parser.add_argument("--reports", nargs="+", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--allow-systemd", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if args.action == "inspect":
            config = load_config(root)
            value = {
                "status": "PASS",
                "meaning": "structural map valid; no tests executed",
                "cases": len(config["cases"]),
                "suites": list(config["suites"]),
                "coverage": dict(Counter(c["coverage"] for c in config["cases"])),
            }
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0
        need(args.out is not None, "--out required")
        destination = output_path(root, args.out)
        if args.action == "freeze":
            value = freeze(root)
        else:
            need(args.baseline is not None, "--baseline required")
            baseline = read(args.baseline)
            if args.action == "run":
                need(args.suite is not None, "--suite required")
                value = run(root, baseline, args.suite, args.allow_systemd)
            elif args.action in {"summarize", "close"}:
                need(args.reports is not None, "--reports required")
                value = summarize(root, baseline, [read(p) for p in args.reports])
                if args.action == "close":
                    value = seal(
                        {
                            **value,
                            "status": "BLOCKED",
                            "can_close": False,
                            "reason": "0.2 is an advisory pilot, not an authorized GSD completion adapter",
                        }
                    )
            else:
                need(args.summary is not None, "--summary required")
                value = review_packet(root, baseline, read(args.summary))
        write(destination, value)
        if args.action != "freeze":
            with destination.with_suffix(".md").open("x", encoding="utf-8") as handle:
                handle.write(markdown(value))
        print(
            json.dumps(
                {
                    "status": value.get("status", "REVIEW_PACKET"),
                    "output": str(destination),
                    "counts": value.get("counts"),
                    "phase7_accepted": False,
                },
                ensure_ascii=False,
            )
        )
        return EXIT.get(value.get("status", "PASS"), 2)
    except (GateError, OSError, ValueError, KeyError, TypeError) as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "error": str(exc), "phase7_accepted": False},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
