"""Provision the locked Python 3.12 engine without importing Qt or scientific code.

Venvs are created at their permanent unique path: Python documents that they
are not portable. Upgrades switch a small active pointer only after pip check,
all locked imports and exact distribution-version checks succeed.

Primary references:
https://docs.python.org/3.12/library/venv.html
https://pip.pypa.io/en/stable/cli/pip_install/
"""
from collections import deque
import codecs
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

from .owned_process import WindowsChildJob

if __package__ and __package__ != "services":
    from ..shared.atomic_files import atomic_replace
    from ..shared.runtime_environment import child_environment
else:
    from shared.atomic_files import atomic_replace
    from shared.runtime_environment import child_environment


class RuntimeSetupError(RuntimeError):
    """An isolated runtime could not be created or verified."""


class RuntimeNotReady(RuntimeSetupError):
    """No healthy runtime matches the packaged requirements."""


class RuntimeBusy(RuntimeSetupError):
    """Another process already owns runtime setup for this cache."""


_PROBE = """import json,struct,sys,venv,ensurepip,ssl,platform
print(json.dumps({'executable':sys.executable,'base_executable':getattr(sys,'_base_executable',sys.executable),
'version':list(sys.version_info[:3]),'bits':struct.calcsize('P')*8,
'implementation':platform.python_implementation(),'prefix':sys.prefix,'base_prefix':sys.base_prefix}))
"""

_HEALTH = """import importlib,importlib.metadata,json,pathlib,platform,re,site,struct,sys
expected=json.loads(sys.argv[1]); root=pathlib.Path(sys.argv[2]).resolve()
assert sys.version_info[:2]==(3,12), 'Python 3.12 required'
assert platform.python_implementation()=='CPython' and struct.calcsize('P')==8, '64-bit CPython required'
assert pathlib.Path(sys.prefix).resolve()==root, 'Runtime prefix mismatch'
assert sys.prefix!=sys.base_prefix and not site.ENABLE_USER_SITE, 'Runtime must be isolated'
aliases={'pyyaml':'yaml','scikit-learn':'sklearn','python-dateutil':'dateutil','click-plugins':'click_plugins'}
canonicalize=lambda name:re.sub(r'[-_.]+','-',name).lower()
installed={canonicalize(dist.metadata['Name']) for dist in importlib.metadata.distributions()}
unexpected=installed-{canonicalize(name) for name in expected}-{'pip','setuptools','wheel'}
assert not unexpected, f'Unlocked packages in engine: {sorted(unexpected)}'
versions={}
for name,version in expected.items():
    actual=importlib.metadata.version(name)
    assert actual==version, f'{name}: expected {version}, found {actual}'
    canonical=re.sub(r'[-_.]+','-',name).lower()
    importlib.import_module(aliases.get(canonical,canonical.replace('-','_')))
    versions[name]=actual
assert 'qgis' not in sys.modules, 'Engine must not import QGIS'
print(json.dumps({'version':list(sys.version_info[:3]),'prefix':sys.prefix,'versions':versions}))
"""


class _WindowsJob(WindowsChildJob):
    """Preserve the provisioning service's error type and private caller API."""
    def __init__(self):
        super().__init__(RuntimeSetupError)


