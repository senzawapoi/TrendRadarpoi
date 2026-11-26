"""Pure, conservative review candidate; never changes a resource budget."""
import math


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def may_trial(
    hours: object = None,
    min_available_mib: object = None,
    all_workloads: object = None,
    worker_explained: object = None,
    other_sli_known: object = None,
    oom: object = None,
) -> bool:
    """Return eligibility for review, not approval or a capacity guarantee.

    Missing, malformed and unknown evidence fails closed. Thresholds are
    conservative candidates that require approval before any production trial.
    """
    return (
        _finite_number(hours)
        and hours >= 6
        and _finite_number(min_available_mib)
        and min_available_mib >= 512
        and all_workloads is True
        and worker_explained is True
        and other_sli_known is True
        and type(oom) is int
        and oom == 0
    )
