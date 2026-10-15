"""Validate release identity without tagging, uploading or modifying files."""

import configparser
from datetime import date
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def check_release(root=ROOT, ref=""):
    root = Path(root)
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(root / "metadata.txt", encoding="utf-8")
    general = metadata["general"]
    version = general["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Expected a three-component release version")
    # metadata.txt is also the numerical engine's canonical version source.
    headings = re.findall(r"^## \[([^\]]+)\] - (.+)$",
                          (root / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    if not headings or headings[0][0] != version:
        raise ValueError("First changelog entry must match plugin version")
    experimental = general.getboolean("experimental")
    if not experimental:
        date.fromisoformat(headings[0][1])
        if "development build" in general["about"].casefold():
            raise ValueError("Stable metadata still describes a development build")
    if ref.startswith("refs/tags/"):
        if ref != f"refs/tags/v{version}":
            raise ValueError("Release tag must match plugin version")
        if experimental:
            raise ValueError("Release tag cannot identify experimental metadata")
    return version


if __name__ == "__main__":
    print(f"Release metadata OK: {check_release(ref=os.environ.get('GITHUB_REF', ''))}")
