"""Late prepare cancellation reports retained output without verifying or deleting it."""
import json
from pathlib import Path

import pytest

from .test_qgis_safety import adapter as adapter, tools_for, publish_tool_result, Process


def tool_fixture(adapter, tmp_path, monkeypatch):
    module, tools = tools_for(adapter, tmp_path)
    tools.dialog.plugin_root = tmp_path / "owned-fake-plugin"
    # This fixture exercises completion messaging, not source snapshot creation.
    monkeypatch.setattr(module, "create_engine_snapshot", lambda source, job: Path(job))
    monkeypatch.setattr(module, "engine_arguments", lambda source, name, args: list(args))
    return tools


@pytest.mark.parametrize("published", [True, False])
def test_cancelled_prepare_truthfully_reports_retained_directory(adapter, tmp_path, monkeypatch, published):
    tools = tool_fixture(adapter, tmp_path, monkeypatch)
    output = tmp_path / "prepared"
    results, completed = [], []
    tools.resultReady.connect(results.append)
    tools.completed.connect(lambda: completed.append(not tools.is_running))
    assert tools.start({"operation": "prepare", "output_dir": str(output)})
    owned, job = tools.process, Path(tools._job.name)
    if published:
        _, event = publish_tool_result(tools)
        tools._consume(json.dumps(event).encode() + b"\n")
    else:
        output.mkdir()
        (output / "partial.txt").write_bytes(b"retained incomplete fixture")
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    tools.stop()
    if not published:
        tools._force_stop(owned)
        assert owned.killed
    tools._finished(0 if published else -1,
        Process.ExitStatus.NormalExit if published else Process.ExitStatus.CrashExit, owned)
    result = results[-1]
    assert result["cancelled"] and not result["success"] and result["report"] is None
    assert "New output directory remains at" in result["message"]
    assert str(output.resolve()) in result["message"]
    assert "It may be incomplete; review before reuse" in result["message"]
    assert result["output_dir"] == str(output.resolve())
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    assert not job.exists() and completed == [True]


@pytest.mark.parametrize("operation", ["inspect", "population_summary", "prepare"])
def test_cancel_notice_never_points_to_removed_temporary_result(adapter, tmp_path, monkeypatch, operation):
    tools = tool_fixture(adapter, tmp_path, monkeypatch)
    results = []
    tools.resultReady.connect(results.append)
    assert tools.start({"operation": operation})
    owned = tools.process
    publish_tool_result(tools)
    output = tools._output
    tools.stop()
    tools._finished(0, Process.ExitStatus.NormalExit, owned)
    assert results[-1]["cancelled"] and not results[-1]["success"]
    assert not output.exists()
    assert "New output directory remains" not in results[-1]["message"]


@pytest.mark.parametrize("operation", ["inspect", "population_summary"])
def test_external_nonprepare_results_do_not_receive_prepared_project_notice(adapter, tmp_path, monkeypatch, operation):
    tools = tool_fixture(adapter, tmp_path, monkeypatch)
    results = []
    tools.resultReady.connect(results.append)
    assert tools.start({"operation": operation, "output_dir": str(tmp_path / "external")})
    publish_tool_result(tools)
    tools.stop()
    tools._finished(0, Process.ExitStatus.NormalExit, tools.process)
    assert tools._output.is_dir()
    assert results[-1]["cancelled"] and "New output directory remains" not in results[-1]["message"]


def test_output_probe_error_does_not_suppress_cleanup_or_terminal_signals(adapter, tmp_path, monkeypatch):
    tools = tool_fixture(adapter, tmp_path, monkeypatch)
    results, completions = [], []
    tools.resultReady.connect(results.append)
    tools.completed.connect(lambda: completions.append(not tools.is_running))
    assert tools.start({"operation": "prepare", "output_dir": str(tmp_path / "prepared")})
    job = Path(tools._job.name)
    tools.stop()
    class UnreadableOutput:
        def __str__(self):
            return str(tmp_path / "prepared")
        def is_dir(self):
            raise PermissionError("fixture output probe denied")
    tools._output = UnreadableOutput()
    tools._finished(-1, Process.ExitStatus.CrashExit, tools.process)
    assert results[-1]["cancelled"] and not results[-1]["success"]
    assert completions == [True] and not job.exists()
    assert "New output directory remains" not in results[-1]["message"]


def test_cancelled_prepare_without_published_directory_does_not_claim_retention(adapter, tmp_path, monkeypatch):
    tools = tool_fixture(adapter, tmp_path, monkeypatch)
    results = []
    tools.resultReady.connect(results.append)
    output = tmp_path / "not-created"
    assert tools.start({"operation": "prepare", "output_dir": str(output)})
    tools.stop()
    tools._finished(-1, Process.ExitStatus.CrashExit, tools.process)
    assert results[-1]["cancelled"] and not results[-1]["success"]
    assert not output.exists() and "New output directory remains" not in results[-1]["message"]
