"""Own one isolated engine process; only verified terminal runs become results."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

import yaml
from qgis.PyQt.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal
from ..services.result_manifest import read_manifest, population_paths
from ..shared.atomic_files import atomic_replace
from ..services.process_exit_guard import ProcessExitGuard
from ..services.engine_snapshot import create_engine_snapshot, engine_arguments
from ..services.project_location import ensure_project_paths


class ProcessExecutor(QObject):
    completed = pyqtSignal()
    MAX_EVENT = 256 * 1024

    def __init__(self, dialog, logger, iface=None):
        super().__init__(dialog)
        self.dialog, self.logger, self.iface = dialog, logger, iface
        self.process = None
        self.output_layers = []
        self.last_run_dir = None
        self.last_result_paths = []
        self._job = None
        self._stdout = b""
        self._stderr = ""
        self._result = None
        self._cancelled = False
        self._expected_run = None
        self._config_file = None
        self._canonical_run = None
        self._exit_guard = None
        self._guard_warning = False
        self._waiting_exit = False

    @property
    def is_running(self):
        return self.process is not None

    def start_analysis(self):
        if self.is_running:
            return
        if self.dialog.is_busy:
            return
        if not self._validate_all():
            return
        python = self.dialog.runtime_controller.python
        if not python:
            self.logger.error("Set up the analysis engine before starting")
            self.dialog.set_task_status("Set up the analysis engine before starting")
            return
        try:
            snapshot = self.dialog.config_manager.get_config()
            snapshot.update(self.dialog.settings_handler.collect_settings(self.dialog))
            snapshot["work_dir"] = str(self.dialog.config_manager.working_dir)
            root = ensure_project_paths(snapshot["work_dir"], snapshot,
                plugin_root=self.dialog.plugin_root, job_cache=self.dialog.job_cache,
                runtime_cache=getattr(self.dialog.runtime_controller.manager, "cache_root", None))
            output = (root / snapshot.get("output_dir", "output")).resolve()
            identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
            self._expected_run = output / "runs" / identifier
            self._canonical_run = self._expected_run.resolve()
            jobs = Path(self.dialog.job_cache)
            jobs.mkdir(parents=True, exist_ok=True)
            self._job = tempfile.TemporaryDirectory(prefix="analysis-", dir=jobs)
            self._cancel_file = Path(self._job.name) / "cancel"
            config = Path(self._job.name) / "config.yaml"
            self._config_file = config.resolve()
            config.write_text(yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8")
            engine_source = create_engine_snapshot(self.dialog.plugin_root, Path(self._job.name))
            self._stdout, self._stderr, self._result = b"", "", None
            self._cancelled = False
            self.last_result_paths = []
            self.logger.info("— New analysis —")
            if hasattr(self.dialog, "begin_task"):
                self.dialog.begin_task("Starting population analysis")
            self.dialog.mainProgressBar.setValue(0)
            process = QProcess(self)
            self.process = process
            self._exit_guard = ProcessExitGuard()
            self._guard_warning = False
            self._waiting_exit = False
            process.started.connect(lambda owned=process, guard=self._exit_guard: self._started(owned, guard))
            process.setWorkingDirectory(self._job.name)
            environment = QProcessEnvironment()
            for key, value in self.dialog.runtime_controller.manager.child_environment(python).items():
                environment.insert(str(key), str(value))
            process.setProcessEnvironment(environment)
            process.setProgram(str(python))
            process.setArguments(engine_arguments(engine_source, "core.pypoprf", [
                "--config", str(config), "--output-dir", str(self._expected_run),
                "--cancel-file", str(self._cancel_file)]))
            process.readyReadStandardOutput.connect(lambda owned=process: self._read_stdout(owned))
            process.readyReadStandardError.connect(lambda owned=process: self._read_stderr(owned))
            process.finished.connect(lambda code, status, owned=process: self._finished(code, status, owned))
            process.errorOccurred.connect(lambda error, owned=process: self._process_error(error, owned))
            self._set_ui_enabled(False)
            self.update_progress(0, "Checking input data…")
            process.start()
        except Exception as exc:
            self.logger.error(f"Could not start analysis: {exc}")
            self.dialog.set_task_status(f"Could not start analysis: {exc}")
            self._release()
            self._set_ui_enabled(True)

    def stop_analysis(self):
        if self.process is None or self._cancelled:
            return
        self._cancelled = True
        try:
            self._cancel_file.touch()
        except OSError as exc:
            self.logger.warning(f"Could not request a graceful stop: {exc}")
            self.process.kill()
        self.dialog.mainStartButton.setEnabled(False)
        self.dialog.mainStartButton.setText("Stopping…")
        self.dialog.set_task_status("Stopping after the current operation…")
        owned = self.process
        QTimer.singleShot(30000, lambda: self._force_stop(owned))

    def _force_stop(self, owned):
        if self.process is owned and self._cancelled:
            self.logger.warning("The calculation did not respond to cancellation; stopping its engine process")
            owned.kill()

    def _read_stdout(self, owned=None):
        if self.process is None or (owned is not None and self.process is not owned):
            return
        data = bytes(self.process.readAllStandardOutput())
        self._consume_stdout(data)

    def _consume_stdout(self, data):
        self._stdout += data
        while b"\n" in self._stdout:
            line, self._stdout = self._stdout.split(b"\n", 1)
            if len(line) > self.MAX_EVENT:
                self.logger.warning("An oversized engine message was ignored")
                continue
            self._event_line(line)
        if len(self._stdout) > self.MAX_EVENT:
            self._stdout = b""
            self.logger.warning("An oversized engine message was ignored")

    def _event_line(self, line):
        try:
            event = json.loads(line.decode("utf-8"))
            if not isinstance(event, dict):
                return
            if event.get("event") == "progress":
                percent, message = event.get("percent"), event.get("message")
                if type(percent) is int and 0 <= percent <= 100 and isinstance(message, str):
                    self.update_progress(percent, message[:2000])
            elif event.get("event") == "result":
                self._result = event
        except (ValueError, UnicodeError):
            if line.strip():
                self.logger.debug(line.decode("utf-8", errors="replace")[:2000])

    def _read_stderr(self, owned=None):
        if self.process and (owned is None or self.process is owned):
            self._stderr = (self._stderr + bytes(self.process.readAllStandardError()).decode(
                "utf-8", errors="replace"))[-65536:]

    def _process_error(self, error, owned=None):
        if owned is not None and self.process is not owned:
            return
        if error == QProcess.ProcessError.FailedToStart and self.process is not None:
            self._stderr = self.process.errorString()
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _started(self, owned, guard):
        if self.process is not owned or self._exit_guard is not guard:
            return
        try:
            guard.begin(int(owned.processId()))
        except Exception as exc:
            self._guard_warning = True
            self.logger.error(f"Could not track engine process exit; temporary files will be retained until exit is verified: {exc}")

    def _verified_outputs(self, manifest):
        event = self._result or {}
        if not self._run_root_safe():
            raise ValueError("The run directory was redirected after analysis started")
        root = self._canonical_run
        if manifest.get("status") != "complete" or event.get("status") != "complete":
            raise ValueError("The engine did not publish a completed run")
        if not event.get("run_dir") or Path(event["run_dir"]).resolve() != root:
            raise ValueError("The engine returned a different run directory")
        names = manifest.get("outputs")
        if not isinstance(names, list) or names != event.get("outputs") or not names:
            raise ValueError("Engine output metadata is incomplete or inconsistent")
        paths = population_paths(root, manifest)
        if not paths:
            raise ValueError("No population maps were published")
        return paths

    def _finished(self, code, exit_status, owned=None):
        if self.process is None or (owned is not None and self.process is not owned):
            return
        owned = self.process
        try:
            reaped = self._exit_guard is None or self._exit_guard.exited()
        except Exception as exc:
            reaped = False
            if not self._guard_warning:
                self._guard_warning = True
                self.logger.error(f"Could not verify engine exit; tasks and temporary files are retained: {exc}")
        if not reaped:
            if not self._waiting_exit:
                self._waiting_exit = True
                self.dialog.set_task_status("Waiting for the engine to exit before cleaning up…")
            QTimer.singleShot(20, lambda: self._finished(code, exit_status, owned))
            return
        self._read_stdout()
        self._read_stderr()
        if self._stdout.strip():
            self._event_line(self._stdout)
        self.last_run_dir = self._expected_run
        success = False
        event = self._result or {}
        message = event.get("message") or self._stderr[-2000:] or "The calculation ended without a complete result"
        manifest_path = self._expected_run / "manifest.json"
        owns_run = self._owns_run(manifest_path)
        try:
            if self._cancelled:
                message = "Analysis stopped. Previous results are preserved."
                self._mark_terminal(manifest_path, "cancelled", message)
            elif code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
                manifest = read_manifest(manifest_path)
                self.last_result_paths = self._verified_outputs(manifest)
                success = True
                message = event.get("message") or "Analysis completed. Population totals were verified."
            else:
                if self._stderr.strip():
                    self.logger.error("Engine diagnostics:\n" + self._stderr)
        except Exception as exc:
            message = f"Could not verify results: {exc}"
        finally:
            try:
                if not success and not self._cancelled:
                    self._mark_terminal(manifest_path, "failed", message)
            except (OSError, ValueError, TypeError) as exc:
                self.logger.warning(f"Could not record the failed run: {exc}")
            finally:
                try:
                    if owns_run:
                        self._cleanup_run_scratch()
                except OSError as exc:
                    self.logger.warning(f"Could not remove temporary calculation files: {exc}")
                finally:
                    self._release()
        try:
            self.analysis_finished(success, message)
        except Exception as exc:
            self.logger.error(f"The calculation ended, but the interface could not refresh: {exc}")
        finally:
            self.completed.emit()

    def _owns_run(self, path):
        """CLI run_dir=None explicitly means output allocation never succeeded."""
        if (not self._config_file or not self._run_root_safe() or
                not path.parent.is_dir() or self._is_link(path)):
            return False
        event = self._result
        if event is not None and event.get("run_dir") is None:
            return False
        if event is not None and event.get("status") in ("complete", "failed", "cancelled"):
            run_dir = event.get("run_dir")
            try:
                if isinstance(run_dir, str) and Path(run_dir).resolve() == self._expected_run.resolve():
                    return True
            except (OSError, ValueError, RuntimeError):
                return False
        # Forced termination may prevent a result event. The initial CLI manifest
        # records the unique parent-owned snapshot, unlike an earlier run's config.
        try:
            if self._config_file and path.is_file() and path.stat().st_size <= 4 * 1024 * 1024:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                return (isinstance(manifest, dict) and
                        manifest.get("config") == str(self._config_file))
        except (OSError, ValueError, UnicodeError):
            pass
        return False

    @staticmethod
    def _is_link(path):
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())

    def _run_root_safe(self):
        try:
            return (self._expected_run is not None and self._canonical_run is not None and
                    not self._is_link(self._expected_run) and
                    self._expected_run.resolve() == self._canonical_run)
        except (OSError, ValueError, RuntimeError):
            return False

    def _cleanup_run_scratch(self):
        """Called only after this child ended and ownership was established."""
        if not self._run_root_safe():
            return
        root = self._canonical_run
        for candidate in self._expected_run.glob("grids-*"):
            target = candidate.resolve()
            if (self._is_link(candidate) or not candidate.is_dir() or
                    target.parent != root or target == root):
                continue
            if any(self._is_link(entry) for entry in candidate.rglob("*")):
                self.logger.warning(f"Temporary files contain a symbolic link; retained: {candidate.name}")
                continue
            shutil.rmtree(target)

    def _mark_terminal(self, path, status, message):
        if not self._owns_run(path):
            return
        manifest = {}
        if path.is_file() and path.stat().st_size <= 4 * 1024 * 1024:
            try:
                manifest = read_manifest(path)
            except (ValueError, TypeError):
                manifest = {}
        manifest.update(schema_version=1, status=status, message=message, outputs=[],
                        config=str(self._config_file))
        descriptor, name = tempfile.mkstemp(prefix=".gui-terminal-", suffix=".tmp", dir=path.parent)
        pending = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            atomic_replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)

    def _release(self):
        process = self.process
        self.process = None
        if process:
            process.deleteLater()
        if self._exit_guard:
            try:
                self._exit_guard.close()
            except Exception as exc:
                self.logger.warning(f"Could not close engine process tracking handles: {exc}")
            self._exit_guard = None
        if self._job:
            try:
                self._job.cleanup()
            except OSError as exc:
                self.logger.warning(f"Could not remove temporary job metadata: {exc}")
            self._job = None

    def analysis_finished(self, success, message):
        self._set_ui_enabled(True)
        if success:
            self.dialog.mainProgressBar.setValue(100)
            if self.iface and self.dialog.addToQgisCheckBox.isChecked():
                self.add_output_layers()
            self.logger.info(message)
        else:
            self.logger.warning(message)
        if success or self._cancelled or not message.strip():
            self.dialog.set_task_status(message)
        else:
            # Engine diagnostics end with the actual error; the full text is in Details.
            self.dialog.set_task_status("Analysis could not be completed: " + message.strip().splitlines()[-1])
        if hasattr(self.dialog, "refresh_results"):
            # Only a verified run takes the selection; failed attempts stay listed.
            self.dialog.refresh_results(select=self.last_run_dir if success else None)

    def update_progress(self, value, message):
        self.dialog.set_task_status(message, value)
        self.logger.info(message)

    def _set_ui_enabled(self, enabled):
        self.dialog.set_input_widgets_enabled(enabled)
        self.dialog.workingDirEdit.setEnabled(enabled)
        self.dialog.initProjectButton.setEnabled(enabled)
        self.dialog.set_settings_widgets_enabled(enabled)
        self.dialog.setupRuntimeButton.setEnabled(enabled)
        self.dialog.browsePythonButton.setEnabled(enabled)
        self.dialog.pythonPathEdit.setEnabled(enabled)
        self.dialog.mainStartButton.setText("Run analysis" if enabled else "Stop")
        self.dialog.mainStartButton.setEnabled(True)

    def _validate_all(self):
        if not self.dialog.config_manager.config_path:
            self.logger.error("Create or open a project first")
            if hasattr(self.dialog, "set_task_status"):
                self.dialog.set_task_status("Create or open a project first")
            return False
        if not getattr(self.dialog, "_project_ready", True):
            self.logger.error("Open the selected project before starting")
            if hasattr(self.dialog, "set_task_status"):
                self.dialog.set_task_status("Open the selected project before starting")
            return False
        valid = self.dialog.settings_handler.validate_settings(self.dialog)
        if not valid and hasattr(self.dialog, "set_task_status"):
            self.dialog.set_task_status("Input or processing settings need attention; see Details for the specific errors")
        return valid

    def add_output_layers(self):
        if not self.iface or not self.last_run_dir:
            return
        if hasattr(self.dialog, "layer_integration"):
            self.dialog.layer_integration.iface = self.iface
            self.output_layers.extend(self.dialog.layer_integration.add_run(self.last_run_dir, self.last_result_paths))
            return
        for path in self.last_result_paths:
            layer = self.iface.addRasterLayer(str(path), path.stem)
            if layer and layer.isValid():
                self.output_layers.append(layer)
            else:
                self.logger.warning(f"Could not load result layer: {path}")
