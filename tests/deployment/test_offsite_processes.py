"""RG-05: exercise actual subprocess trees without a restic repository."""

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from scripts.deploy.offsite_backup import upload_snapshot
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.backup import create_snapshot

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "SYNTHETIC-RESTIC-SECRET-79426"


def _snapshot(tmp_path):
    database = tmp_path / "intelligence.db"
    with IntelligenceStorage(database):
        pass
    return Path(create_snapshot([database], tmp_path / "backups", release_id="tree-test")["path"])


def _alive(pid):
    if os.name != "nt":
        stat = Path(f"/proc/{pid}/stat")
        try:
            status = stat.read_text()
        except (FileNotFoundError, ProcessLookupError):
            return False
        return status.rsplit(")", 1)[1].split()[0] != "Z"
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def _wait_dead(pid):
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _alive(pid), f"test child {pid} survived backup completion"


def _cleanup_owned(pid):
    if not _alive(pid):
        return
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(1, False, pid)
        if handle:
            kernel.TerminateProcess(handle, 92)
            kernel.CloseHandle(handle)
    else:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


@pytest.mark.skipif(os.name == "nt", reason="Linux procfs lifecycle")
@pytest.mark.parametrize("error", [FileNotFoundError, ProcessLookupError])
def test_alive_handles_exit_before_stat_read(monkeypatch, error):
    monkeypatch.setattr(Path, "exists", lambda self: True)

    def disappeared(self):
        raise error(self)

    monkeypatch.setattr(Path, "read_text", disappeared)
    assert not _alive(12345)


@pytest.mark.skipif(os.name == "nt", reason="Linux procfs lifecycle")
@pytest.mark.parametrize(("state", "alive"), [("S", True), ("R", True), ("Z", False)])
def test_alive_distinguishes_running_and_zombie_processes(monkeypatch, state, alive):
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "read_text", lambda self: f"12345 (test (child)) {state} 1 0")
    assert _alive(12345) is alive


@pytest.mark.skipif(os.name == "nt", reason="Linux procfs lifecycle")
def test_alive_does_not_hide_unreadable_stat(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda self: True)

    def unreadable(self):
        raise PermissionError(self)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(PermissionError):
        _alive(12345)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal lifecycle")
@pytest.mark.parametrize("error", [ProcessLookupError, PermissionError])
def test_cleanup_handles_only_exit_before_signal(monkeypatch, error):
    monkeypatch.setitem(globals(), "_alive", lambda pid: True)

    def failed_signal(pid, sig):
        raise error(pid)

    monkeypatch.setattr(os, "kill", failed_signal)
    if error is ProcessLookupError:
        _cleanup_owned(12345)
    else:
        with pytest.raises(PermissionError):
            _cleanup_owned(12345)


def _fake_tree(tmp_path, mode):
    child = tmp_path / "child.py"
    child.write_text(
        "import os,signal,time\nfrom pathlib import Path\n"
        "if os.name != 'nt': signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(tmp_path / 'child.pid')!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n", encoding="utf-8",
    )
    parent = tmp_path / "fake_restic.py"
    parent.write_text(
        "import json,os,subprocess,sys,time\nfrom pathlib import Path\n"
        f"Path({str(tmp_path / 'parent.pid')!r}).write_text(str(os.getpid()))\n"
        f"mode={mode!r}\n"
        f"child=subprocess.Popen([sys.executable,'-B',{str(child)!r}], "
        "stdout=subprocess.DEVNULL if mode=='detached' else None, "
        "stderr=subprocess.DEVNULL if mode=='detached' else None)\n"
        "deadline=time.monotonic()+5\n"
        f"while not Path({str(tmp_path / 'child.pid')!r}).exists():\n"
        "    if time.monotonic()>deadline: raise RuntimeError('test child handshake failed')\n"
        "    time.sleep(0.01)\n"
        f"print({SENTINEL!r},file=sys.stderr,flush=True)\n"
        "print(json.dumps({'snapshot_id':'fake-tree-snapshot'}),flush=True)\n"
        "if mode=='hanging': time.sleep(60)\n", encoding="utf-8",
    )
    return parent


