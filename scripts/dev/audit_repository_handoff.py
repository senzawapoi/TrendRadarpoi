"""Inventory two worktrees without copying files or exposing matched secret values."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PATTERNS = {
    "google_api_key": r"AIza[0-9A-Za-z_-]{30,}",
    "github_token": r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
    "aws_access_key": r"(?:AKIA|ASIA)[A-Z0-9]{16}",
    "slack_token": r"xox[baprs]-[A-Za-z0-9-]{20,}",
    "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "credential_assignment": (
        r"(?i)(?:api[_-]?key|app[_-]?secret|access[_-]?token|password)"
        r"\s*[=:]\s*[\"']?[A-Za-z0-9_./+-]{24,}"
    ),
    "webhook": r"https://(?:hooks\.slack\.com/services|open\.(?:feishu|larksuite)\.com"
    r"/open-apis/bot/v2/hook)/[A-Za-z0-9_/-]{20,}",
}
SECRET_PATTERNS = {name: re.compile(pattern) for name, pattern in PATTERNS.items()}
DEFERRED_QUOTE = {
    "trendradar/ai/tools.py", "trendradar/ai/assistant.py", "trendradar/ai/models.py",
    "trendradar/integrations/feishu/models.py", "trendradar/integrations/feishu/handler.py",
    "trendradar/integrations/feishu/client.py", "trendradar/integrations/feishu/reply_context.py",
    "tests/ai/test_tool_recovery.py", "tests/ai/test_quoted_context.py",
    "tests/integrations/feishu/test_client.py",
    "tests/integrations/feishu/test_reply_context.py",
    "tests/integrations/feishu/test_quoted_replies.py",
    "docs/lark-reply-tool-fix-20261023.md",
}


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(root), *args],
        check=True, capture_output=True,
    ).stdout


def paths(root: Path, *args: str) -> list[str]:
    return sorted(filter(None, git(root, *args, "-z").decode("utf-8").split("\0")))


def normalized(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha(data: bytes) -> str:
    return hashlib.sha256(normalized(data)).hexdigest()


def decision(path: str, comparison: str) -> str:
    if path.startswith((".phasegate/", "phase-gate-demo/")) or path.endswith(".zip"):
        return "exclude_local_generated_or_demo"
    if path.startswith("phasegate/"):
        return "migrate_real_phasegate" if comparison != "missing" else "review_missing_gate"
    if path in DEFERRED_QUOTE:
        return "defer_quote_tool_port_per_owner_keep_old_tree_intact"
    if comparison == "same_lf":
        return "already_retained_identical"
    if path.startswith((".planning/", "conductor/")) or path.startswith("TrendRadarpoi_"):
        return "retain_current_reviewed_plan_or_historical_record"
    if path.startswith("docs/phase7-actual-gap-evidence/"):
        return "retain_current_historical_evidence_do_not_replace"
    if path in {"AGENTS.md", "CLAUDE.md", "README.md", "README-EN.md", ".windsurfrules"}:
        return "retain_current_constraints_and_documentation"
    if path.startswith(("test/", "docs/")):
        return "retain_current_documentation_or_historical_uat"
    return "retain_phase7_implementation_no_bulk_merge"


def scan(root: Path, selected: list[str]) -> dict:
    findings = []
    unreadable = []
    binary = []
    large = []
    text_count = 0
    sensitive_paths = []
    for relative in selected:
        file = root / relative
        if file.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3"}:
            sensitive_paths.append(relative)
        if file.name == ".env" or file.name.endswith((".db-wal", ".db-shm")):
            sensitive_paths.append(relative)
        try:
            data = file.read_bytes()
        except OSError as exc:
            unreadable.append({"path": relative, "error": type(exc).__name__})
            continue
        if len(data) > 1024 * 1024:
            large.append({"path": relative, "bytes": len(data)})
        try:
            encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            text = data.decode(encoding)
        except UnicodeDecodeError:
            binary.append(relative)
            continue
        text_count += 1
        for number, line in enumerate(text.splitlines(), 1):
            for category, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    findings.append({"path": relative, "line": number, "category": category})
    return {
        "selected_files": len(selected), "scanned_text_files": text_count,
        "binary_files": binary, "unreadable": unreadable, "findings": findings,
        "sensitive_paths": sorted(set(sensitive_paths)), "over_1_mib": large,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    old = args.old.resolve(strict=True)
    current = args.current.resolve(strict=True)
    output = args.out.resolve()
    output.relative_to(current / "docs")
    if output.exists():
        parser.error("Use a new output name; existing evidence is never overwritten")
    old_modified = paths(old, "diff", "--name-only", "HEAD")
    old_new = paths(old, "ls-files", "--others", "--exclude-standard")
    entries = []
    for relative in sorted(set(old_modified + old_new)):
        old_data = (old / relative).read_bytes()
        target = current / relative
        new_data = target.read_bytes() if target.is_file() else None
        comparison = ("missing" if new_data is None else
                      "same_lf" if normalized(old_data) == normalized(new_data) else "different")
        entries.append({
            "path": relative, "old_state": "modified" if relative in old_modified else "untracked",
            "old_sha256_lf": sha(old_data), "comparison": comparison,
            "current_sha256_lf": sha(new_data) if new_data is not None else None,
            "decision": decision(relative, comparison),
        })
    current_modified = paths(current, "diff", "--name-only", "HEAD")
    current_new = paths(current, "ls-files", "--others", "--exclude-standard")
    current_all = sorted(set(paths(current, "ls-files") + current_new))
    report = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Content inventory and decision register; not a claim of semantic equivalence",
        "hash_normalization": "SHA256 of bytes with CRLF replaced by LF",
        "old_head": git(old, "rev-parse", "HEAD").decode().strip(),
        "current_head": git(current, "rev-parse", "HEAD").decode().strip(),
        "current_branch": git(current, "branch", "--show-current").decode().strip(),
        "old_counts": {"modified": len(old_modified), "untracked": len(old_new)},
        "decisions": dict(Counter(entry["decision"] for entry in entries)),
        "old_entries": entries,
        "current_candidates": [
            {"path": path, "sha256_lf": sha((current / path).read_bytes())}
            for path in sorted(set(current_modified + current_new))
        ],
        "old_security": scan(old, sorted(set(old_modified + old_new))),
        "current_security": scan(current, current_all),
        "limitations": [
            "Regex matches require human adjudication; values are never emitted",
            "Git history, ignored runtime, remote secrets and non-UTF8/UTF16 files are not scanned",
            "Current candidate inventory excludes this newly generated report itself",
            "Retained differing files require area-specific reasoning in the companion handoff",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(output), "old_counts": report["old_counts"],
        "decisions": report["decisions"], "current_candidates": len(report["current_candidates"]),
        "old_security": report["old_security"], "current_security": report["current_security"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
