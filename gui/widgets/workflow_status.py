"""Qt-free text helpers for the readiness row, task status and path display."""
import html

# key, label, hint shown while the item is missing
READINESS = (
    ("engine", "Engine", "Set up the analysis engine on the Project tab."),
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
