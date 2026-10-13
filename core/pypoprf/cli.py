"""JSON-event CLI for running the numerical engine outside the QGIS process."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import sys
import traceback
from uuid import uuid4

import yaml
import rasterio
from threadpoolctl import threadpool_info

from . import __version__
from .config.settings import Settings
from .pipeline import execute_analysis
from .utils.logger import get_logger
from .utils.runtime import atomic_output, CancellationToken, CancelledError


class FileCancellationToken(CancellationToken):
    """An adapter can cancel a child engine by creating its run-local marker."""

    def __init__(self, marker=None):
        super().__init__()
        self.marker = Path(marker) if marker else None

    def check(self):
        if self.marker is not None and self.marker.is_file():
            self.cancel()
        super().check()


def fingerprint(path, token):
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            token.check()
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Input changed while fingerprinting: {path}")
    return {"path": str(path.resolve()), "bytes": after.st_size,
            "mtime_ns": after.st_mtime_ns, "sha256": digest.hexdigest()}


def emit(kind, **values):
    # ASCII JSON is valid UTF-8 and survives Windows legacy pipe encodings.
    print(json.dumps({"event": kind, **values}, ensure_ascii=True, allow_nan=False), flush=True)


def input_resources(settings, token):
    """Include GDAL mask/metadata resources, not only the TIFF payload."""
    rasters = {settings.mastergrid, *settings.covariate.values()}
    rasters.update(path for path in (settings.mask, settings.constrain) if path)
    paths = {Path(settings.census["path"]).resolve()}
    if settings.agesex_data:
        paths.add(Path(settings.agesex_data).resolve())
    for source in sorted(rasters):
        token.check()
        with rasterio.open(source) as dataset:
            paths.update(Path(path).resolve() for path in dataset.files)
        paths.add(Path(source).resolve())
    if any(not path.is_file() for path in paths):
        raise ValueError("All input dataset resources must be regular local files")
    return sorted(paths)


def artifact_inventory(output, token):
    """Describe immutable run products separately from displayable raster outputs."""
    records = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "manifest.json" or ".log" in path.suffixes:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(output.resolve()):
            raise ValueError(f"Run artifact escapes its directory: {path}")
        record = fingerprint(path, token)
        record["path"] = path.relative_to(output).as_posix()
        records.append(record)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run pypopRF in an isolated Python engine")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cancel-file", type=Path)
    options = parser.parse_args(argv)
    token = FileCancellationToken(options.cancel_file)
    output = None
    owned = False
    manifest = {"schema_version": 1, "status": "failed", "outputs": [], "inputs": []}
    logger = get_logger()

    def save_manifest():
        if owned:
            # Terminal status must be written even when the token is cancelled.
            with atomic_output(output / "manifest.json") as path:
                path.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")

    def save_terminal_manifest():
        try:
            save_manifest()
        except Exception as exc:
            manifest.update(status="failed", message=f"Run finalization failed: {exc}")
            traceback.print_exc(file=sys.stderr)
            return False
        return True

    try:
        token.check()
        settings = Settings.from_file(options.config)
        settings.cancellation_token = token
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        output = options.output_dir.resolve() if options.output_dir else settings.output_dir / "runs" / run_id
        output.mkdir(parents=True, exist_ok=False)
        owned = True
        settings.output_dir = output
        manifest.update(status="running", run_id=output.name, config=str(options.config.resolve()),
                        engine_version=__version__)
        manifest["runtime"] = {
            "python": sys.version, "implementation": platform.python_implementation(),
            "platform": platform.platform(), "machine": platform.machine(),
            "distributions": dict(sorted((dist.metadata["Name"], dist.version)
                                         for dist in metadata.distributions())),
            "rasterio_gdal": rasterio.__gdal_version__,
            "rasterio_proj": getattr(rasterio, "__proj_version__", None),
            "native_threadpools": threadpool_info(),
        }
        module_root = Path(__file__).resolve().parent
        lock = module_root.parents[1] / "requirements-engine.lock"
        manifest["packaged_dependency_lock_sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
        manifest["engine_adapter_source_sha256"] = {
            name: hashlib.sha256((module_root.parents[1] / name).read_bytes()).hexdigest()
            for name in ("services/runtime_manager.py", "services/owned_process.py",
                         "shared/atomic_files.py", "shared/runtime_environment.py")
        }
        manifest["engine_source_sha256"] = {
            path.relative_to(module_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(module_root.rglob("*.py"))
            if "__pycache__" not in path.parts
        }
        snapshot = settings.to_config()
        with atomic_output(output / "run_config.yaml") as path:
            path.write_text(yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8")
        manifest["config_snapshot"] = "run_config.yaml"
        save_manifest()
        logger.set_level(settings.logging["level"])
        if settings.logging["file"]:
            logger.set_log_file(str(output / Path(settings.logging["file"]).name))
        paths = input_resources(settings, token)
        manifest["inputs"] = [fingerprint(path, token) for path in paths]
        result = execute_analysis(settings, lambda percent, message: emit("progress", percent=percent, message=message))
        token.check()
        # Detect upstream changes rather than stamping a run with mixed input versions.
        if input_resources(settings, token) != paths:
            raise ValueError("Input dataset resources changed during analysis")
        for source in manifest["inputs"]:
            if fingerprint(source["path"], token) != source:
                raise ValueError(f"Input changed during analysis: {source['path']}")
        outputs = [result["prediction"], *result["population"].values(), *result["agesex"].values()]
        manifest.update(
            status="complete", outputs=[str(Path(path).relative_to(output)) for path in outputs],
            cv_metrics=result["cv_metrics"], diagnostics=result["diagnostics"],
            elapsed_seconds=result["elapsed_seconds"],
            artifacts=artifact_inventory(output, token),
        )
        save_manifest()
        emit("result", status="complete", message="Analysis completed and census totals verified",
             run_dir=str(output), outputs=manifest["outputs"])
        return 0
    except CancelledError as exc:
        manifest.update(status="cancelled", message=str(exc))
        recorded = save_terminal_manifest()
        emit("result", status=manifest["status"], message=manifest["message"],
             run_dir=str(output) if owned else None)
        return 2 if recorded else 1
    except Exception as exc:
        manifest.update(status="failed", message=str(exc))
        save_terminal_manifest()
        traceback.print_exc(file=sys.stderr)
        emit("result", status="failed", message=manifest["message"], run_dir=str(output) if owned else None)
        return 1
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
