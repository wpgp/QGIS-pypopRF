import shutil

import pytest

from scripts.check_release import ROOT, check_release


@pytest.fixture
def source(tmp_path):
    for name in ("metadata.txt", "CHANGELOG.md"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def replace(root, name, old, new):
    path = root / name
    contents = path.read_text(encoding="utf-8")
    assert old in contents
    path.write_text(contents.replace(old, new), encoding="utf-8")


def test_current_release_and_matching_tag():
    version = check_release()
    assert check_release(ref=f"refs/tags/v{version}") == version
    assert check_release(ref="refs/heads/master") == version


def test_rejects_mismatched_tag():
    with pytest.raises(ValueError, match="tag must match"):
        check_release(ref="refs/tags/v999.0.0")


def test_rejects_malformed_version(source):
    version = check_release(source)
    replace(source, "metadata.txt", f"version={version}", "version=broken")
    with pytest.raises(ValueError, match="three-component"):
        check_release(source)


def test_rejects_changelog_version_mismatch(source):
    version = check_release(source)
    replace(source, "CHANGELOG.md", f"## [{version}]", "## [999.0.0]")
    with pytest.raises(ValueError, match="changelog entry"):
        check_release(source)


def test_rejects_undated_stable_entry(source):
    replace(source, "CHANGELOG.md", "2026-10-15", "Unreleased")
    with pytest.raises(ValueError):
        check_release(source)


def test_rejects_stale_development_description(source):
    replace(source, "metadata.txt", "about=", "about=This is a development build. ")
    with pytest.raises(ValueError, match="development build"):
        check_release(source)


def test_experimental_checkout_allowed_but_release_tag_rejected(source):
    version = check_release(source)
    replace(source, "metadata.txt", "experimental=False", "experimental=True")
    replace(source, "CHANGELOG.md", "2026-10-15", "Unreleased")
    assert check_release(source) == version
    with pytest.raises(ValueError, match="experimental"):
        check_release(source, ref=f"refs/tags/v{version}")
