"""Fail closed on Bandit findings and NEW secrets in the actual plugin ZIP.

QGIS currently invokes detect-secrets scan --baseline, which updates the file
instead of printing findings. Never rely on that stdout-based server check:
scan independently without a baseline, then compare exact reviewed fingerprints.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_plugin import SECRETS_BASELINE, verify_package


def run_json(command, directory, accepted_codes=(0,)):
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True,
                            encoding="utf-8", timeout=120, shell=False)
    if result.returncode not in accepted_codes or not result.stdout.strip():
        raise RuntimeError(f"Scanner failed or produced no JSON: {command[2]}")
    return json.loads(result.stdout)


def scan_secrets(directory, baseline):
    # Keep every detector enabled. No baseline, no file-wide checksum exclusions,
    # and no network verification of potential credentials. A single worker also
    # avoids spawning one process per CPU on high-core-count Windows machines.
    report = run_json([sys.executable, "-m", "detect_secrets", "-c", "1", "scan",
        "--all-files", "--no-verify", "--exclude-files", r"(^|[\\/])\.secrets\.baseline$", "."], directory)
    accepted = {(name, item["type"], item["hashed_secret"])
                for name, items in baseline["results"].items() for item in items}
    findings, known = [], 0
    for filename, items in report["results"].items():
        filename = filename.replace("\\", "/")
        for item in items:
            if (filename, item["type"], item["hashed_secret"]) in accepted:
                known += 1
            else:
                findings.append({"file": filename, "line": item.get("line_number"),
                                 "type": item["type"]})
    return {"new_findings": findings, "reviewed_checksum_findings": known,
            "detectors_enabled": len(report["plugins_used"])}


def scan_bandit(directory):
    report = run_json([sys.executable, "-m", "bandit", "-r", str(directory),
                       "-f", "json", "--quiet"], directory, accepted_codes=(0, 1))
    if report.get("errors"):
        raise RuntimeError("Bandit could not parse every packaged Python file")
    return [{"file": str(Path(item["filename"]).relative_to(directory)),
             "line": item["line_number"], "rule": item["test_id"],
             "severity": item["issue_severity"]} for item in report["results"]]


def check_catalog(archive):
    manifest = verify_package(archive)
    import zipfile
    with tempfile.TemporaryDirectory(prefix="pypoprf-catalog-") as temporary:
        directory = Path(temporary).resolve()
        with zipfile.ZipFile(archive) as package:
            package.extractall(directory)  # Validated portable members, no links.
        baseline_path = directory / "pypopRF" / SECRETS_BASELINE
        if not baseline_path.is_file():
            raise ValueError("Catalog submission requires a generated reviewed-checksum baseline")
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        report = {"version": manifest["version"], "bandit": scan_bandit(directory),
                  "secrets": scan_secrets(directory, baseline)}
    report["passed"] = not report["bandit"] and not report["secrets"]["new_findings"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = check_catalog(args.archive.resolve())
    output = json.dumps(report, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
