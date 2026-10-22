"""Offline characterization tests for the supported runtime entry points."""

from __future__ import annotations

from importlib import import_module

import pytest


@pytest.mark.parametrize(
    ("module_name", "callable_name"),
    [
        ("trendradar.__main__", "main"),
        ("trendradar.ai_frontier.__main__", "main"),
        ("mcp_server.server", "run_server"),
    ],
)
def test_runtime_entrypoint_is_importable(module_name: str, callable_name: str) -> None:
    module = import_module(module_name)

    assert callable(getattr(module, callable_name))
