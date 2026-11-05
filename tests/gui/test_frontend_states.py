"""Qt-free engine view state, next-step routing and run-action role contracts."""
import pytest

from .test_qgis_safety import adapter as adapter


@pytest.mark.parametrize("operation", ["check", "discover", "inspect"])
@pytest.mark.parametrize("ready", [False, True])
def test_running_checks_never_claim_missing_python_or_readiness(adapter, operation, ready):
    status = adapter("workflow_status")
    # Even with "nothing found so far", a running check is only "checking".
    assert status.engine_view_state(operation, ready, False, True, False) == status.ENGINE_CHECKING


def test_setup_is_distinct_from_choosing_an_interpreter(adapter):
    status = adapter("workflow_status")
    assert status.engine_view_state("setup", False, True, False, False) == status.ENGINE_INSTALLING
    assert status.engine_view_state(None, False, True, False, False) == status.ENGINE_SELECTED
    assert status.engine_view_state(None, True, True, False, False) == status.ENGINE_READY


def test_no_python_requires_completed_empty_discovery(adapter):
    status = adapter("workflow_status")
    assert status.engine_view_state(None, False, False, True, False) == status.ENGINE_NO_PYTHON
    # Cancelled/failed discovery is not evidence that no interpreter exists.
    assert status.engine_view_state(None, False, False, False, False) == status.ENGINE_UNDISCOVERED


def test_failed_repair_keeps_ready_engine_visible_as_failure(adapter):
    status = adapter("workflow_status")
    assert status.engine_view_state(None, True, False, False, True) == status.ENGINE_REPAIR_FAILED
    assert status.engine_view_state(None, False, True, False, True) == status.ENGINE_FAILED


@pytest.mark.parametrize("state,expected", [
    ({}, "project"), ({"project_ready": True}, "inputs"),
    ({"project_ready": True, "inputs_ready": True}, "review"),
    ({"project_ready": "yes", "inputs_ready": True}, "project"), (None, "project")])
def test_engine_next_step_follows_live_state_only(adapter, state, expected):
    status = adapter("workflow_status")
    assert status.engine_next_step(state)[0] == expected


@pytest.mark.parametrize("text,role", [
    ("Run analysis", "run"), ("Stop", "stop"), ("Stop data tool", "stop"), ("Cancel import", "stop"),
    ("Stopping…", "stopping"), ("Stopping import…", "stopping"), ("Stopping data tool…", "stopping")])
def test_run_action_role_mirrors_every_controller_text(adapter, text, role):
    assert adapter("workflow_status").run_action_role(text) == role


def test_interpreter_label_omits_unknown_metadata_and_shortens_path(adapter):
    status = adapter("workflow_status")
    legacy = status.interpreter_label({"path": "/opt/python", "version": "unknown", "bits": None,
                                       "source": "legacy"}, {"legacy": "Detected"})
    assert legacy == "Python · Detected · /opt/python"
    verified = status.interpreter_label({"path": "C:\\" + "x" * 80 + "\\python.exe", "version": "3.12.10",
                                         "bits": 64, "source": "registry-user", "recommended": True},
                                        {"registry-user": "Installed for you"})
    assert verified.startswith("Python 3.12.10 · 64-bit · Installed for you · Recommended · C:\\")
    assert verified.endswith("python.exe") and len(verified.rsplit(" · ", 1)[1]) == 48