class RuntimeManager:
    """Manage one per-user engine cache; no installation touches the host Python.

    ``progress`` receives ``(percent, message)`` on the setup caller's thread.
    Discovery, readiness and setup use subprocesses and belong in a GUI worker.
    Cancellation accepts the shared optional object exposing ``check()``.
    """
    PYTHON_VERSION = (3, 12)
    SCHEMA_VERSION = 2
    INSTALL_POLICY = "sha256_checked_binary_wheels"
    ENV_PATTERN = re.compile(r"engine-[0-9a-f]{12}-[0-9a-f]{32}$")
    PIN_PATTERN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)$")
    HASH_PATTERN = re.compile(r"--hash=sha256:([0-9a-fA-F]{64})$")
    MAX_CONTROL_BYTES = 512 * 1024

    def __init__(self, package_root, cache_root):
        self.package_root = Path(package_root).resolve()
        self.cache_root = Path(cache_root).resolve()
        if self.cache_root == self.package_root or self.cache_root.is_relative_to(self.package_root):
            raise ValueError("Engine cache must be outside the plugin source directory")
        self.env_root = self.cache_root / "environments"
        self.active_path = self.cache_root / "active.json"
        self.last_error = ""

    @staticmethod
    def _check_cancel(token):
        if token is not None:
            token.check()

    @staticmethod
    def _environment(python=None):
        return child_environment(python)

    @staticmethod
    def child_environment(python=None):
        """Return an independent sanitized environment for a QProcess adapter."""
        return RuntimeManager._environment(python)

    @staticmethod
    def _terminate(process, job=None):
        """Reap only our process group/tree, including venv's ensurepip child."""
        if os.name == "nt":
            if job is not None:
                job.terminate()
                process.wait(timeout=10)
                return
            if process.poll() is not None:
                return
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            try:
                subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=10)
        if os.name != "nt":
            # The leader can already be gone while descendants retain pipes.
            # Do not use only the leader's wait() as proof that the group ended.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _run(self, command, cancellation_token=None, progress=None, percent=0, timeout=300):
        """Bound diagnostic output; drain pipes and check cancellation regularly."""
        self._check_cancel(cancellation_token)
        working = Path(command[0]).resolve().parent
        if not working.is_dir() or working.is_relative_to(self.package_root):
            working = Path(tempfile.gettempdir()).resolve()
        if working.is_relative_to(self.package_root):
            raise RuntimeSetupError("Cannot choose an external runtime working directory")
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      env=self._environment(command[0]), cwd=working)
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        job = _WindowsJob() if os.name == "nt" else None
        try:
            process = subprocess.Popen([str(argument) for argument in command], **kwargs)
        except OSError as exc:
            if job is not None:
                job.close()
            raise RuntimeSetupError(f"Cannot start Python: {exc}") from exc
        try:
            if job is not None:
                job.assign(process)
        except Exception:
            self._terminate(process)
            if job is not None:
                job.close()
            process.stdout.close()
            raise
        chunks = queue.Queue(maxsize=64)
        stopped = threading.Event()
        reader_error = []
        def read_output():
            try:
                while not stopped.is_set():
                    data = process.stdout.read1(8192)
                    if not data:
                        break
                    while not stopped.is_set():
                        try:
                            chunks.put(data, timeout=0.1)
                            break
                        except queue.Full:
                            continue
            except (OSError, ValueError) as exc:
                reader_error.append(exc)
        reader = threading.Thread(target=read_output, name="pypoprf-runtime-output", daemon=True)
        reader.start()
        output = deque(maxlen=200)
        started = time.monotonic()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        def record(line):
            output.append(line[-2048:] + "\n")
            if progress is not None and line.strip():
                progress(percent, line.strip()[-1000:])
        def drain():
            nonlocal pending
            for _ in range(64):
                self._check_cancel(cancellation_token)
                try:
                    data = chunks.get_nowait()
                except queue.Empty:
                    break
                pending += decoder.decode(data)
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    record(line)
                # Untrusted diagnostics cannot grow a line without bound.
                if len(pending) > 8192:
                    record(pending[:-2048])
                    pending = pending[-2048:]
        try:
            while process.poll() is None:
                self._check_cancel(cancellation_token)
                drain()
                if time.monotonic() - started > timeout:
                    raise RuntimeSetupError(f"Python operation timed out after {timeout}s")
                time.sleep(0.05)
            while reader.is_alive():
                drain()
                self._check_cancel(cancellation_token)
                if time.monotonic() - started > timeout:
                    raise RuntimeSetupError(f"Python output pipe did not close after {timeout}s")
                reader.join(timeout=0.05)
            drain()
            pending += decoder.decode(b"", final=True)
            if pending:
                record(pending)
            self._check_cancel(cancellation_token)
            if process.returncode != 0:
                details = "".join(output)[-12000:].strip()
                raise RuntimeSetupError(f"Python operation failed ({process.returncode}): {details}")
            if reader_error:
                raise RuntimeSetupError(f"Cannot read Python output: {reader_error[0]}")
            return "".join(output)
        finally:
            stopped.set()
            try:
                self._terminate(process, job)
                reader.join(timeout=2)
                process.stdout.close()
            finally:
                if job is not None:
                    job.close()

    @staticmethod
    def _json_output(output):
        try:
            result = json.loads(output.strip().splitlines()[-1])
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON object")
            return result
        except (ValueError, IndexError) as exc:
            raise RuntimeSetupError("Python returned invalid runtime information") from exc

    def _probe(self, command, cancellation_token=None):
        info = self._json_output(self._run([*command, "-I", "-X", "utf8", "-c", _PROBE],
                                          cancellation_token=cancellation_token, timeout=15))
        if (tuple(info.get("version", [])[:2]) != self.PYTHON_VERSION
                or info.get("bits") != 64 or info.get("implementation") != "CPython"):
            raise RuntimeSetupError("The engine requires installed 64-bit CPython 3.12")
        executable = Path(info.get("executable", ""))
        if not executable.is_absolute() or not executable.is_file():
            raise RuntimeSetupError("Interpreter did not report an existing absolute executable path")
        return info

    @staticmethod
    def _interpreter_path(python_executable):
        executable = Path(python_executable).expanduser().resolve()
        if not executable.is_file():
            raise RuntimeSetupError(f"Python executable not found: {executable}")
        if executable.suffix.lower() in {".bat", ".cmd", ".ps1"}:
            raise RuntimeSetupError("Choose an installed Python executable, not a shell wrapper")
        if executable.parent.name.casefold() == "windowsapps":
            raise RuntimeSetupError("Choose an installed Python executable, not a Windows Store alias")
        return executable

    def check_interpreter(self, python_executable):
        executable = self._interpreter_path(python_executable)
        return self._probe([str(executable)])

    def detect_python_candidates(self, cancellation_token=None):
        self._check_cancel(cancellation_token)
        candidates = []
        base = getattr(sys, "_base_executable", None)
        if base and Path(base).name.lower() in {"python", "python.exe", "python3", "python3.12"}:
            candidates.append([str(base)])
        for path in (Path(sys.prefix) / "python.exe", Path(sys.prefix) / "bin" / "python3.12"):
            if path.is_file():
                candidates.append([str(path)])
        for name in ("python3.12", "python", "python3"):
            found = shutil.which(name)
            if found:
                candidates.append([found])
        if os.name == "nt":
            launcher = shutil.which("py")
            if launcher:
                candidates.append([launcher, "-3.12"])
        verified, seen = [], set()
        for command in candidates:
            self._check_cancel(cancellation_token)
            key = tuple(command)
            if key in seen:
                continue
            seen.add(key)
            if Path(command[0]).parent.name.casefold() == "windowsapps":
                continue
            try:
                path = Path(self._probe(command, cancellation_token)["executable"]).resolve()
                if path not in verified:
                    verified.append(path)
            except RuntimeSetupError:
                continue
        return verified

    @staticmethod
    def _requirement_lines(text):
        """Join pip-style continuations before stripping comments."""
        pending = ""
        for physical in text.splitlines():
            physical = physical.rstrip()
            continued = physical.endswith("\\")
            pending += (physical[:-1] if continued else physical) + (" " if continued else "")
            if continued:
                continue
            line = re.sub(r"(^|\s)#.*$", "", pending).strip()
            pending = ""
            if line:
                yield line
        if pending:
            raise RuntimeSetupError("Unterminated requirements line continuation")

    def _requirements(self):
        """Hash complete nested files and require exact SHA-256-verified pins."""
        files, pins, wheel_hashes, visiting = {}, {}, {}, set()
        def visit(relative):
            path = (self.package_root / relative).resolve()
            if not path.is_relative_to(self.package_root) or not path.is_file():
                raise RuntimeSetupError(f"Missing or unsafe requirements file: {relative}")
            name = path.relative_to(self.package_root).as_posix()
            if name in visiting:
                raise RuntimeSetupError("Cyclic nested requirements files")
            if name in files:
                return
            visiting.add(name)
            data = path.read_bytes()
            files[name] = data
            for line in self._requirement_lines(data.decode("utf-8-sig")):
                nested = re.fullmatch(r"(?:-r\s*|--requirement(?:\s+|=))(.+)", line)
                if nested:
                    child = (path.parent / nested.group(1).strip()).resolve()
                    if not child.is_relative_to(self.package_root):
                        raise RuntimeSetupError("Nested requirements escape the plugin package")
                    visit(child.relative_to(self.package_root))
                    continue
                fields = line.split()
                pin = self.PIN_PATTERN.fullmatch(fields[0])
                if pin is None:
                    raise RuntimeSetupError(f"Requirements must use exact package==version pins: {line}")
                package, version = pin.groups()
                digests = []
                for option in fields[1:]:
                    digest = self.HASH_PATTERN.fullmatch(option)
                    if digest is None:
                        raise RuntimeSetupError(f"Only --hash=sha256:<64 hex digits> is allowed for {package}")
                    digests.append(digest.group(1).lower())
                if not digests:
                    raise RuntimeSetupError(f"Every engine dependency must have a SHA-256 hash: {package}")
                canonical = re.sub(r"[-_.]+", "-", package).lower()
                existing = next((key for key in pins if re.sub(r"[-_.]+", "-", key).lower() == canonical), None)
                if existing is not None and pins[existing] != version:
                    raise RuntimeSetupError(f"Conflicting pins for {package}")
                if existing is None:
                    pins[package] = version
                    wheel_hashes[package] = sorted(set(digests))
                else:
                    wheel_hashes[existing] = sorted(set(wheel_hashes[existing] + digests))
            visiting.remove(name)
        visit(Path("requirements-engine.lock"))
        # requirements.txt documents direct dependencies; it is never an extra
        # pip input. Permit its unhashed exact pins, but reject documentation that
        # contradicts the verified engine lock and fingerprint its full bytes.
        summary = self.package_root / "requirements.txt"
        if summary.is_file() and "requirements.txt" not in files:
            if not summary.resolve().is_relative_to(self.package_root):
                raise RuntimeSetupError("Unsafe direct dependency summary")
            summary_bytes = summary.read_bytes()
            lookup = {re.sub(r"[-_.]+", "-", name).lower(): version for name, version in pins.items()}
            for line in self._requirement_lines(summary_bytes.decode("utf-8-sig")):
                fields = line.split()
                pin = self.PIN_PATTERN.fullmatch(fields[0])
                if pin is None or any(self.HASH_PATTERN.fullmatch(option) is None for option in fields[1:]):
                    raise RuntimeSetupError("Direct dependency summary must use exact pins")
                name, version = pin.groups()
                if lookup.get(re.sub(r"[-_.]+", "-", name).lower()) != version:
                    raise RuntimeSetupError(f"Direct dependency summary contradicts engine lock: {name}")
            files["requirements.txt"] = summary_bytes
        content = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
        payload = dict(files=content, python=list(self.PYTHON_VERSION), platform=sys.platform,
                       machine=platform.machine().lower(), schema=self.SCHEMA_VERSION,
                       install_policy=self.INSTALL_POLICY)
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return dict(fingerprint=fingerprint, files=files, hashes=content, pins=pins, wheel_hashes=wheel_hashes)

    @staticmethod
    def _python_in(environment):
        return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def _owned_environment(self, name):
        if not isinstance(name, str) or self.ENV_PATTERN.fullmatch(name) is None:
            raise RuntimeNotReady("Invalid engine environment name")
        environment = self.env_root / name
        if (environment.is_symlink() or self.env_root.is_symlink()
                or self.env_root.resolve() != self.env_root
                or environment.resolve().parent != self.env_root):
            raise RuntimeNotReady("Engine environment escaped its cache directory")
        return environment

    def _health(self, environment, requirements, cancellation_token=None):
        python = self._python_in(environment)
        if not python.is_file():
            raise RuntimeNotReady("Engine interpreter is missing")
        config = environment / "pyvenv.cfg"
        if (config.is_symlink() or config.resolve().parent != environment.resolve() or not config.is_file()
                or "include-system-site-packages = false" not in config.read_text(encoding="utf-8").lower()):
            raise RuntimeNotReady("Engine is not an isolated virtual environment")
        self._run([python, "-I", "-X", "utf8", "-m", "pip", "--isolated", "check"],
                  cancellation_token=cancellation_token, timeout=60)
        report = self._json_output(self._run([python, "-I", "-X", "utf8", "-c", _HEALTH,
                                             json.dumps(requirements["pins"], sort_keys=True), environment],
                                            cancellation_token=cancellation_token, timeout=60))
        if (report.get("versions") != requirements["pins"]
                or Path(report.get("prefix", "")).resolve() != environment.resolve()
                or tuple(report.get("version", [])[:2]) != self.PYTHON_VERSION):
            raise RuntimeNotReady("Engine health report does not match its requirements")
        return report

    def _control_json(self, path, parent):
        """Read bounded regular metadata without following unowned file links."""
        if path.is_symlink() or path.resolve().parent != parent.resolve() or not path.is_file():
            raise RuntimeNotReady(f"Missing or unsafe engine metadata: {path.name}")
        if path.stat().st_size > self.MAX_CONTROL_BYTES:
            raise RuntimeNotReady(f"Engine metadata is too large: {path.name}")
        try:
            with path.open("rb") as stream:
                data = stream.read(self.MAX_CONTROL_BYTES + 1)
            if len(data) > self.MAX_CONTROL_BYTES:
                raise RuntimeNotReady(f"Engine metadata is too large: {path.name}")
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError("Metadata must be an object")
            return result
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeNotReady(f"Invalid engine metadata: {path.name}") from exc

    def _completed_environment(self, name, requirements, cancellation_token=None):
        self._check_cancel(cancellation_token)
        environment = self._owned_environment(name)
        if not environment.is_dir():
            raise RuntimeNotReady("Engine environment is missing")
        owner = self._control_json(environment / "OWNER.json", environment)
        if not isinstance(owner.get("id"), str) or re.fullmatch(r"[0-9a-f]{32}", owner["id"]) is None:
            raise RuntimeNotReady("Engine environment has invalid ownership metadata")
        marker = self._control_json(environment / "READY.json", environment)
        if (marker.get("schema_version") != self.SCHEMA_VERSION
                or marker.get("fingerprint") != requirements["fingerprint"]
                or marker.get("requirements") != requirements["hashes"]
                or marker.get("pins") != requirements["pins"]
                or marker.get("wheel_hashes") != requirements["wheel_hashes"]
                or marker.get("install_policy") != self.INSTALL_POLICY):
            raise RuntimeNotReady("Engine completion marker is missing or stale")
        # lib64 -> lib is normal for Unix venvs; directory links out of the
        # environment are not. Do not import from a redirected package tree.
        for directory, children, _ in os.walk(environment, followlinks=False):
            self._check_cancel(cancellation_token)
            for child in children:
                candidate = Path(directory) / child
                if ((candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()))
                        and not candidate.resolve().is_relative_to(environment.resolve())):
                    raise RuntimeNotReady("Engine environment contains an unowned directory link")
        return environment

    def _ready_python(self, requirements, cancellation_token=None):
        if not self.active_path.is_file():
            raise RuntimeNotReady("Engine is not installed; set up Python 3.12 in plugin settings")
        active = self._control_json(self.active_path, self.cache_root)
        if active.get("schema_version") != self.SCHEMA_VERSION or active.get("fingerprint") != requirements["fingerprint"]:
            raise RuntimeNotReady("Engine needs an update for this plugin's requirements")
        environment = self._completed_environment(active.get("environment"), requirements, cancellation_token)
        self._health(environment, requirements, cancellation_token)
        return self._python_in(environment)

    def _reusable_environment(self, requirements, cancellation_token=None):
        """Find a previously completed matching engine; never change the pointer."""
        if not self.env_root.is_dir():
            return None
        if self.env_root.resolve() != self.env_root:
            raise RuntimeSetupError("Engine environment root cannot be a directory link")
        pattern = f"engine-{requirements['fingerprint'][:12]}-*"
        for candidate in sorted(self.env_root.glob(pattern), key=lambda path: path.name):
            self._check_cancel(cancellation_token)
            try:
                environment = self._completed_environment(candidate.name, requirements, cancellation_token)
                self._health(environment, requirements, cancellation_token)
                return environment
            except (RuntimeSetupError, OSError):
                # Preserve damaged environments for inspection; they are never
                # selected or deleted by a read/discovery operation.
                continue
        return None

    def runtime_ready(self, cancellation_token=None):
        try:
            self.get_python(cancellation_token)
            return True
        except (RuntimeSetupError, OSError, UnicodeError) as exc:
            self.last_error = str(exc)
            return False

    def get_python(self, cancellation_token=None):
        try:
            self._check_cancel(cancellation_token)
            python = self._ready_python(self._requirements(), cancellation_token)
            self.last_error = ""
            return python
        except (RuntimeSetupError, OSError, UnicodeError) as exc:
            self.last_error = str(exc)
            raise RuntimeNotReady(str(exc)) from exc

    @contextmanager
    def _setup_lock(self):
        self.cache_root.mkdir(parents=True, exist_ok=True)
        path = self.cache_root / "setup.lock"
        if path.is_symlink():
            raise RuntimeSetupError("Unsafe engine setup lock")
        handle = path.open("a+b")
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise RuntimeBusy("Another engine setup is already running") from exc
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise RuntimeBusy("Another engine setup is already running") from exc
            locked = True
            yield
        finally:
            if locked:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    @staticmethod
    def _write_json(path, value, cancellation_token=None):
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            atomic_replace(temporary, path, lambda: RuntimeManager._check_cancel(cancellation_token))
        finally:
            temporary.unlink(missing_ok=True)

    def _remove_owned_environment(self, environment, ownership_id):
        """Delete only the exact unique directory created by this setup attempt."""
        expected = self._owned_environment(environment.name)
        if expected.resolve() != environment.resolve() or not environment.is_dir():
            raise RuntimeSetupError("Unsafe engine cleanup target")
        owner = environment / "OWNER.json"
        if owner.is_symlink() or json.loads(owner.read_text(encoding="utf-8")).get("id") != ownership_id:
            raise RuntimeSetupError("Engine cleanup ownership verification failed")
        # No symlinks/junctions may redirect traversal outside our environment.
        # Unix venv Python executable symlinks are normal and are unlinked, not traversed.
        for directory, children, _ in os.walk(environment, followlinks=False):
            for child in children:
                candidate = Path(directory) / child
                if ((candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()))
                        and not candidate.resolve().is_relative_to(environment.resolve())):
                    raise RuntimeSetupError("Engine cleanup refuses directory links")
        shutil.rmtree(environment)

    def setup(self, python_executable, progress=None, cancellation_token=None):
        """Install locked wheels in a fresh venv, then atomically activate it."""
        def stage(percent, message):
            self._check_cancel(cancellation_token)
            if progress is not None:
                progress(percent, message)
        stage(0, "Checking isolated engine")
        with self._setup_lock():
            requirements = self._requirements()
            try:
                ready = self._ready_python(requirements, cancellation_token)
                stage(100, "Engine is ready")
                return ready
            except RuntimeSetupError:
                pass
            reusable = self._reusable_environment(requirements, cancellation_token)
            if reusable is not None:
                stage(95, "Reactivating the verified existing engine")
                if self._requirements()["fingerprint"] != requirements["fingerprint"]:
                    raise RuntimeSetupError("Plugin requirements changed during engine reactivation; retry the update")
                self._check_cancel(cancellation_token)
                self._write_json(self.active_path, {
                    "schema_version": self.SCHEMA_VERSION, "environment": reusable.name,
                    "fingerprint": requirements["fingerprint"],
                }, cancellation_token)
                self.last_error = ""
                if progress is not None:
                    progress(100, "Engine is ready")
                return self._python_in(reusable)
            stage(5, "Verifying Python 3.12")
            python = self._interpreter_path(python_executable)
            info = self._probe([str(python)], cancellation_token)
            python = Path(info["executable"])
            self.env_root.mkdir(parents=True, exist_ok=True)
            if self.env_root.is_symlink():
                raise RuntimeSetupError("Engine environment root cannot be a directory link")
            name = f"engine-{requirements['fingerprint'][:12]}-{uuid4().hex}"
            environment = self._owned_environment(name)
            environment.mkdir(exist_ok=False)
            ownership_id = uuid4().hex
            try:
                self._write_json(environment / "OWNER.json", {"id": ownership_id})
            except Exception:
                # No subprocess has used this just-created directory yet. An
                # atomic marker failure leaves it empty, so rmdir is sufficient.
                environment.rmdir()
                raise
            published = False
            try:
                stage(10, "Creating a dedicated virtual environment")
                self._run([python, "-I", "-X", "utf8", "-m", "venv", environment], cancellation_token, progress, 10, 180)
                runtime_python = self._python_in(environment)
                if not runtime_python.is_file():
                    raise RuntimeSetupError("Virtual environment creation did not produce Python")
                snapshot = environment / "requirements"
                for relative, data in requirements["files"].items():
                    destination = snapshot / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                stage(25, "Installing locked binary packages in the engine")
                self._run([runtime_python, "-I", "-X", "utf8", "-m", "pip", "--isolated", "--disable-pip-version-check",
                           "install", "--require-hashes", "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
                           "--no-warn-script-location", "-r", snapshot / "requirements-engine.lock"],
                          cancellation_token, progress, 25, 1800)
                stage(85, "Checking exact package versions and native imports")
                report = self._health(environment, requirements, cancellation_token)
                stage(95, "Activating the verified engine")
                if self._requirements()["fingerprint"] != requirements["fingerprint"]:
                    raise RuntimeSetupError("Plugin requirements changed during setup; retry the update")
                self._check_cancel(cancellation_token)
                self._write_json(environment / "READY.json", {
                    "schema_version": self.SCHEMA_VERSION, "fingerprint": requirements["fingerprint"],
                    "requirements": requirements["hashes"], "pins": requirements["pins"],
                    "wheel_hashes": requirements["wheel_hashes"], "install_policy": self.INSTALL_POLICY,
                    "health": report, "created_utc": datetime.now(timezone.utc).isoformat(),
                })
                self._check_cancel(cancellation_token)
                self._write_json(self.active_path, {
                    "schema_version": self.SCHEMA_VERSION, "environment": name,
                    "fingerprint": requirements["fingerprint"],
                }, cancellation_token)
                published = True
                self.last_error = ""
                if progress is not None:
                    progress(100, "Engine is ready")
                return runtime_python
            finally:
                if not published:
                    self._remove_owned_environment(environment, ownership_id)