@pytest.mark.parametrize("mode", ["hanging", "inherited", "detached"])
def test_backup_completion_reaps_child_even_after_leader_exit(tmp_path, mode):
    snapshot = _snapshot(tmp_path)
    fake = _fake_tree(tmp_path, mode)
    started = time.monotonic()
    try:
        if mode == "detached":
            assert upload_snapshot(
                snapshot, restic_bin=[sys.executable, "-B", str(fake)],
                repository=SENTINEL, password_file="fake-password", timeout_seconds=2,
                kill_grace_seconds=1,
            )["success"]
        else:
            with pytest.raises(TimeoutError, match="exceeded its time budget"):
                upload_snapshot(
                    snapshot, restic_bin=[sys.executable, "-B", str(fake)],
                    repository=SENTINEL, password_file="fake-password", timeout_seconds=2,
                    kill_grace_seconds=1,
                )
            assert not (snapshot / "offsite-manifest.json").exists()
        assert time.monotonic() - started < 10
        assert (tmp_path / "child.pid").is_file(), "child handshake never completed"
        for name in ("child.pid", "parent.pid"):
            _wait_dead(int((tmp_path / name).read_text()))
    finally:
        for name in ("child.pid", "parent.pid"):
            if (tmp_path / name).is_file():
                _cleanup_owned(int((tmp_path / name).read_text()))


@pytest.mark.parametrize("mode", ["success", "failure", "timeout"])
def test_direct_cli_outside_checkout_redacts_provider_failures(tmp_path, mode):
    snapshot = _snapshot(tmp_path)
    # Python serves as the fake restic executable and runs this local 'backup' file.
    (tmp_path / "backup").write_text(
        "import json,sys,time\n"
        f"print({SENTINEL!r},flush=True)\nprint({SENTINEL!r},file=sys.stderr,flush=True)\n"
        + ("time.sleep(60)\n" if mode == "timeout" else "")
        + ("raise SystemExit(7)\n" if mode == "failure" else
           "print(json.dumps({'snapshot_id':'direct-cli-snapshot'}))\n"), encoding="utf-8",
    )
    environment = {key: os.environ[key] for key in ("PATH", "SystemRoot", "TEMP", "TMP")
                   if key in os.environ}
    environment["TRENDRADAR_OFFSITE_ENABLED"] = "true"
    result = subprocess.run([
        sys.executable, "-B", str(ROOT / "scripts/deploy/offsite_backup.py"),
        "--snapshot", str(snapshot), "--restic-bin", sys.executable,
        "--repository", SENTINEL, "--password-file", SENTINEL,
        "--timeout-seconds", "2", "--kill-grace-seconds", "1",
    ], cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=15)
    assert SENTINEL not in result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is (mode == "success")
    assert result.returncode == (0 if mode == "success" else 1)
    assert (snapshot / "offsite-manifest.json").exists() is (mode == "success")


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object lifecycle")
def test_popen_failure_closes_windows_job(tmp_path, monkeypatch):
    import scripts.deploy.process_tree as process_tree

    closed = []

    class TrackedJob(process_tree.WindowsJob):
        def close(self):
            super().close()
            closed.append(True)

    monkeypatch.setattr(process_tree, "WindowsJob", TrackedJob)
    with pytest.raises(OSError):
        upload_snapshot(_snapshot(tmp_path), restic_bin=str(tmp_path / "missing-restic.exe"),
                        repository="fake", password_file="fake-password")
    assert closed == [True]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object attachment")
@pytest.mark.parametrize("assigned", [False, True])
def test_job_attachment_failure_reaps_the_actual_suspended_process(tmp_path, monkeypatch, assigned):
    from scripts.deploy import offsite_backup, process_tree

    processes = []
    closed = []
    original_popen = offsite_backup.subprocess.Popen

    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    class FailingJob(process_tree.WindowsJob):
        def attach_and_resume(self, process):
            if assigned:
                assert self.kernel.AssignProcessToJobObject(self.handle, int(process._handle))
            raise OSError("synthetic assignment/resume failure")

        def close(self):
            super().close()
            closed.append(True)

    monkeypatch.setattr(process_tree, "WindowsJob", FailingJob)
    monkeypatch.setattr(offsite_backup.subprocess, "Popen", popen)
    with pytest.raises(OSError, match="assignment/resume"):
        upload_snapshot(_snapshot(tmp_path), restic_bin=[sys.executable, "-B", "-c", "pass"],
                        repository="fake", password_file="fake-password", kill_grace_seconds=1)
    assert closed == [True]
    assert len(processes) == 1
    assert processes[0].poll() is not None
    _wait_dead(processes[0].pid)
