"""Offline Linux fresh-process pure SDK import measurement; no client creation."""
import hashlib
import importlib
import importlib.metadata
import json
import os
import sys
import time
from pathlib import Path


def profile_import() -> dict:
    """Measure Linux ru_maxrss high-water marks, never private/current RSS."""
    if sys.platform != "linux":
        raise RuntimeError("Linux required: ru_maxrss units must be KiB")
    if any(name == "lark_oapi" or name.startswith("lark_oapi.") for name in sys.modules):
        raise RuntimeError("fresh process required: lark_oapi is already imported")
    import resource

    version = importlib.metadata.version("lark-oapi")
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.process_time()
    importlib.import_module("lark_oapi")
    process_cpu_seconds = time.process_time() - started
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    root = Path(__file__).resolve().parents[2]
    return {
        "schema_version": 1,
        "platform": "linux",
        "rss_unit": "KiB",
        "rss_measurement": "ru_maxrss process high-water mark; not private footprint",
        "ru_maxrss_before_kib": before,
        "ru_maxrss_after_kib": after,
        "ru_maxrss_delta_kib": after - before,
        "process_cpu_seconds": process_cpu_seconds,
        "lark_oapi_version": version,
        "lark_modules_count": sum(
            name == "lark_oapi" or name.startswith("lark_oapi.") for name in sys.modules
        ),
        "pid": os.getpid(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "requirements_lock_sha256": hashlib.sha256(
            (root / "requirements.lock").read_bytes()
        ).hexdigest(),
    }


if __name__ == "__main__":
    print(json.dumps(profile_import(), sort_keys=True, allow_nan=False))
