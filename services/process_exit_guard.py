"""Read-only Windows descendant reaping before an owned QProcess is released.

Windows CPython venv launchers can finish just before their interpreter child.
No process is killed here: held handles and creation/exit-time ancestry identify
only this launch, and the Qt adapter polls without blocking its event loop.
POSIX numerical tools use the QProcess PID itself and private threads.
"""
import os


class ProcessExitGuard:
    def __init__(self, api=None):
        self._api = api
        self._members = {}
        self._begun = False
        self._indeterminate = False

    def begin(self, pid):
        if type(pid) is not int or pid <= 0:
            raise ValueError("An owned positive process ID is required")
        if self._begun:
            raise RuntimeError("An exit guard belongs to one process launch")
        self._begun = True
        if self._api is None and os.name != "nt":
            return
        self._indeterminate = True
        if self._api is None:
            self._api = _WindowsProcesses()
        handle = self._api.open(pid)
        if handle is None:
            self._indeterminate = True
            raise RuntimeError("The owned process disappeared before its exit could be tracked")
        try:
            created, _ = self._api.times(handle)
        except Exception:
            self._api.close(handle)
            self._indeterminate = True
            raise
        self._members[(pid, created)] = handle
        self._indeterminate = False
        self._capture()

    def _capture(self):
        if not self._members:
            return
        entries = self._api.snapshot()
        # A PID can be reused: every parent proof is an actual creation/exit
        # interval from a held process handle, never a bare PPID/name match.
        while True:
            parents = {}
            for (pid, created), handle in self._members.items():
                # GetProcessTimes exit output is undefined while a process is
                # running. The held handle's creation key is already known.
                exited = self._api.times(handle)[1] if self._api.signaled(handle) else 0
                parents.setdefault(pid, []).append((created, exited))
            added = False
            for pid, parent_pid in entries:
                if pid == parent_pid or parent_pid not in parents:
                    continue
                try:
                    handle = self._api.open(pid)
                except OSError as exc:
                    if getattr(exc, "winerror", None) == 5 and hasattr(self._api, "creation_time"):
                        # A stale PPID may point to an unrelated protected
                        # process. Limited query rights can prove its birth is
                        # outside every held parent's lifetime, but cannot
                        # prove an owned process exited without SYNCHRONIZE.
                        candidate_created = self._api.creation_time(pid)
                        if candidate_created is None or not any(
                                candidate_created >= start and (not end or candidate_created <= end)
                                for start, end in parents[parent_pid]):
                            continue
                    raise
                if handle is None:  # Already exited and disappeared.
                    continue
                retained = False
                try:
                    created, _ = self._api.times(handle)
                    key = pid, created
                    if key in self._members:
                        continue
                    if any(created >= start and (not end or created <= end)
                           for start, end in parents[parent_pid]):
                        self._members[key] = handle
                        retained, added = True, True
                finally:
                    if not retained:
                        self._api.close(handle)
            if not added:
                break

    def exited(self):
        if self._indeterminate:
            raise RuntimeError("The owned process exit could not be verified")
        if self._api is None or not self._members:
            return True
        self._capture()
        return all(self._api.signaled(handle) for handle in self._members.values())

    def close(self):
        if self._api is not None:
            for handle in self._members.values():
                self._api.close(handle)
        self._members.clear()


class _WindowsProcesses:
    """Minimal kernel adapter; failures are not treated as successful reaping."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes
        self.wt = wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)

        class FileTime(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

        class ProcessEntry(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                       ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                       ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                       ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                       ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260)]

        self.FileTime, self.ProcessEntry = FileTime, ProcessEntry
        declarations = {
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "GetProcessTimes": ([wintypes.HANDLE, *[ctypes.POINTER(FileTime)] * 4], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Process32FirstW": ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
            "Process32NextW": ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
        }
        for name, (arguments, result) in declarations.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = arguments, result

    def open(self, pid):
        handle = self.kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not handle:
            error = self.ct.get_last_error()
            if error == 87:  # PID disappeared between snapshot and open.
                return None
            raise self.ct.WinError(error)
        return handle

    def times(self, handle):
        created, exited, kernel, user = (self.FileTime() for _ in range(4))
        if not self.kernel.GetProcessTimes(handle, self.ct.byref(created), self.ct.byref(exited),
                                           self.ct.byref(kernel), self.ct.byref(user)):
            raise self.ct.WinError(self.ct.get_last_error())
        return ((created.high << 32) | created.low, (exited.high << 32) | exited.low)

    def creation_time(self, pid):
        """Query birth only; this handle is never retained or used to prove exit."""
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            error = self.ct.get_last_error()
            if error == 87:
                return None
            raise self.ct.WinError(error)
        try:
            return self.times(handle)[0]
        finally:
            self.close(handle)

    def signaled(self, handle):
        status = self.kernel.WaitForSingleObject(handle, 0)
        if status == 0:
            return True
        if status == 258:
            return False
        raise self.ct.WinError(self.ct.get_last_error())

    def snapshot(self):
        invalid = self.ct.c_void_p(-1).value
        for _ in range(3):
            handle = self.kernel.CreateToolhelp32Snapshot(2, 0)
            if handle != invalid:
                break
            error = self.ct.get_last_error()
            if error != 24:  # ERROR_BAD_LENGTH: process list changed.
                raise self.ct.WinError(error)
        else:
            raise self.ct.WinError(24)
        if not handle:
            raise self.ct.WinError(self.ct.get_last_error())
        try:
            entry = self.ProcessEntry()
            entry.size = self.ct.sizeof(entry)
            entries = []
            present = self.kernel.Process32FirstW(handle, self.ct.byref(entry))
            while present:
                entries.append((int(entry.pid), int(entry.parent)))
                present = self.kernel.Process32NextW(handle, self.ct.byref(entry))
            error = self.ct.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES
                raise self.ct.WinError(error)
            return entries
        finally:
            self.close(handle)

    def close(self, handle):
        self.kernel.CloseHandle(handle)
