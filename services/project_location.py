"""Read-only project-location safety against plugin updates and cache cleanup."""
from pathlib import Path
import stat


class ProjectLocationError(ValueError):
    """User data must not live inside a mutable plugin/cache directory."""


def _canonical(value):
    if value is None or not str(value).strip():
        raise ProjectLocationError("Choose an external project directory first")
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ProjectLocationError("Could not verify the project location. Choose an accessible external folder.") from exc


def ensure_project_location(path, *, plugin_root=None, job_cache=None, runtime_cache=None):
    """Return a canonical safe project path, without reading/writing user files.

    Existing aliases/junctions are resolved before containment comparisons.
    Only equality/descendants are refused: a project that is a safe ancestor of
    a protected folder is not itself refused. This is a path check, not a
    hostile-filesystem sandbox or validation of every configured output path.
    """
    project = _canonical(path)
    protected = []
    if plugin_root is not None:
        protected.append(("installed plugin folder", _canonical(plugin_root)))
    if job_cache is not None:
        # Preserve the configured cache namespace and redirected jobs directory
        # itself. Do not protect an unrelated parent of a leaf jobs junction:
        # that would incorrectly refuse safe sibling/ancestor projects.
        protected.append(("temporary job cache", _canonical(Path(job_cache).parent)))
        protected.append(("temporary job cache", _canonical(job_cache)))
    if runtime_cache is not None:
        protected.append(("analysis engine cache", _canonical(runtime_cache)))
    for label, root in protected:
        if project == root or project.is_relative_to(root):
            raise ProjectLocationError(
                f"Project location is inside the {label}: {root}. "
                "This folder can be removed during update or cache cleanup. "
                "Back up and move any existing project to an external folder, then open it there. "
                "No project files were moved or deleted."
            )
    return project


def ensure_project_paths(path, config, **protected):
    """Check root and configured data/output directories before GUI writes.

    Callers supply validated saved config or the defaults for a new project;
    analysis callers recheck their current config immediately before spawning.
    Other individual inputs/outputs are not a hostile-filesystem sandbox.
    """
    project = ensure_project_location(path, **protected)
    for field, default in (("data_dir", "data"), ("output_dir", "output")):
        value = config.get(field, default)
        if not isinstance(value, str) or not value.strip():
            raise ProjectLocationError(f"Configured {field} must be a nonempty directory path")
        try:
            ensure_project_location(project / value, **protected)
        except ProjectLocationError as exc:
            raise ProjectLocationError(f"Configured {field} is unsafe. {exc}") from exc
    logging = config.get("logging", {})
    if not isinstance(logging, dict):
        raise ProjectLocationError("Project logging settings must be a mapping")
    ensure_gui_log_location(project, logging.get("file", "logs_pypoprf.log"), **protected)
    return project


def ensure_gui_log_location(project, filename, **protected):
    """Validate the actual fixed GUI log target without opening/changing it.

    Logging uses project/output, independently of analysis output_dir. A log
    must be a dedicated ordinary file: leaf links, multiple hardlinks and device/
    directory targets are refused. Safe parent-folder aliases remain supported.
    This rejects static aliases, not hostile concurrent filesystem replacement.
    """
    if (not isinstance(filename, str) or not filename.strip() or filename != filename.strip()
            or any(char in filename for char in '/\\:<>"|?*')
            or any(ord(char) < 32 for char in filename) or Path(filename).suffix.lower() != ".log"):
        raise ProjectLocationError("GUI log filename must be a plain portable basename ending in .log")
    device = filename.split(".", 1)[0].upper()
    if device in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ProjectLocationError("GUI log filename cannot be a reserved device name")
    root = ensure_project_location(project, **protected)
    try:
        directory = ensure_project_location(root / "output", **protected)
    except ProjectLocationError as exc:
        raise ProjectLocationError(f"GUI log directory is unsafe. {exc}") from exc
    target = directory / filename
    if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
        raise ProjectLocationError("GUI log file must be a dedicated ordinary file, not a symlink/junction. Choose a new log filename.")
    try:
        target = ensure_project_location(target, **protected)
    except ProjectLocationError as exc:
        raise ProjectLocationError(f"GUI log file is unsafe. {exc}") from exc
    try:
        current = target.stat()
    except FileNotFoundError:
        return target
    if not stat.S_ISREG(current.st_mode) or current.st_nlink > 1:
        raise ProjectLocationError("GUI log file must be a dedicated ordinary file, not a hardlink, directory or device. Choose a new log filename.")
    return target
