"""Process ancestry and asynchronous reaping are independent of native Qt."""
import os
import subprocess
import sys
import time

import pytest

from services.process_exit_guard import ProcessExitGuard


class Kernel:
    def __init__(self):
        self.processes = {10: (100, 0, False)}
        self.entries = []
        self.closed = []

    def open(self, pid):
        if pid not in self.processes:
            return None
        created, exited, signaled = self.processes[pid]
        return pid, created, exited, signaled

    def times(self, handle):
        current = self.processes.get(handle[0])
        if current and current[0] == handle[1]:
            return current[:2]
        return handle[1:3]

    def signaled(self, handle):
        current = self.processes.get(handle[0])
        return current[2] if current and current[0] == handle[1] else handle[3]

    def snapshot(self):
        return list(self.entries)

    def close(self, handle):
        self.closed.append(handle)


def test_no_started_process_and_posix_guard_are_nonblocking():
    guard = ProcessExitGuard()
    assert guard.exited()
    guard.close()
    if os.name != "nt":
        guard.begin(10)
        assert guard.exited()


def test_parent_exit_does_not_release_live_child_or_grandchild():
    kernel, guard = Kernel(), None
    kernel.processes.update({11: (110, 0, False), 12: (120, 0, False), 99: (1, 0, False)})
    kernel.entries = [(11, 10), (12, 11), (99, 10)]
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    kernel.processes[10] = (100, 200, True)
    assert not guard.exited()
    assert (99, 1) not in guard._members  # Unrelated older process / reused PPID.
    kernel.processes[11] = (110, 210, True)
    assert not guard.exited()
    kernel.processes[12] = (120, 220, True)
    assert guard.exited()
    retained = list(guard._members.values())
    guard.close()
    assert all(handle in kernel.closed for handle in retained)


def test_child_discovered_after_started_and_parent_pid_reuse_is_not_owned():
    kernel = Kernel()
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    kernel.processes[10] = (100, 200, True)
    kernel.processes[11] = (150, 0, False)
    kernel.processes[12] = (250, 0, False)
    kernel.entries = [(11, 10), (12, 10)]
    assert not guard.exited()
    assert (11, 150) in guard._members and (12, 250) not in guard._members


def test_query_failure_does_not_claim_successful_reaping():
    kernel = Kernel()
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    kernel.snapshot = lambda: (_ for _ in ()).throw(OSError("snapshot failed"))
    with pytest.raises(OSError, match="snapshot failed"):
        guard.exited()
    guard.close()


def test_missing_started_process_is_indeterminate_not_success():
    guard = ProcessExitGuard(Kernel())
    with pytest.raises(RuntimeError, match="disappeared"):
        guard.begin(123)
    with pytest.raises(RuntimeError, match="could not be verified"):
        guard.exited()
    guard.close()


def test_initial_open_failure_is_indeterminate_not_success():
    kernel = Kernel()
    kernel.open = lambda pid: (_ for _ in ()).throw(OSError("access denied"))
    guard = ProcessExitGuard(kernel)
    with pytest.raises(OSError, match="access denied"):
        guard.begin(10)
    with pytest.raises(RuntimeError, match="could not be verified"):
        guard.exited()
    guard.close()


def access_denied():
    error = PermissionError("SYNCHRONIZE access denied")
    error.winerror = 5
    return error


@pytest.mark.parametrize("created", [1, 250])
def test_inaccessible_foreign_candidate_requires_proven_birth_outside_parent_lifetime(created):
    kernel = Kernel()
    kernel.processes[10] = (100, 200, True)
    open_process = kernel.open
    queried = []
    def open_candidate(pid):
        if pid == 99:
            raise access_denied()
        return open_process(pid)
    kernel.open = open_candidate
    kernel.creation_time = lambda pid: queried.append(pid) or created
    kernel.entries = [(99, 10)]
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    assert guard.exited() and queried
    assert list(guard._members) == [(10, 100)]
    guard.close()


def test_inaccessible_possibly_owned_candidate_is_not_ignored():
    kernel = Kernel()
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    kernel.processes[10] = (100, 200, True)
    kernel.entries = [(11, 10)]
    kernel.open = lambda pid: (_ for _ in ()).throw(access_denied())
    kernel.creation_time = lambda pid: 120
    with pytest.raises(PermissionError, match="SYNCHRONIZE"):
        guard.exited()
    assert list(guard._members) == [(10, 100)]
    guard.close()


