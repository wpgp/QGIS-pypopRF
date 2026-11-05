"""JSON-request tools entrypoint, run only in the isolated numerical engine."""
import argparse
import json
from pathlib import Path
import re
import sys
from uuid import uuid4
import os

# Cap native pools before importing any numerical/geospatial code, as the main
# analysis entrypoint does. Never execute this module inside the QGIS host.
if __package__ == "core.pypoprf":
    from shared.runtime_environment import NATIVE_THREAD_LIMITS
else:
    from ...shared.runtime_environment import NATIVE_THREAD_LIMITS
if __name__ == "__main__":
    os.environ.update(NATIVE_THREAD_LIMITS)

from .utils.runtime import CancellationToken, CancelledError  # noqa: E402


class FileCancellationToken(CancellationToken):
    def __init__(self, marker=None):
        super().__init__()
        self.marker = Path(marker) if marker else None

    def check(self):
        if self.marker is not None and self.marker.is_file():
            self.cancel()
        super().check()


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=True, allow_nan=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect, prepare or summarize population in the isolated engine")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--cancel-file", type=Path)
    options = parser.parse_args(argv)
    token = FileCancellationToken(options.cancel_file)
    request_id = None
    output = None
    try:
        if options.request.stat().st_size > 1024 * 1024:
            raise ValueError("Request exceeds the 1 MiB limit")
        def invalid_constant(value):
            raise ValueError(f"Nonfinite JSON constant: {value}")
        with options.request.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Request exceeds the 1 MiB limit")
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate JSON request field: {key}")
                result[key] = value
            return result
        request = json.loads(raw, parse_constant=invalid_constant, object_pairs_hook=unique_object)
        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object")
        request_id = request.setdefault("request_id", uuid4().hex)
        if not isinstance(request_id, str) or re.fullmatch(r"[0-9a-f]{32}", request_id) is None:
            raise ValueError("request_id must be a lowercase UUID hex ownership nonce")
        output = request.get("output_dir")
        token.check()
        operation = request.get("operation")
        callback = lambda percent, message: emit("progress", request_id=request_id, percent=percent, message=message)
        if operation in {"inspect", "prepare"}:
            from .preparation import prepare_or_inspect
            path = prepare_or_inspect(request, token, callback)
        elif operation == "population_summary":
            from .population_summary import summarize_population
            path = summarize_population(request, token, callback)
        else:
            raise ValueError("Unknown operation; only inspect, prepare and population_summary are supported")
        report = json.loads(path.read_text(encoding="utf-8"))
        emit("result", status="complete", request_id=request_id, output_dir=str(path.parent),
             report_path=str(path), config_path=report.get("config_path"), message="Tool operation completed")
        return 0
    except CancelledError as exc:
        emit("result", status="cancelled", request_id=request_id, output_dir=output,
             report_path=None, config_path=None, message=str(exc)[:4000])
        return 2
    except Exception as exc:
        emit("result", status="failed", request_id=request_id, output_dir=output,
             report_path=None, config_path=None, message=str(exc)[:4000])
        return 1


if __name__ == "__main__":
    sys.exit(main())
