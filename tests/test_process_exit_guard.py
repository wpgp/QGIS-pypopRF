"""Process ancestry and asynchronous reaping are independent of native Qt."""
import os
import subprocess
import sys
import time

import pytest

from q_models.process_exit_guard import ProcessExitGuard


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
