"""Qt-free text/state helpers for the readiness row, engine view, task status and paths."""
import html

# key, label, hint shown while the item is missing
READINESS = (
    ("engine", "Engine", "Set up the analysis engine on the Engine tab."),
    ("project", "Project", "Create or open the selected project folder."),
    ("mastergrid", "Zone grid", "Choose a zone grid in Input data."),
    ("census_data", "Census", "Choose a population census in Input data."),
    ("covariates", "Covariates", "Add at least one covariate raster in Input data."),
)
SCOPE = "This only shows what is selected. Run still checks that the data and zone grid are compatible."


def readiness_states(engine, active, config):
    """Inputs of an inactive (mismatched or unopened) project are not counted."""
    config = config if active else {}
    return {"engine": bool(engine), "project": bool(active),
            "mastergrid": bool(config.get("mastergrid")),
            "census_data": bool(config.get("census_data")),
            "covariates": bool(config.get("covariates"))}


def readiness_tooltip(label, hint, ready):
    return f"{label}: {'ready' if ready else 'needed'}. " + ("" if ready else hint + " ") + SCOPE


def bounded_status(message, limit=1000, lines=3):
    """Short plain status text; complete messages remain in Details."""
    text = str(message).replace("\r\n", "\n").replace("\r", "\n").strip()
    parts = text.split("\n")
    if len(parts) <= lines and len(text) <= limit:
        return text
    suffix = " … See Details for the full message."
    return "\n".join(parts[:lines])[:max(0, limit - len(suffix))].rstrip() + suffix[:limit]


def short_path(path, limit=72):
    text = str(path)
    if len(text) <= limit:
        return text
    head = (limit - 1) // 3
    return text[:head] + "…" + text[-(limit - 1 - head):]


def plain_tooltip(text):
    """Qt guesses rich text in tooltips; escape so paths and IDs show literally."""
    return "<qt>" + html.escape(str(text), quote=False).replace("\n", "<br>") + "</qt>"


# Engine view states. They describe presentation only; RuntimeController.python
# remains the single authority for whether calculations may use an engine.
ENGINE_CHECKING = "checking"          # a check/discovery/inspection has not ended yet
ENGINE_NO_PYTHON = "no_python"        # a completed discovery found no compatible Python
ENGINE_UNDISCOVERED = "undiscovered"  # discovery did not complete; nothing is proven
ENGINE_SELECTED = "selected"          # compatible Python listed, engine not prepared
ENGINE_INSTALLING = "installing"      # setup/repair worker is running
ENGINE_READY = "ready"                # verified engine available
ENGINE_REPAIR_FAILED = "repair_failed"  # last repair/check failed, previous engine kept
ENGINE_FAILED = "failed"              # last setup/check failed and no engine is usable


def engine_view_state(operation, ready, has_choices, discovery_empty, failed):
    """Derive the single engine view state.

    ``operation`` is the running worker kind (``"setup"``, ``"check"``,
    ``"discover"``, ``"inspect"``) or ``None`` once it ended. A pending check is
    never reported as "no Python": only a completed, error-free discovery that
    listed nothing sets ``discovery_empty``.
    """
    if operation == "setup":
        return ENGINE_INSTALLING
    if operation:
        return ENGINE_CHECKING
    if ready:
        return ENGINE_REPAIR_FAILED if failed else ENGINE_READY
    if failed:
        return ENGINE_FAILED
    if has_choices:
        return ENGINE_SELECTED
    return ENGINE_NO_PYTHON if discovery_empty else ENGINE_UNDISCOVERED


def engine_next_step(state):
    """Next workflow destination after the engine, from the dialog's live home state."""
    state = state if isinstance(state, dict) else {}
    if state.get("project_ready") is not True:
        return "project", "Continue to Project"
    if state.get("inputs_ready") is not True:
        return "inputs", "Continue to Input data"
    return "review", "Review settings"


def run_action_role(text):
    """Visual role mirrored from the controller-owned run button text."""
    words = str(text).strip().casefold()
    if words.startswith("stopping"):
        return "stopping"
    if words.startswith(("stop", "cancel")):
        return "stop"
    return "run"


def interpreter_label(record, source_labels):
    """Readable combo entry for one verified interpreter record."""
    version = str(record.get("version") or "").strip()
    parts = ["Python " + version if version and version != "unknown" else "Python"]
    if record.get("bits"):
        parts.append(f"{record['bits']}-bit")
    source = record.get("source")
    if source:
        parts.append(source_labels.get(source, str(source)))
    if record.get("recommended"):
        parts.append("Recommended")
    parts.append(short_path(record.get("path", ""), 48))
    return " · ".join(parts)
