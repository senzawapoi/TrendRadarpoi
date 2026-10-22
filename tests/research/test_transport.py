from __future__ import annotations

import sys
import time

from trendradar.research.transport import ProcessOutput, run_fixed_process


def test_process_timeout_kills_and_reaps_child():
    started = time.monotonic()
    result = run_fixed_process(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(10)"],
        timeout=0.1,
        max_output_bytes=4096,
    )
    assert result.timed_out
    assert time.monotonic() - started < 3
    assert "started" in result.stdout


def test_process_output_limit_kills_and_bounds_output():
    result = run_fixed_process(
        [sys.executable, "-c", "print('x' * 100000)"],
        timeout=5,
        max_output_bytes=4096,
    )
    assert result.output_limited
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 4096


def test_injected_process_boundary_receives_fixed_safe_contract(tmp_path):
    captured = {}

    def runner(**kwargs):
        captured.update(kwargs)
        return ProcessOutput(0, "{}", "")

    result = run_fixed_process(
        ["gh", "search", "repos", "--", "literal"],
        timeout=3,
        max_output_bytes=4096,
        cwd=tmp_path,
        runner=runner,
    )
    assert result.stdout == "{}"
    assert captured["shell"] is False
    assert captured["argv"][-1] == "literal"
    assert "GEMINI_API_KEY" not in captured["env"]
    assert "LARK_APP_SECRET" not in captured["env"]
