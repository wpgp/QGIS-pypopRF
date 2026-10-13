"""Dedicated-process native installer qualification, never a real QGIS profile.

The parent supplies an owned pytest directory, nonce marker and validated ZIP.
All Qt/QGIS imports occur after profile/environment isolation. The installer
and qgis.utils lifecycle functions are real; only network/UI interfaces are
replaced with local test endpoints.
"""
import json
import gc
import hashlib
import os
from pathlib import Path
import sys
import time
import zipfile
import weakref
import shutil


def wait_until(app, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate(), "Owned native operation did not reach its terminal state"


def owned_child_alive(controller):
    """ExitGuard's POSIX path is intentionally only a post-Qt-finished no-op."""
    if os.name == "nt":
        return not controller._exit_guard.exited()
    process = controller.process
    if process is None or process.processId() <= 0:
        return False
    try:
        os.kill(int(process.processId()), 0)  # Read-only check of this QProcess PID.
    except ProcessLookupError:
        return False
    return True


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    nonce, archive = sys.argv[2], Path(sys.argv[3]).resolve(strict=True)
    scenario = sys.argv[4] if len(sys.argv) > 4 else "idle_update_reinstall"
    assert scenario in {"idle_update_reinstall", "busy_unload", "probe_unload", "failed_tool",
                        "corrupt_archive", "incomplete_archive", "gc_busy_unload",
                        "legacy_migration_prepare", "legacy_migration_finish"}
    assert (root / "owned-sandbox.txt").read_text() == nonce
    assert root != Path.cwd().resolve() and root != Path.home().resolve()

    def contained(path):
        path = Path(path)
        assert path.resolve().is_relative_to(root), str(path)
        for entry in (path, *path.parents):
            assert not entry.is_symlink()
            assert not (hasattr(entry, "is_junction") and entry.is_junction())
            if entry == root:
                break
        return path

    home, profile, cache = root / "home", root / "profile", root / "cache"
    for directory in (home, profile, cache):
        if scenario == "legacy_migration_finish":
            assert contained(directory).is_dir()
        else:
            contained(directory).mkdir()
    for name, directory in {
        "HOME": home, "USERPROFILE": home, "APPDATA": home / "roaming",
        "LOCALAPPDATA": home / "local", "XDG_CONFIG_HOME": home / "config",
        "XDG_CACHE_HOME": cache, "QGIS_CUSTOM_CONFIG_PATH": profile,
        "QGIS_OPTIONS_PATH": profile,
    }.items():
        os.environ[name] = str(contained(directory))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if os.name == "nt":
        os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"))

    from qgis.PyQt.QtCore import QCoreApplication, QSettings, QObject, QEvent
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(profile))
    from qgis.core import (QgsApplication, QgsSettings, QgsProject, QgsVectorLayer,
                           QgsSettingsTree, QgsSettingsEntryString, QgsSettingsEntryBool,
                           QgsSettingsEntryStringList)
    from qgis.PyQt.QtWidgets import QMainWindow
    app = QgsApplication([], True, str(profile))
    QCoreApplication.setOrganizationName("pypoprf-owned-update-test")
    QCoreApplication.setApplicationName("installer-sandbox")
    # These assertions precede ALL settings/installer writes. Registry paths
    # and non-isolated profile paths fail closed rather than being restored.
    settings = QgsSettings()
    settings_file = contained(settings.fileName())
    settings.setValue("sandbox/nonce", nonce)
    settings.sync()
    assert settings_file.is_file()
    app.initQgis()
    contained(QgsApplication.qgisSettingsDirPath())
    # initQgis may switch the active profile/settings prefix. Do not retain
    # a pre-init settings instance for persistent plugin enable/disable flags.
    settings = QgsSettings()
    settings_file = contained(settings.fileName())
    # The desktop normally registers this application-level settings node;
    # QgsApplication-only acceptance must register its real entry explicitly.
    manager_node = QgsSettingsTree.node("plugin-manager")
    if manager_node is None:
        manager_node = QgsSettingsTree.treeRoot().createChildNode("plugin-manager")
    settings_entries = [
        QgsSettingsEntryString("last-zip-directory", manager_node, ""),
        QgsSettingsEntryBool("allow-experimental", manager_node, False),
        QgsSettingsEntryBool("allow-deprecated", manager_node, False),
        QgsSettingsEntryStringList("seen-plugins", manager_node, []),
    ]
    assert len(settings_entries) == 4

    import qgis.utils as utils
    import pyplugin_installer.installer as installer_module
    import pyplugin_installer.installer_data as installer_data
    plugins_dir = contained(profile / "python" / "plugins")
    if scenario == "legacy_migration_finish":
        assert plugins_dir.is_dir()
    else:
        plugins_dir.mkdir(parents=True)
    utils.HOME_PLUGIN_PATH = str(plugins_dir)
    utils.plugin_paths[:] = [str(plugins_dir)]
    installer_module.HOME_PLUGIN_PATH = str(plugins_dir)
    installer_data.HOME_PLUGIN_PATH = str(plugins_dir)
    installer_data.plugin_paths = utils.plugin_paths
    sys.path.insert(0, str(plugins_dir))
    with zipfile.ZipFile(archive) as bundle:
        metadata = [name for name in bundle.namelist() if name.endswith("/metadata.txt")]
        assert len(metadata) == 1
        plugin_name = metadata[0].split("/")[0]
        assert plugin_name.isidentifier()
        for name in bundle.namelist():
            assert name.startswith(plugin_name + "/") and ".." not in Path(name).parts
    plugin_dir = contained(plugins_dir / plugin_name)
    messages, actions = [], []

    class Iface:
        def __init__(self):
            self.window = QMainWindow()
        def mainWindow(self):
            return self.window
        def pluginManagerInterface(self):
            return self
        def pushMessage(self, *args, **kwargs):
            messages.append([str(value) for value in args])
        def addToolBarIcon(self, action):
            actions.append(action)
        def addPluginToMenu(self, *args):
            pass
        def removePluginMenu(self, *args):
            pass
        def removeToolBarIcon(self, action):
            actions.remove(action)
        def messageBar(self):
            return self

    iface = Iface()
    utils.iface = installer_module.iface = iface
    # Expected broken-package diagnostics must not enter a modal stack dialog.
    utils.open_stack_dialog = lambda *args: messages.append(["expected stack diagnostic"])

    class LocalInstaller(installer_module.QgsPluginInstaller):
        def __init__(self):
            # Do not initialize repository fetching or change repository state.
            QObject.__init__(self)
        def processDependencies(self, name):
            assert name == plugin_name
        def exportPluginsToManager(self):
            pass

    installer = LocalInstaller()
    if scenario == "legacy_migration_finish":
        assert os.name == "nt"
        assert not QgsSettings().value("/PythonPlugins/" + plugin_name, True, type=bool)
    assert installer.installFromZipFile(str(archive))
    if scenario == "legacy_migration_finish":
        assert not utils.isPluginLoaded(plugin_name)
        assert utils.loadPlugin(plugin_name) and utils.startPlugin(plugin_name)
        settings.setValue("/PythonPlugins/" + plugin_name, True)
        settings.sync()
    assert utils.isPluginLoaded(plugin_name)
    assert plugin_dir.is_dir() and plugin_name in utils._plugin_modules
    original = utils.plugins[plugin_name]
    package = sys.modules[plugin_name]
    memory = QgsVectorLayer("Point?crs=EPSG:3857", "owned-update-test-layer", "memory")
    QgsProject.instance().addMapLayer(memory)
    layer_id = memory.id()
    if scenario.startswith("legacy_migration_"):
        assert os.name == "nt"
        user_data = contained(root / "user-data")
        migration = contained(root / "migration-state.json")
        copied_dll = contained(plugin_dir / "owned-legacy-version.dll")
        if scenario == "legacy_migration_prepare":
            import ctypes
            user_data.mkdir()
            csv = user_data / "census.csv"
            csv.write_text("id,pop\n1,20\n", encoding="utf-8")
            area_file = user_data / "area.geojson"
            area_file.write_text(json.dumps({"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {"id": 1},
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
            }]}), encoding="utf-8")
            area = QgsVectorLayer(str(area_file), "legacy-area", "ogr")
            assert area.isValid()
            QgsProject.instance().addMapLayer(area)
            project_file = user_data / "session.qgs"
            assert QgsProject.instance().write(str(project_file))
            system_dll = Path(os.environ["SystemRoot"]) / "System32" / "version.dll"
            source_sha = hashlib.sha256(system_dll.read_bytes()).hexdigest()
            shutil.copy2(system_dll, copied_dll)
            loaded = ctypes.WinDLL(str(copied_dll))
            assert loaded._handle
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
            kernel.GetModuleFileNameW.restype = ctypes.c_uint32
            module_path = ctypes.create_unicode_buffer(32768)
            length = kernel.GetModuleFileNameW(loaded._handle, module_path, len(module_path))
            assert 0 < length < len(module_path)
            assert Path(module_path.value).resolve() == copied_dll.resolve()
            assert utils.unloadPlugin(plugin_name)
            settings.setValue("/PythonPlugins/" + plugin_name, False)
            settings.sync()
            # Never FreeLibrary or force-delete a loaded DLL. Windows can allow
            # image renames while denying removal, so probe ordinary deletion
            # of this exact nonce-scoped COPY, never the system source.
            try:
                copied_dll.unlink()
            except OSError as exc:
                assert getattr(exc, "winerror", None) in {5, 32, 33}
            else:
                raise AssertionError("Expected Windows loaded-image sharing protection")
            assert hashlib.sha256(copied_dll.read_bytes()).hexdigest() == source_sha
            assert hashlib.sha256(system_dll.read_bytes()).hexdigest() == source_sha
            files = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (csv, area_file, project_file)}
            migration.write_text(json.dumps({"files": files, "system_dll_sha256": source_sha}), encoding="utf-8")
            result = {"status": "complete", "scenario": scenario,
                "settings_file": str(settings_file), "plugins_dir": str(plugins_dir),
                "loaded_fixture_remained_locked_after_unload": True,
                "plugin_disabled_for_next_start": True, "system_dll_unchanged": True}
        else:
            state = json.loads(migration.read_text())
            system_dll = Path(os.environ["SystemRoot"]) / "System32" / "version.dll"
            assert hashlib.sha256(system_dll.read_bytes()).hexdigest() == state["system_dll_sha256"]
            assert not copied_dll.exists(), "Actual ZIP installer must replace the unlocked legacy directory"
            assert all(hashlib.sha256(contained(root / name).read_bytes()).hexdigest() == digest
                       for name, digest in state["files"].items())
            assert QgsProject.instance().read(str(user_data / "session.qgs"))
            areas = [layer for layer in QgsProject.instance().mapLayers().values() if layer.name() == "legacy-area"]
            assert len(areas) == 1 and areas[0].isValid()
            assert utils.isPluginLoaded(plugin_name)
            assert utils.unloadPlugin(plugin_name)
            result = {"status": "complete", "scenario": scenario,
                "settings_file": str(settings_file), "plugins_dir": str(plugins_dir),
                "same_profile_fresh_process_install_enable": True,
                "manual_folder_delete": False, "saved_project_and_data_preserved": True}
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        print("INSTALLER_SANDBOX_RESULT=" + json.dumps(result))
        QgsProject.instance().clear()
        app.exitQgis()
        return
    # Disable actual runtime probing/setup by injecting only the runtime API.
    # Lifecycle widgets, Qt event handling and installer functions remain real.
    dialog_module = __import__(plugin_name + ".gui.dialogs.main_dialog", fromlist=["PyPopRFDialog"])
    runtime_module = __import__(plugin_name + ".services.runtime_manager", fromlist=["RuntimeNotReady"])

    class NoInstallRuntime:
        def get_python(self, cancellation_token=None):
            if cancellation_token:
                cancellation_token.check()
            if scenario == "probe_unload":
                while True:
                    cancellation_token.check()
                    time.sleep(0.01)
            if scenario in {"busy_unload", "gc_busy_unload", "failed_tool"}:
                engine = os.environ.get("PYPOPRF_TEST_ENGINE")
                if os.name == "nt" and not engine:
                    raise RuntimeError("Windows installer fixture requires PYPOPRF_TEST_ENGINE (standalone managed Python, not portable QGIS Python)")
                return Path(engine or sys.executable)
            raise runtime_module.RuntimeNotReady("No runtime setup during installer test")
        def detect_python_candidates(self, cancellation_token=None):
            return []
        def child_environment(self, python=None):
            return runtime_module.RuntimeManager.child_environment(python)

    original.dlg = dialog_module.PyPopRFDialog(iface=iface, parent=iface.window,
        runtime_manager=NoInstallRuntime(), cache_root=root / "plugin-cache")
    if scenario == "probe_unload":
        dialog = original.dlg
        assert dialog.runtime_controller.is_running
        assert utils.unloadPlugin(plugin_name)
        assert plugin_name not in sys.modules
        wait_until(app, lambda: original.dlg is None)
        assert not dialog.runtime_controller.is_running
        result = {"status": "complete", "scenario": scenario,
            "settings_file": str(settings_file), "plugins_dir": str(plugins_dir),
            "unload_removed_modules": True, "owned_probe_reaped": True}
        print("INSTALLER_SANDBOX_RESULT=" + json.dumps(result))
        QgsProject.instance().clear()
        app.exitQgis()
        return
    wait_until(app, lambda: not original.dlg.is_busy)
    if scenario in {"corrupt_archive", "incomplete_archive"}:
        damaged = contained(root / "damaged.zip")
        before_metadata = (plugin_dir / "metadata.txt").read_bytes()
        before_form = (plugin_dir / "gui" / "forms" / "main_dialog.ui").read_bytes()
        if scenario == "corrupt_archive":
            damaged.write_bytes(b"owned test fixture, not a ZIP")
            try:
                installer.installFromZipFile(str(damaged))
            except zipfile.BadZipFile:
                pass
            else:
                raise AssertionError("The malformed ZIP was unexpectedly accepted")
            assert utils.plugins[plugin_name] is original
            assert (plugin_dir / "metadata.txt").read_bytes() == before_metadata
            assert (plugin_dir / "gui" / "forms" / "main_dialog.ui").read_bytes() == before_form
            observed = {"invalid_zip_preserved_active_plugin": True}
        else:
            with zipfile.ZipFile(damaged, "w") as bundle:
                bundle.writestr(plugin_name + "/metadata.txt", before_metadata)
                bundle.writestr(plugin_name + "/__init__.py", "raise RuntimeError('owned incomplete package fixture')\n")
            reported_success = installer.installFromZipFile(str(damaged))
            # Record the real QGIS installer gap, not a plugin rollback claim.
            assert reported_success and not utils.isPluginLoaded(plugin_name)
            assert not (plugin_dir / "gui" / "forms" / "main_dialog.ui").exists()
            observed = {"installer_reported_success": reported_success,
                        "incomplete_plugin_active": False, "old_files_rolled_back": False}
            assert installer.installFromZipFile(str(archive))
            assert utils.isPluginLoaded(plugin_name)
        assert utils.unloadPlugin(plugin_name)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert QgsProject.instance().mapLayer(layer_id) is memory and not actions
        result = {"status": "complete", "scenario": scenario,
            "settings_file": str(settings_file), "plugins_dir": str(plugins_dir), **observed}
        print("INSTALLER_SANDBOX_RESULT=" + json.dumps(result))
        QgsProject.instance().clear()
        app.exitQgis()
        return
    if scenario in {"busy_unload", "gc_busy_unload", "failed_tool"}:
        from qgis.PyQt.QtCore import QProcess
        tools_module = __import__(plugin_name + ".controllers.tools_controller", fromlist=["ToolsController"])

        class FixtureProcess(QProcess):
            def setArguments(self, arguments):
                request = arguments[arguments.index("--request") + 1]
                marker = arguments[arguments.index("--cancel-file") + 1]
                script = (
                    "import json,os,sys,time; from pathlib import Path; "
                    "r=json.load(open(sys.argv[1])); "
                    "print(json.dumps({'event':'progress','request_id':r['request_id'],"
                    "'percent':1,'message':'fixture child cwd:'+os.getcwd()}),flush=True); "
                )
                if scenario == "failed_tool":
                    script += (
                        "print(json.dumps({'event':'result','request_id':r['request_id'],"
                        "'status':'failed','message':'owned fixture failure'}),flush=True); sys.exit(1)"
                    )
                else:
                    script += (
                        "\ndeadline=time.monotonic()+30"
                        "\nwhile not Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.01)"
                        "\nwhile not (Path(sys.argv[2]).parent/'fixture_release').exists() and time.monotonic()<deadline: time.sleep(.01)"
                        "\nsys.exit(130)"
                    )
                assert arguments[:5] == ["-I", "-B", "-X", "utf8", "-c"]
                super().setArguments(["-I", "-B", "-X", "utf8", "-c", script, request, marker])

        tools_module.QProcess = FixtureProcess
        dialog = original.dlg
        progress, outcomes = [], []
        dialog.tools_controller.progress.connect(lambda value, message: progress.append(message))
        dialog.tools_controller.resultReady.connect(outcomes.append)
        assert dialog.tools_controller.start({"operation": "inspect", "schema_version": 1})
        try:
            wait_until(app, lambda: any(message.startswith("fixture child cwd:") for message in progress))
        except AssertionError as exc:
            raise AssertionError(f"Fixture child did not start: outcomes={outcomes}; stderr={dialog.tools_controller._stderr}") from exc
        if scenario in {"busy_unload", "gc_busy_unload"}:
            recorded = next(message.split(":", 1)[1] for message in progress if message.startswith("fixture child cwd:"))
            job = contained(Path(recorded).resolve())
            assert job.is_relative_to(root / "plugin-cache")
            assert not job.is_relative_to(plugin_dir)
            snapshot = job / "engine_source"
            manifest = json.loads((snapshot / ".engine_snapshot.json").read_text())
            assert Path(manifest["source_root"]) == plugin_dir
            frozen = {name: (snapshot / name).read_bytes() for name in manifest["files"]}
            assert all(hashlib.sha256(data).hexdigest() == manifest["files"][name]["sha256"]
                       for name, data in frozen.items())
            log = contained(root / "project" / "unload.log")
            dialog.logger.set_log_file(log)
            dialog.logger.info("owned unload logger marker")
            assert log.is_file()
            assert dialog.tools_controller.is_running
            assert owned_child_alive(dialog.tools_controller)
            plugin_ref = weakref.ref(original)
            retired = None
            if scenario == "gc_busy_unload":
                assert utils.unloadPlugin(plugin_name)
                assert plugin_name not in sys.modules
                # Real directory rename while the actual child still lives.
                # A Windows child cwd inside this directory would block it.
                retired = contained(root / "retired-plugin")
                plugin_dir.rename(retired)
                assert retired.is_dir() and not plugin_dir.exists()
            # The other case exercises direct in-place ZIP replacement, not
            # a manually pre-unloaded/renamed plugin installation.
            assert installer.installFromZipFile(str(archive))
            assert utils.isPluginLoaded(plugin_name)
            assert utils.plugins[plugin_name] is not original
            assert dialog.tools_controller.is_running
            assert owned_child_alive(dialog.tools_controller)
            assert dialog._dispose_pending
            assert snapshot.is_dir()
            assert all((snapshot / name).read_bytes() == data for name, data in frozen.items())
            original = None
            gc.collect()
            assert plugin_ref() is None
            (job / "fixture_release").touch()
            wait_until(app, lambda: not dialog.tools_controller.is_running)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            from qgis.PyQt import sip
            assert sip.isdeleted(dialog)
            assert not dialog.logger.logger.handlers
            assert not job.exists()
            closed_log = contained(root / "project" / "unload-closed.log")
            log.rename(closed_log)
            assert "owned unload logger marker" in closed_log.read_text()
            assert outcomes and not outcomes[-1]["success"]
            if retired:
                assert not installer_module.removeDir(str(retired))
            assert utils.unloadPlugin(plugin_name)
            result = {"status": "complete", "scenario": scenario,
                "settings_file": str(settings_file), "plugins_dir": str(plugins_dir),
                "child_cwd": recorded, "owned_child_reaped": True,
                "zip_replaced_while_child_alive": True, "frozen_source_unchanged": True,
                "plugin_collected": plugin_ref() is None, "dialog_deleted": True,
                "logger_handlers": 0, "log_rename_completed": True,
                "job_cache_removed_after_exit": True}
        else:
            wait_until(app, lambda: not dialog.tools_controller.is_running)
            assert outcomes and not outcomes[-1]["success"]
            assert "owned fixture failure" in outcomes[-1]["message"]
            assert utils.unloadPlugin(plugin_name)
            assert installer.installFromZipFile(str(archive))
            assert utils.isPluginLoaded(plugin_name)
            assert utils.unloadPlugin(plugin_name)
            result = {"status": "complete", "scenario": scenario,
                "settings_file": str(settings_file), "plugins_dir": str(plugins_dir),
                "failed_tool_update_completed": True}
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert QgsProject.instance().mapLayer(layer_id) is memory and not actions
        print("INSTALLER_SANDBOX_RESULT=" + json.dumps(result))
        QgsProject.instance().clear()
        app.exitQgis()
        return
    for _ in range(4):
        original.run()
        app.processEvents()
        original.dlg.reject()
        app.processEvents()
    assert installer.installFromZipFile(str(archive))
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert utils.isPluginLoaded(plugin_name)
    assert utils.plugins[plugin_name] is not original
    assert sys.modules[plugin_name] is not package
    assert QgsProject.instance().mapLayer(layer_id) is memory and memory.isValid()
    assert len(actions) == 1
    assert utils.unloadPlugin(plugin_name)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert plugin_name not in utils.plugins and not actions
    assert plugin_name not in utils._plugin_modules
    assert not installer_module.removeDir(str(plugin_dir))
    assert not plugin_dir.exists()
    assert installer.installFromZipFile(str(archive))
    assert utils.isPluginLoaded(plugin_name) and len(actions) == 1
    assert utils.unloadPlugin(plugin_name)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert QgsProject.instance().mapLayer(layer_id) is memory
    contained(QgsSettings().fileName())
    result = {"status": "complete", "scenario": "idle_update_reinstall",
        "settings_file": str(settings_file), "plugins_dir": str(plugins_dir),
        "close_reopen_cycles": 4, "messages": messages,
        "qgis": QgsApplication.qgisVersion() if hasattr(QgsApplication, "qgisVersion") else "native"}
    print("INSTALLER_SANDBOX_RESULT=" + json.dumps(result))
    QgsProject.instance().clear()
    app.exitQgis()


if __name__ == "__main__":
    main()
