"""Owned asynchronous runtime selection lifecycle using existing Qt doubles."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_qgis_safety import adapter as adapter


def finish(controller):
    worker = controller.worker
    worker.run()
    worker.finished.emit()
    return worker


def test_cold_check_returns_compatible_choices_without_installing(adapter):
    module = adapter("runtime_controller")
    calls = []
    def missing(**kwargs):
        raise module.RuntimeNotReady("No active engine pointer")
    records = [{"path": "/installed/python", "version": "3.12.10", "bits": 64,
                "source": "PATH", "recommended": True, "embedded": False}]
    manager = SimpleNamespace(get_python=missing,
        discover_interpreters=lambda cancellation_token=None: calls.append("discover") or records)
    controller = module.RuntimeController(manager)
    controller.check()
    assert calls == [] and controller.is_running
    finish(controller)
    assert calls == ["discover"] and not controller.is_running
    result = controller.changed.calls[-1][0]
    assert result == {"python": None, "candidates": ["/installed/python"], "interpreters": records,
                      "setup_needed": True, "reason": "No active engine pointer", "error": None,
                      "cancelled": False, "known_invalidated": True}


@pytest.mark.parametrize("error", [None, "Select64-bitCPython3.12"])
def test_async_selection_inspect_does_not_change_healthy_engine(adapter, error):
    module = adapter("runtime_controller")
    calls = []
    def check(path, cancellation_token=None):
        calls.append(path)
        if error:
            raise ValueError(error)
        return {"executable": path, "version": [3, 12, 10], "bits": 64}
    controller = module.RuntimeController(SimpleNamespace(check_interpreter=check))
    controller.python = "/healthy/engine/python"
    assert controller.inspect("/selected/python") is True
    assert calls == [] and controller.python == "/healthy/engine/python"
    assert controller.inspect("/other/python") is False
    finish(controller)
    assert calls == ["/selected/python"] and controller.python == "/healthy/engine/python"
    assert not controller.changed.calls and len(controller.completed.calls) == 1
    result = controller.interpreterChecked.calls[-1][0]
    assert result["path"] == "/selected/python" and result["error"] == error
    assert (result["info"] is not None) is (error is None)


def test_cancel_inspect_never_probes_and_old_callbacks_cannot_finish_new_worker(adapter):
    module = adapter("runtime_controller")
    controller = module.RuntimeController(SimpleNamespace(check_interpreter=lambda *args, **kwargs: pytest.fail("Cancelled probe")))
    controller.python = "healthy"
    controller.inspect("first")
    controller.stop()
    old = finish(controller)
    assert "cancelled" in controller.interpreterChecked.calls[-1][0]["error"]
    controller.inspect("second")
    newer = controller.worker
    old.progress.emit(100, "stale completion")
    old.finished.emit()
    assert controller.worker is newer and controller.is_running
    assert controller.progress.calls == [] and controller.python == "healthy"


def test_failed_setup_keeps_old_engine_and_exposes_failure(adapter):
    module = adapter("runtime_controller")
    def failed(*args, **kwargs):
        raise ValueError("wheel verification failed")
    controller = module.RuntimeController(SimpleNamespace(setup=failed))
    controller.python = "healthy"
    controller.setup(Path("selected"))
    finish(controller)
    result = controller.changed.calls[-1][0]
    assert result["python"] == "healthy" and "verification" in result["error"]
    assert result["setup_needed"] is True


def test_explicit_find_again_discovers_even_when_engine_is_healthy(adapter):
    module = adapter("runtime_controller")
    calls = []
    choices = [{"path": "installed", "version": "3.12.10", "bits": 64,
                "source": "PATH", "recommended": True, "embedded": False}]
    manager = SimpleNamespace(get_python=lambda **kwargs: Path("healthy"),
        discover_interpreters=lambda **kwargs: calls.append("discover") or choices)
    controller = module.RuntimeController(manager)
    controller.check()
    finish(controller)
    assert calls == []
    controller.check(discover=True)
    finish(controller)
    result = controller.changed.calls[-1][0]
    assert calls == ["discover"] and result["python"] == "healthy"
    assert result["interpreters"] == choices and not result["setup_needed"] and result["reason"] is None


def test_optional_discovery_failure_keeps_engine_just_health_verified(adapter):
    module = adapter("runtime_controller")
    def cancelled(**kwargs):
        kwargs["cancellation_token"].cancel()
        raise module.SetupCancelled("Discovery cancelled")
    manager = SimpleNamespace(get_python=lambda **kwargs: Path("healthy"), discover_interpreters=cancelled)
    controller = module.RuntimeController(manager)
    controller.check(discover=True)
    finish(controller)
    result = controller.changed.calls[-1][0]
    assert controller.python == "healthy" and result["error"] == "Discovery cancelled"
    assert result["setup_needed"] is False


def test_cancel_during_health_probe_preserves_previous_engine_without_invalidation(adapter):
    module = adapter("runtime_controller")
    def health(cancellation_token=None):
        cancellation_token.cancel()
        cancellation_token.check()
    controller = module.RuntimeController(SimpleNamespace(get_python=health))
    controller.python = "previously-verified"
    controller.check(discover=True)
    finish(controller)
    result = controller.changed.calls[-1][0]
    assert result["cancelled"] and not result["known_invalidated"]
    assert result["python"] == controller.python == "previously-verified"
    assert result["setup_needed"] is False and not controller.is_running


def test_cancel_after_real_health_invalidation_does_not_restore_previous_engine(adapter):
    module = adapter("runtime_controller")
    def invalid(**kwargs):
        raise module.RuntimeNotReady("Engine lock no longer matches")
    def discover(cancellation_token=None):
        cancellation_token.cancel()
        cancellation_token.check()
    controller = module.RuntimeController(SimpleNamespace(get_python=invalid, discover_interpreters=discover))
    controller.python = "previously-verified"
    controller.check(discover=True)
    finish(controller)
    result = controller.changed.calls[-1][0]
    assert result["cancelled"] and result["known_invalidated"]
    assert result["python"] is None and controller.python is None
    assert result["setup_needed"] is True and not controller.is_running
