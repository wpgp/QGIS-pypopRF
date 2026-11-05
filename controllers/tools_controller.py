"""Cancellable isolated data tools; no numerical imports in the QGIS process."""
import json
import math
from pathlib import Path
import tempfile
from uuid import uuid4

from qgis.PyQt.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal
from ..services.process_exit_guard import ProcessExitGuard
from ..services.engine_snapshot import create_engine_snapshot, engine_arguments


def validate_population_summary(summary):
    """Reject malformed or scientifically inconsistent coverage declarations."""
    if not isinstance(summary, dict):
        raise ValueError("The population summary must be an object")
    selected, valid = summary.get("selected_cells"), summary.get("valid_cells")
    if type(selected) is not int or type(valid) is not int or not 0 <= valid <= selected:
        raise ValueError("Population summary cell counts are invalid")
    population = summary.get("sum_persons")
    try:
        finite = math.isfinite(population) if type(population) in (int, float) else False
    except OverflowError:
        finite = False
    if not finite or population < 0 or (valid == 0 and population != 0):
        raise ValueError("Population summary must contain a finite nonnegative count")
    coverage = summary.get("coverage_fraction")
    if selected:
        if (type(coverage) not in (int, float) or not 0 <= coverage <= 1 or not math.isfinite(coverage)
                or not math.isclose(coverage, valid / selected, rel_tol=1e-9, abs_tol=1e-12)):
            raise ValueError("Population summary coverage is invalid or inconsistent")
    elif coverage is not None:
        raise ValueError("Coverage is undefined when no raster cell centers were selected")
    complete, extends = summary.get("complete_coverage"), summary.get("aoi_extends_outside_raster")
    if (type(complete) is not bool or type(extends) is not bool or
            complete != bool(selected and valid == selected and not extends)):
        raise ValueError("Population summary cannot claim inconsistent complete coverage")
    if summary.get("inclusion") != "cell_center" or summary.get("units") != "persons_per_pixel":
        raise ValueError("Population summary did not declare count units and cell-center inclusion")
    if type(summary.get("display_persons")) is not int or summary["display_persons"] != round(population):
        raise ValueError("Rounded population display is inconsistent with the computed sum")
    return summary


