"""Security intelligence collection, analysis, and reporting."""

from trendradar.domains.security.analyzer import (
    SecurityRankingConfig,
    SourceFreshness,
    analyze_security_stories,
    build_source_freshness,
)
from trendradar.domains.security.collector import (
    SecurityRecord,
    SecurityRunSummary,
    extract_cve_ids,
    run_security_pipeline,
)
from trendradar.domains.security.report import (
    prepare_security_report,
    render_security_report,
    save_security_report,
)

__all__ = [
    "SecurityRecord",
    "SecurityRankingConfig",
    "SecurityRunSummary",
    "SourceFreshness",
    "analyze_security_stories",
    "build_source_freshness",
    "extract_cve_ids",
    "prepare_security_report",
    "render_security_report",
    "run_security_pipeline",
    "save_security_report",
]