def test_candidate_with_inaccessible_creation_time_keeps_fail_closed_state():
    kernel = Kernel()
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    kernel.processes[10] = (100, 200, True)
    kernel.entries = [(99, 10)]
    kernel.open = lambda pid: (_ for _ in ()).throw(access_denied())
    kernel.creation_time = lambda pid: (_ for _ in ()).throw(access_denied())
    with pytest.raises(PermissionError):
        guard.exited()
    guard.close()


def test_non_access_denied_candidate_failure_does_not_query_or_ignore():
    kernel = Kernel()
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    kernel.entries = [(99, 10)]
    kernel.open = lambda pid: (_ for _ in ()).throw(OSError("unrelated failure"))
    kernel.creation_time = lambda pid: pytest.fail("Only access-denied candidates may be queried")
    with pytest.raises(OSError, match="unrelated failure"):
        guard.exited()
    guard.close()


def test_running_parent_undefined_exit_timestamp_cannot_exclude_owned_child():
    kernel = Kernel()
    kernel.processes.update({10: (100, 150, False), 11: (200, 0, False)})
    kernel.entries = [(11, 10)]
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    assert (11, 200) in guard._members
    kernel.processes[10] = (100, 300, True)
    assert not guard.exited()
    kernel.processes[11] = (200, 400, True)
    assert guard.exited()
    guard.close()


@pytest.mark.skipif(os.name != "nt", reason="Real Windows limited-query process handle")
def test_actual_creation_only_query_never_waits_and_closes_handle(monkeypatch):
    from services.process_exit_guard import _WindowsProcesses
    api = _WindowsProcesses()
    closed = []
    close = api.close
    monkeypatch.setattr(api, "close", lambda handle: closed.append(handle) or close(handle))
    monkeypatch.setattr(api, "signaled", lambda handle: pytest.fail("Query-only rights cannot prove reaping"))
    created = api.creation_time(os.getpid())
    assert isinstance(created, int) and created > 0 and len(closed) == 1


def test_pid_reuse_tracks_each_generation_and_never_waits_on_foreign_children():
    kernel = Kernel()
    root = {"created": 100, "exited": 0, "signaled": False}
    first = {"created": 110, "exited": 0, "signaled": False}
    current = {10: root, 11: first}
    kernel.open = lambda pid: current.get(pid)
    kernel.times = lambda handle: (handle["created"], handle["exited"])
    kernel.signaled = lambda handle: handle["signaled"]
    kernel.entries = [(11, 10)]
    guard = ProcessExitGuard(kernel)
    guard.begin(10)
    first.update(exited=140, signaled=True)
    second = {"created": 160, "exited": 0, "signaled": False}
    current[11] = second  # A new owned child reuses an earlier child's PID.
    assert not guard.exited()
    assert (11, 110) in guard._members and (11, 160) in guard._members
    root.update(exited=200, signaled=True)
    current[10] = {"created": 300, "exited": 0, "signaled": False}
    current[12] = {"created": 310, "exited": 0, "signaled": False}
    kernel.entries = [(12, 10)]  # A foreign process now owns the reused root PID.
    assert not guard.exited()
    assert (12, 310) not in guard._members
    second.update(exited=220, signaled=True)
    assert guard.exited()  # The unrelated new root/child are deliberately ignored.
    guard.close()


@pytest.mark.parametrize("pid", [0, -1, True, "10"])
def test_invalid_pid_rejected(pid):
    with pytest.raises(ValueError):
        ProcessExitGuard(Kernel()).begin(pid)


@pytest.mark.skipif(os.name != "nt", reason="Real Windows process handles")
def test_real_managed_venv_launcher_and_interpreter_are_reaped_before_release():
    process = subprocess.Popen([sys.executable, "-c", "import os,time; print(os.getpid(),flush=True); time.sleep(30)"],
                               stdout=subprocess.PIPE, text=True)
    guard = ProcessExitGuard()
    try:
        guard.begin(process.pid)
        actual = int(process.stdout.readline())
        assert not guard.exited()
        assert any(pid == actual for pid, created in guard._members)
        process.kill()
        process.wait(timeout=10)
        deadline = time.monotonic() + 10
        while not guard.exited() and time.monotonic() < deadline:
            time.sleep(.01)
        assert guard.exited()
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        process.stdout.close()
        guard.close()