class ToolsController(QObject):
    progress = pyqtSignal(int, str)
    resultReady = pyqtSignal(object)
    completed = pyqtSignal()
    busyChanged = pyqtSignal(bool)
    MAX_EVENT = 256 * 1024
    MAX_REPORT = 4 * 1024 * 1024

    def __init__(self, dialog, logger):
        super().__init__(dialog)
        self.dialog, self.logger = dialog, logger
        self.process = None
        self._job = None
        self._buffer = b""
        self._stderr = ""
        self._event = None
        self._cancelled = False
        self._operation = None
        self._output = None
        self._request_id = None
        self._exit_guard = None
        self._guard_warning = False
        self._waiting_exit = False

    @property
    def is_running(self):
        return self.process is not None

    def start(self, request):
        if self.is_running or self.dialog.is_busy:
            return False
        python = self.dialog.runtime_controller.python
        if not python:
            self.logger.error("Set up the analysis engine before preparing data")
            return False
        try:
            if not isinstance(request, dict) or request.get("operation") not in (
                    "inspect", "prepare", "population_summary"):
                raise ValueError("Unsupported data tool request")
            request = dict(request, schema_version=1)
            self._request_id = uuid4().hex
            request["request_id"] = self._request_id
            jobs = Path(self.dialog.job_cache)
            jobs.mkdir(parents=True, exist_ok=True)
            self._job = tempfile.TemporaryDirectory(prefix="tools-", dir=jobs)
            request.setdefault("output_dir", str(Path(self._job.name) / "result"))
            self._output = Path(request["output_dir"]).resolve()
            if self._output.exists():
                raise ValueError("Choose a new output project directory; existing files are never overwritten")
            request["output_dir"] = str(self._output)
            self._operation = request["operation"]
            self._marker = Path(self._job.name) / "cancel"
            config = Path(self._job.name) / "request.json"
            config.write_text(json.dumps(request, ensure_ascii=True), encoding="utf-8")
            engine_source = create_engine_snapshot(self.dialog.plugin_root, Path(self._job.name))
            self._buffer, self._stderr, self._event = b"", "", None
            self._cancelled = False
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
            process.setArguments(engine_arguments(engine_source, "core.pypoprf.tools", [
                "--request", str(config), "--cancel-file", str(self._marker)]))
            process.readyReadStandardOutput.connect(lambda owned=process: self._read_stdout(owned))
            process.readyReadStandardError.connect(lambda owned=process: self._read_stderr(owned))
            process.finished.connect(lambda code, status, owned=process: self._finished(code, status, owned))
            process.errorOccurred.connect(lambda error, owned=process: self._error(error, owned))
            self.busyChanged.emit(True)
            process.start()
            return True
        except Exception as exc:
            self.logger.error(f"Could not start data preparation: {exc}")
            self._release()
            self.busyChanged.emit(False)
            try:
                self.resultReady.emit({"success": False, "cancelled": False,
                    "operation": request.get("operation") if isinstance(request, dict) else None,
                    "report": None, "output_dir": None, "message": f"Could not start data tool: {exc}"})
            finally:
                self.completed.emit()
            return False

    def stop(self):
        if self.process is None or self._cancelled:
            return
        self._cancelled = True
        owned = self.process
        try:
            self._marker.touch()
        except OSError as exc:
            self.logger.warning(f"Could not request a graceful stop: {exc}")
            owned.kill()
        self.progress.emit(0, "Stopping the data tool…")
        QTimer.singleShot(30000, lambda: self._force_stop(owned))

    def _force_stop(self, owned):
        if self.process is owned and self._cancelled:
            self.logger.warning("The data tool did not respond; stopping its owned process")
            owned.kill()

    def _read_stdout(self, owned):
        if self.process is owned:
            self._consume(bytes(owned.readAllStandardOutput()))

    def _consume(self, data):
        self._buffer += data
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if len(line) <= self.MAX_EVENT:
                self._line(line)
        if len(self._buffer) > self.MAX_EVENT:
            self._buffer = b""
            self.logger.warning("An oversized data-tool message was ignored")

    def _line(self, line):
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                return
            if event.get("event") == "progress" and event.get("request_id") == self._request_id:
                percent, message = event.get("percent"), event.get("message")
                if type(percent) is int and 0 <= percent <= 100 and isinstance(message, str):
                    self.progress.emit(percent, message[:2000])
            elif event.get("event") == "result":
                self._event = event
        except (ValueError, UnicodeError):
            pass

    def _read_stderr(self, owned):
        if self.process is owned:
            self._stderr = (self._stderr + bytes(owned.readAllStandardError()).decode(
                "utf-8", errors="replace"))[-65536:]

    def _error(self, error, owned):
        if self.process is owned and error == QProcess.ProcessError.FailedToStart:
            self._stderr = owned.errorString()
            self._finished(-1, QProcess.ExitStatus.CrashExit, owned)

    def _started(self, owned, guard):
        if self.process is not owned or self._exit_guard is not guard:
            return
        try:
            guard.begin(int(owned.processId()))
        except Exception as exc:
            self._guard_warning = True
            self.logger.error(f"Could not track data-tool exit; temporary files will be retained until exit is verified: {exc}")

    @staticmethod
    def _is_link(path):
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())

    def _contained_file(self, value, filename):
        if not isinstance(value, str) or not value:
            raise ValueError("The data tool did not publish its result file")
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("The data tool returned a noncanonical path")
        if self._is_link(self._output) or self._output.resolve() != self._output:
            raise ValueError("The result directory was redirected")
        if path != self._output / filename:
            raise ValueError("The data tool returned an unexpected result filename")
        for component in (path, *path.parents):
            if self._is_link(component):
                raise ValueError("The data tool result uses a redirected path")
            if component == self._output:
                break
        canonical = path.resolve()
        if not canonical.is_relative_to(self._output) or not canonical.is_file() or path.is_symlink():
            raise ValueError("The data tool result is missing or outside its output directory")
        return canonical

    def _verified_result(self):
        event = self._event or {}
        if (event.get("status") != "complete" or not isinstance(event.get("output_dir"), str)
                or Path(event["output_dir"]).resolve() != self._output or
                event.get("request_id") != self._request_id):
            raise ValueError("The data tool did not publish a complete owned result")
        report_path = self._contained_file(event.get("report_path"), "report.json")
        with report_path.open("rb") as stream:
            data = stream.read(self.MAX_REPORT + 1)
        if len(data) > self.MAX_REPORT:
            raise ValueError("The preparation report is unexpectedly large")
        def invalid_constant(value):
            raise ValueError(f"The data tool report contains a nonfinite JSON value: {value}")
        report = json.loads(data, parse_constant=invalid_constant)
        if (not isinstance(report, dict) or type(report.get("schema_version")) is not int or
                report.get("schema_version") != 1 or report.get("status") != "complete"):
            raise ValueError("The preparation report has an unsupported format")
        if report.get("operation") != self._operation or report.get("request_id") != self._request_id:
            raise ValueError("The preparation report belongs to another operation")
        if type(report.get("ready")) is not bool:
            raise ValueError("The preparation report has no validated readiness status")
        for field in ("errors", "warnings"):
            records = report.get(field)
            if not isinstance(records, list) or any(not isinstance(record, dict) or
                    not isinstance(record.get("message"), str) for record in records):
                raise ValueError("The preparation diagnostics have an invalid format")
        result = {"success": True, "cancelled": False, "message": event.get("message") or "Data tool completed",
                  "operation": self._operation, "report": report, "output_dir": str(self._output)}
        if self._operation == "prepare":
            if report.get("ready") is not True:
                raise ValueError("The prepared project did not pass input validation")
            config_path = self._contained_file(event.get("config_path"), "config.yaml")
            if report.get("config_path") != str(config_path):
                raise ValueError("Prepared configuration metadata is inconsistent")
            result["config_path"] = str(config_path)
        elif self._operation == "population_summary" and report.get("ready") is not True:
            raise ValueError("The population summary did not pass input validation")
        if self._operation == "population_summary":
            validate_population_summary(report.get("summary"))
        return result

    def _finished(self, code, status, owned):
        if self.process is not owned:
            return
        try:
            reaped = self._exit_guard is None or self._exit_guard.exited()
        except Exception as exc:
            reaped = False
            if not self._guard_warning:
                self._guard_warning = True
                self.logger.error(f"Could not verify data-tool exit; tasks and temporary files are retained: {exc}")
        if not reaped:
            if not self._waiting_exit:
                self._waiting_exit = True
                self.progress.emit(0, "Waiting for the data-tool process to exit before cleaning up…")
            QTimer.singleShot(20, lambda: self._finished(code, status, owned))
            return
        output = self._output
        result = {"success": False, "cancelled": self._cancelled, "operation": self._operation,
                  "report": None, "output_dir": str(self._output),
                  "message": "Data tool stopped; your existing project and source data were not changed"}
        try:
            self._read_stdout(owned)
            self._read_stderr(owned)
            if self._buffer.strip():
                self._line(self._buffer)
            if not self._cancelled:
                if code == 0 and status == QProcess.ExitStatus.NormalExit:
                    result = self._verified_result()
                else:
                    event = self._event or {}
                    result["message"] = event.get("message") or self._stderr[-2000:] or "Data tool failed; see Details"
                if self._stderr.strip():
                    self.logger.error("Data tool diagnostics:\n" + self._stderr)
        except Exception as exc:
            result["message"] = f"Could not verify data-tool results: {exc}"
        finally:
            self._release()
            if result["cancelled"] and result["operation"] == "prepare":
                try:
                    # Check after owned job cleanup: temporary results may have
                    # disappeared, but an external prepared directory is kept.
                    if output.is_dir():
                        result["message"] += (f". New output directory remains at {output}. "
                                              "It may be incomplete; review before reuse.")
                except OSError as exc:
                    self.logger.warning(f"Could not inspect the stopped preparation output: {exc}")
            self.busyChanged.emit(False)
        try:
            self.resultReady.emit(result)
        finally:
            self.completed.emit()

    def _release(self):
        process, self.process = self.process, None
        if process:
            process.deleteLater()
        if self._exit_guard:
            try:
                self._exit_guard.close()
            except Exception as exc:
                self.logger.warning(f"Could not close data-tool process tracking handles: {exc}")
            self._exit_guard = None
        if self._job:
            try:
                self._job.cleanup()
            except OSError as exc:
                self.logger.warning(f"Could not remove temporary tool metadata: {exc}")
            self._job = None
