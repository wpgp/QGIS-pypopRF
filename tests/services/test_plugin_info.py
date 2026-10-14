"""Static plugin presentation metadata never needs QGIS or scientific imports."""
from pathlib import Path

import pytest

from services.plugin_info import load_plugin_info, safe_web_url


@pytest.fixture
def package(tmp_path):
    (tmp_path / "metadata.txt").write_text("""[general]
name=Test <b>brand</b>
version=9.2
description=Literal <img> description
author=Recorded author
    Recorded contributor
email=author@example.test
homepage=https://example.test/docs
repository=https://example.test/source
tracker=javascript:alert(1)
""", encoding="utf-8")
    (tmp_path / "README.md").write_text("""[DOI](https://doi.org/10.1234/example)
The repository contains [MIT LICENSE](LICENSE) and GPL notices.
Licensing remains a release gate.

## Citation
```bibtex
@software{test, author={Recorded person}, title={Recorded title}}
```

## Other
Do not use this as citation.
""", encoding="utf-8")
    return tmp_path


def test_info_is_source_backed_plain_and_does_not_resolve_licensing_conflict(package):
    info = load_plugin_info(package)
    assert info.name == "Test <b>brand</b>" and info.version == "9.2"
    assert "Recorded contributor" in info.author and info.email == "author@example.test"
    assert "MIT LICENSE" in info.license_notice and "GPL" in info.license_notice
    assert "release gate" in info.license_notice
    assert info.citation == "@software{test, author={Recorded person}, title={Recorded title}}"
    assert len(info.links) == 3
    assert not any("javascript" in link.url for link in info.links)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///tmp/private", "mailto:a@b.test",
    "https://user:secret@example.test", "https://example.test\n/script", "https://example.test/ space",
    "https://example.test:99999/", "https:///missing", "http://[broken", "//example.test", None])
def test_links_reject_non_web_credentials_controls_and_malformed_urls(url):
    assert safe_web_url(url) is None


@pytest.mark.parametrize("url", ["https://example.test/path?q=one#section", "http://example.test/", "HTTPS://example.test/"])
def test_packaged_http_links_are_returned_without_automatic_navigation(url):
    assert safe_web_url(url) == url


def test_missing_or_oversized_metadata_is_bounded_and_reports_diagnostics(tmp_path):
    (tmp_path / "metadata.txt").write_bytes(b"x" * (128 * 1024 + 1))
    info = load_plugin_info(tmp_path)
    assert info.version == "Unknown" and info.author == ""
    assert info.links == () and info.logo_path is None
    assert info.warnings and not info.citation


def test_metadata_interpolation_is_disabled_and_logo_uses_only_known_local_asset(package):
    metadata = package / "metadata.txt"
    metadata.write_text(metadata.read_text() + "about=100% unchanged\nicon=../../secret.png\n")
    (package / "icon.png").write_bytes(b"owned fixture, widget handles invalid image safely")
    info = load_plugin_info(package)
    assert info.about == "100% unchanged"
    assert info.logo_path == package / "icon.png"


def test_packaged_repository_identity_and_citation_are_not_fabricated():
    root = Path(__file__).resolve().parents[2]
    info = load_plugin_info(root)
    assert info.name == "pypopRF"
    assert "WorldPop SDI Team" in info.author
    assert "GPL" in info.license_notice and "MIT" in info.license_notice
    assert "@software{QGIS-pypopRF" in info.citation
    assert info.logo_path == root / "wp_logo.png"
