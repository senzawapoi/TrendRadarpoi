"""Bounded process and HTTP primitives for the optional research adapter."""

from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessOutput:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_limited: bool = False


def _safe_environment(
    home: str | Path,
    *,
    github_auth: bool = False,
    github_config_dir: str | Path | None = None,
    github_token: str | None = None,
) -> dict[str, str]:
    """Pass neutral settings plus the explicitly allowed GitHub auth boundary."""
    path = os.environ.get("PATH", "")
    environment = {
        "PATH": path,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", str(Path(home) / "tmp")),
        "TMP": os.environ.get("TMP", str(Path(home) / "tmp")),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GH_CONFIG_DIR": str(github_config_dir or Path(home) / "gh"),
        "YTDLP_NO_UPDATE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    if github_auth:
        if github_token is not None:
            if not isinstance(github_token, str) or not github_token.strip() or "\x00" in github_token:
                raise ValueError("invalid GitHub token")
            environment["GH_TOKEN"] = github_token
    return environment


def run_fixed_process(
    argv: Sequence[str], *, timeout: float, max_output_bytes: int,
    cwd: str | Path | None = None, home: str | Path | None = None,
    github_auth: bool = False,
    github_token: str | None = None,
    runner: Callable[..., ProcessOutput] | None = None,
) -> ProcessOutput:
    """Run a pre-built argv without a shell and enforce a hard output/deadline bound."""
    if not argv or any(not isinstance(value, str) for value in argv):
        raise ValueError("argv must contain strings")
    if timeout <= 0 or max_output_bytes < 1024:
        raise ValueError("invalid process bounds")
    if github_token is not None:
        github_auth = True
    temp_home = None
    try:
        if home is None:
            temp_home = tempfile.TemporaryDirectory(prefix="trendradar-research-")
            home = temp_home.name
        # GitHub auth is explicit. The child must not read the caller's gh
        # profile, even when the host has one configured.
        github_config_dir = Path(home) / "gh"
        process_kwargs = {
            "args": list(argv),
            "cwd": str(cwd) if cwd is not None else str(home),
            "env": _safe_environment(
                home,
                github_auth=github_auth,
                github_config_dir=github_config_dir,
                github_token=github_token,
            ),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
        }
        if runner is not None:
            completed = runner(
                argv=list(argv),
                cwd=process_kwargs["cwd"],
                env=process_kwargs["env"],
                capture_output=True,
                text=False,
                shell=False,
                timeout=timeout,
                check=False,
            )
            stdout = completed.stdout or b""
            stderr = completed.stderr or b""
            if isinstance(stdout, str):
                stdout = stdout.encode()
            if isinstance(stderr, str):
                stderr = stderr.encode()
            limited = len(stdout) + len(stderr) > max_output_bytes
            if len(stdout) + len(stderr) > max_output_bytes:
                stdout = stdout[:max_output_bytes]
                stderr = stderr[:max(0, max_output_bytes - len(stdout))]
            return ProcessOutput(
                int(completed.returncode),
                bytes(stdout).decode("utf-8", errors="replace"),
                bytes(stderr).decode("utf-8", errors="replace"),
                output_limited=limited,
            )
        process = subprocess.Popen(**process_kwargs)
        stdout_output = bytearray()
        stderr_output = bytearray()
        total_output = 0
        lock = threading.Lock()
        limited = threading.Event()

        def drain(stream, target: bytearray) -> None:
            nonlocal total_output
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                with lock:
                    remaining = max_output_bytes - total_output
                    if remaining > 0:
                        target.extend(chunk[:remaining])
                        total_output += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        limited.set()

        readers = [
            threading.Thread(target=drain, args=(process.stdout, stdout_output), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr_output), daemon=True),
        ]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + timeout
        timed_out = False
        while process.poll() is None:
            if limited.is_set():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            time.sleep(min(0.01, remaining))
        if process.poll() is None:
            process.kill()
        returncode = process.wait()
        for reader in readers:
            reader.join(timeout=1)
        with lock:
            stdout = bytes(stdout_output)
            stderr = bytes(stderr_output)
        return ProcessOutput(
            returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            timed_out=timed_out,
            output_limited=limited.is_set(),
        )
    finally:
        if temp_home is not None:
            temp_home.cleanup()


class FixedHttpClient:
    """HTTP client that refuses redirects and caps bytes before decoding."""

    def __init__(self, *, opener: urllib.request.OpenerDirector | None = None) -> None:
        self._isolated = opener is None
        self._opener = opener or urllib.request.build_opener(_NoRedirectHandler())

    def get(self, url: str, *, timeout: float, max_bytes: int) -> bytes:
        if timeout <= 0 or max_bytes < 1:
            raise ValueError("invalid HTTP bounds")
        if self._isolated:
            return self._get_isolated(url, timeout=timeout, max_bytes=max_bytes)
        result: queue.Queue[tuple[bytes | None, BaseException | None]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result.put((self._get(url, timeout=timeout, max_bytes=max_bytes), None))
            except Exception as exc:
                result.put((None, exc))

        thread = threading.Thread(target=worker, name="research-http", daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise TimeoutError("research HTTP request timed out")
        data, error = result.get_nowait()
        if error is not None:
            if isinstance(error, TimeoutError):
                raise error
            if isinstance(error, ValueError):
                raise error
            raise RuntimeError("research HTTP request failed") from error
        return data or b""

    def _get_isolated(self, url: str, *, timeout: float, max_bytes: int) -> bytes:
        encoded_limit = max(1024, ((max_bytes + 2) // 3) * 4 + 16)
        result = run_fixed_process(
            [sys.executable, "-c", _HTTP_CHILD_SCRIPT, url, str(max_bytes)],
            timeout=timeout,
            max_output_bytes=encoded_limit,
        )
        if result.timed_out:
            raise TimeoutError("research HTTP request timed out")
        if result.output_limited:
            raise ValueError("response too large")
        if result.returncode == 20:
            raise ValueError("response too large")
        if result.returncode != 0:
            raise RuntimeError("research HTTP request failed")
        try:
            return base64.b64decode(result.stdout.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise RuntimeError("research HTTP response was invalid") from exc

    def _get(self, url: str, *, timeout: float, max_bytes: int) -> bytes:
        request = urllib.request.Request(
            url, headers={"User-Agent": "TrendRadar-Research/1.0", "Accept": "text/plain, application/json"}
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                chunks = []
                total = 0
                while total <= max_bytes:
                    chunk = response.read(min(8192, max_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("response too large")
                    chunks.append(chunk)
                return b"".join(chunks)
        except TimeoutError:
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            raise RuntimeError("research HTTP request failed") from exc


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect disabled", headers, None)


_HTTP_CHILD_SCRIPT = r'''
import base64
import sys
import urllib.error
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect disabled", headers, None)

url = sys.argv[1]
limit = int(sys.argv[2])
request = urllib.request.Request(
    url,
    headers={"User-Agent": "TrendRadar-Research/1.0", "Accept": "text/plain, application/json"},
)
try:
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        chunks = []
        total = 0
        while total <= limit:
            chunk = response.read(min(8192, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise SystemExit(20)
            chunks.append(chunk)
        sys.stdout.write(base64.b64encode(b"".join(chunks)).decode("ascii"))
except SystemExit:
    raise
except Exception:
    raise SystemExit(21)
'''


def json_object(value: str) -> object:
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid JSON response") from exc
