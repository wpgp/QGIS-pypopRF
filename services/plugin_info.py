"""Bounded, Qt-free presentation metadata from the installed plugin itself."""
from configparser import ConfigParser, Error as ConfigError
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PluginLink:
    label: str
    url: str


@dataclass(frozen=True)
class PluginInfo:
    name: str
    version: str
    description: str
    about: str
    author: str
    email: str
    license_notice: str
    citation: str
    links: tuple[PluginLink, ...]
    logo_path: Path | None
    warnings: tuple[str, ...] = ()


def safe_web_url(value):
    """Return a packaged explicit HTTP(S) destination, never mail/file/script."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    if any(ord(character) < 32 or character.isspace() for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return None
        parsed.port  # Reject malformed/out-of-range ports without navigating.
    except (ValueError, UnicodeError):
        return None
    return value


def _read(root, name, limit, warnings):
    path = root / name
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise ValueError("missing, linked or oversized")
        with path.open("rb") as source:
            data = source.read(limit + 1)
        if len(data) > limit:
            raise ValueError("oversized")
        return data.decode("utf-8-sig")
    except (OSError, UnicodeError, ValueError) as exc:
        warnings.append(f"Could not read packaged {name}: {exc}")
        return ""


def _plain_markdown(text):
    return re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text).replace("**", "").strip()


def load_plugin_info(plugin_root):
    """Read static identity only; readiness and installation state are not saved."""
    root = Path(plugin_root).resolve()
    warnings = []
    metadata = _read(root, "metadata.txt", 128 * 1024, warnings)
    readme = _read(root, "README.md", 512 * 1024, warnings)
    parser = ConfigParser(interpolation=None)
    try:
        parser.read_string(metadata)
    except ConfigError as exc:
        warnings.append(f"Could not parse packaged metadata: {exc}")
        parser = ConfigParser(interpolation=None)

    def field(name, default="", limit=4096):
        return parser.get("general", name, fallback=default).strip()[:limit]

    links = []
    for key, label in (("homepage", "Documentation"), ("repository", "Source repository"),
                       ("tracker", "Report an issue")):
        url = safe_web_url(field(key))
        if url:
            links.append(PluginLink(label, url))
    doi = re.search(r"\]\((https://doi\.org/[^\s\)]+)\)", readme)
    if doi and safe_web_url(doi.group(1)):
        links.append(PluginLink("Citation DOI from README", doi.group(1)))
    worldpop = re.search(r"\[WorldPop SDI\]\(([^\s\)]+)\)", readme)
    if worldpop and safe_web_url(worldpop.group(1)):
        links.append(PluginLink("WorldPop SDI", worldpop.group(1)))
    citation_section = re.search(r"(?ms)^## Citation\s*\n(.*?)(?=^## |\Z)", readme)
    citation = ""
    if citation_section:
        block = re.search(r"(?s)```bibtex\s*\n(.*?)```", citation_section.group(1))
        if block:
            citation = block.group(1).strip()[:8192]
    licensing = re.search(r"(?s)(The repository contains.*?)(?:\n\s*\n|\Z)", readme)
    license_notice = _plain_markdown(licensing.group(1))[:4096] if licensing else ""
    if not license_notice:
        license_text = _read(root, "LICENSE", 128 * 1024, warnings)
        license_notice = ("Packaged LICENSE heading: " + license_text.splitlines()[0].strip() +
            ". Additional licensing/provenance information is unavailable; consult the package files."
            if license_text else "Licensing information is unavailable in this package.")
    logo = None
    for name in ("wp_logo.png", "icon.png"):
        path = root / name
        try:
            if not path.is_symlink() and path.is_file() and path.stat().st_size <= 2 * 1024 * 1024:
                logo = path
                break
        except OSError:
            pass
    return PluginInfo(field("name", "pypopRF", 120), field("version", "Unknown", 80),
        field("description", limit=1024), field("about"), field("author"), field("email", limit=512),
        license_notice, citation, tuple(links), logo, tuple(warnings))
