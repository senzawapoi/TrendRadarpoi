"""Construction of the optional research gateway from runtime settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .agent_reach import AgentReachAdapter
from .gateway import ResearchGateway
from .models import CAPABILITIES, ResearchPolicy

if TYPE_CHECKING:
    from trendradar.core.settings import RuntimeSettings


def build_research_gateway(settings: RuntimeSettings) -> ResearchGateway:
    config = settings.intelligence_research_config
    capabilities = frozenset(
        value for value in config.get("capabilities", ()) if value in CAPABILITIES
    )
    policy = ResearchPolicy(
        enabled=bool(config.get("enabled", False)),
        capabilities=capabilities,
        timeout_seconds=int(config.get("timeout_seconds", 15)),
        max_results=int(config.get("max_results", 5)),
        max_result_chars=int(config.get("max_result_chars", 3000)),
        max_response_bytes=int(config.get("max_response_bytes", 262_144)),
        max_concurrency=int(config.get("max_concurrency", 2)),
    )
    # The adapter is lazy at the capability boundary. It does not inspect the
    # machine, install tools, read credentials, or make network calls here.
    return ResearchGateway(
        AgentReachAdapter(github_token=settings.intelligence_research_github_token)
        if policy.enabled else None,
        policy=policy,
    )


__all__ = ["build_research_gateway"]
