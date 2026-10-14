import platform
import os
import shutil
import tempfile
import hashlib
import csv
import re
import stat
from logging import Logger
from pathlib import Path
from typing import Optional


class FileHandlerError(Exception):
    """Custom exception for file handling operations."""

    pass


class FileHandler:
    """Handler for file operations in QGIS plugin.

    Manages file operations including copying, validation, and system interactions.

    Attributes:
        working_dir: Current working directory path
        logger: Logger instance for output messages
    """

    def __init__(self, working_dir: str, logger: Logger) -> None:
        """Initialize FileHandler.

        Args:
            working_dir: Working directory path
            logger: Logger instance

        Raises:
            FileHandlerError: If initialization fails
        """
        self.working_dir = working_dir
        self.data_dir = "data"
        self.logger = logger
        self._validate_logger()

    def _validate_logger(self) -> None:
        """Validate logger instance has required methods."""
        required_methods = ["info", "error", "debug", "warning"]
        missing_methods = [
            method for method in required_methods if not hasattr(self.logger, method)
        ]
        if missing_methods:
            raise FileHandlerError(
                f"Logger missing required methods: {', '.join(missing_methods)}"
            )

    def set_working_dir(self, working_dir: str, data_dir: str = "data") -> None:
        """Set working directory.

        Args:
            working_dir: New working directory path

        Raises:
            FileHandlerError: If path is invalid
        """
        try:
            path = Path(working_dir)
            if not path.exists():
                path.mkdir(parents=True)
            self.working_dir = str(path)
            self.data_dir = data_dir
        except Exception as e:
            raise FileHandlerError(f"Failed to set working directory: {str(e)}")

    def copy_to_data_dir(self, source_path: str, file_type: str, cancellation_token=None,
                         progress=None, *, destination_name=None, conflict=None,
                         action=None, id_column="id") -> Optional[str]:
        """Copy file to project's data directory.

        Args:
            source_path: Original file path
            file_type: Type of file (mastergrid, mask, covariate, etc.)

        Returns:
            Optional[str]: Filename of copied file or None if failed

        Raises:
            FileHandlerError: If copy operation fails
        """
        try:
            source_file = Path(source_path)
            self._ordinary(source_file)
            if not source_file.is_file():
                self.logger.error(f"Source file not found: {source_path}")
                raise FileNotFoundError(f"Source file not found: {source_path}")

            data_dir = Path(self.working_dir) / self.data_dir
            data_dir.mkdir(parents=True, exist_ok=True)

            name = destination_name or source_file.name
            self.validate_basename(name, source_file.suffix)
            dest_file = data_dir / name
            self.validate_role(source_file, file_type, id_column)
            if conflict is not None:
                self._verify_resolution(source_file, dest_file, conflict, action,
                                        cancellation_token, progress)
                if action == "reuse":
                    return dest_file.name
            # Check if destination exists
            # GDAL resolves sidecars beside the selected pathname, not by inode.
            # An outside hardlink/symlink can therefore have a different mask.
            if (dest_file.exists() and source_file.samefile(dest_file)
                    and source_file.parent.resolve() == dest_file.parent.resolve()):
                return source_file.name
            if dest_file.exists() or dest_file.is_symlink():
                raise FileExistsError(f"Import would overwrite an existing input: {dest_file}")

            sidecars = self._sidecars(source_file)
            self._reject_sidecars(sidecars + self._sidecars(dest_file))
            source_info = (conflict["source_info"] if conflict is not None else
                           self._fingerprint(source_file, cancellation_token, progress))
            self._reject_sidecars(sidecars + self._sidecars(dest_file))

            descriptor, pending_name = tempfile.mkstemp(prefix=".import-", suffix=".tmp", dir=data_dir)
            os.close(descriptor)
            pending = Path(pending_name)
            try:
                original_metadata = source_file.stat()
                if self._identity(original_metadata) != source_info["identity"]:
                    raise FileHandlerError("Source changed before copy; select it again")
                if cancellation_token is None and progress is None:
                    shutil.copy2(source_path, str(pending))
                else:
                    total, copied = source_file.stat().st_size, 0
                    with source_file.open("rb") as source, pending.open("wb") as target:
                        while chunk := source.read(1024 * 1024):
                            if cancellation_token:
                                cancellation_token.check()
                            target.write(chunk)
                            copied += len(chunk)
                            if progress:
                                progress(int(100 * copied / max(total, 1)), source_file.name)
                        target.flush()
                        os.fsync(target.fileno())
                    shutil.copystat(source_file, pending)
                    if cancellation_token:
                        cancellation_token.check()
                current_metadata = source_file.stat()
                if self._identity(original_metadata) != self._identity(current_metadata):
                    raise FileHandlerError("Source changed during import; retry after it finishes updating")
                # A writer can create a GDAL mask/metadata file without changing
                # the TIFF's size or timestamp while our staged copy is running.
                # Stat identity is insufficient on Windows when a producer
                # preserves size/mtime. Verify all imports, not only collision
                # decisions, against both the actual staged bytes and source.
                if (self._fingerprint(pending, cancellation_token)["sha256"] != source_info["sha256"]
                        or self._fingerprint(source_file, cancellation_token, progress) != source_info):
                    raise FileHandlerError("Source changed during copy; select it again")
                self._ordinary(source_file)
                self._reject_sidecars(sidecars + self._sidecars(dest_file))
                if cancellation_token:
                    cancellation_token.check()
                # Publishing a hard link is atomic and refuses concurrent collisions.
                # Windows rename also refuses an existing destination on filesystems
                # that do not support hard links.
                try:
                    os.link(pending, dest_file)
                except FileExistsError:
                    raise
                except OSError:
                    if platform.system() != "Windows":
                        raise
                    os.rename(pending, dest_file)
            finally:
                pending.unlink(missing_ok=True)

            self.logger.info(f"Copied {file_type} file to data directory: {source_file.name}")
            return dest_file.name

        except Exception as e:
            self.logger.error(f"Failed to copy file: {str(e)}")
            raise FileHandlerError(f"Failed to copy file: {str(e)}")

    @staticmethod
    def validate_basename(name, suffix=None):
        if (not isinstance(name, str) or not name or name != name.strip()
                or name in {".", ".."} or name.endswith((".", " "))
                or any(c in name for c in '/\\:<>"|?*') or any(ord(c) < 32 for c in name)
                or len(name) > 240):
            raise FileHandlerError("Choose a plain portable filename, without folders or special characters")
        device = name.split(".", 1)[0].upper()
        if device in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise FileHandlerError("Reserved device names cannot be imported")
        if suffix is not None and Path(name).suffix.lower() != suffix.lower():
            raise FileHandlerError("Keep the original file extension")
        return name

    @staticmethod
    def _ordinary(path):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise FileHandlerError("Input file aliases are not supported; select a dedicated ordinary file")
        if not stat.S_ISREG(path.stat().st_mode):
            raise FileHandlerError("Select a regular input file")

    @staticmethod
    def _identity(metadata):
        # Python 3.12 Windows stat/fstat expose different legacy st_ctime values
        # after writes. Creation time is the stable extra identity there; bytes
        # are independently rehashed and size/mtime/inode are always checked.
        extra = getattr(metadata, "st_birthtime_ns", 0) if os.name == "nt" else metadata.st_ctime_ns
        return [metadata.st_dev, metadata.st_ino, metadata.st_size,
                metadata.st_mtime_ns, extra]

    @staticmethod
    def _sidecars(path):
        if path.suffix.lower() not in {".tif", ".tiff"}:
            return []
        return ([Path(str(path) + suffix) for suffix in (".msk", ".aux.xml")]
                + [path.with_suffix(suffix) for suffix in (".tfw", ".tifw", ".wld", ".prj")])

    @staticmethod
    def validate_role(path, kind, id_column="id"):
        """Bounded CSV header check, not a substitute for numerical preflight."""
        if kind not in {"census_data", "agesex_data"}:
            return []
        if path.suffix.lower() != ".csv":
            raise FileHandlerError("Choose a CSV table for this input role")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            line = stream.readline(65537)
        if len(line) > 65536:
            raise FileHandlerError("CSV header exceeds the supported preview limit")
        headers = next(csv.reader([line]), [])
        if not headers or any(not header for header in headers) or len(set(headers)) != len(headers):
            raise FileHandlerError("CSV needs nonempty unique headers; choose column mapping in Settings before running")
        if kind == "agesex_data" and not any(re.fullmatch(r"[fm](?:_)?\d+(?:[_-]\d+|\+)?", column, re.I) for column in headers):
            raise FileHandlerError("Age-sex CSV needs supported count columns such as f0, m0, f_0_4 or m_65+. A regular population table is not an age-sex table.")
        return headers

    def _fingerprint(self, path, token=None, progress=None):
        self._ordinary(path)
        before = self._identity(path.stat())
        digest, total = hashlib.sha256(), 0
        with path.open("rb") as stream:
            if self._identity(os.fstat(stream.fileno())) != before:
                raise FileHandlerError("Input changed before verification; try again")
            while chunk := stream.read(1024 * 1024):
                if token:
                    token.check()
                digest.update(chunk)
                total += len(chunk)
                if progress:
                    progress(int(100 * total / max(before[2], 1)), path.name)
            if self._identity(os.fstat(stream.fileno())) != before:
                raise FileHandlerError("Input changed during verification; try again")
        self._ordinary(path)
        if self._identity(path.stat()) != before:
            raise FileHandlerError("Input changed during verification; try again")
        if token:
            token.check()
        return {"identity": before, "sha256": digest.hexdigest()}

    def inspect_conflict(self, source_path, kind, cancellation_token=None, progress=None,
                         id_column="id"):
        """Run in a worker; SHA comparisons never run in the GUI thread."""
        source = Path(source_path)
        self._ordinary(source)
        self.validate_basename(source.name, source.suffix)
        headers = self.validate_role(source, kind, id_column)
        target = Path(self.working_dir) / self.data_dir / source.name
        if not target.exists() and not target.is_symlink():
            return None
        self._ordinary(target)
        if target.stat().st_nlink > 1:
            raise FileHandlerError("Existing input is a hardlink; select a dedicated project file")
        if source.samefile(target) and source.parent.resolve() == target.parent.resolve():
            return None  # Canonical selection keeps its own GDAL sidecar namespace.
        source_info = self._fingerprint(source, cancellation_token, progress)
        target_info = self._fingerprint(target, cancellation_token, progress)
        compatible = not any(p.exists() or p.is_symlink() for p in self._sidecars(source) + self._sidecars(target))
        return {"kind": kind, "filename": source.name, "source": str(source.absolute()),
                "destination": str(target.absolute()), "source_info": source_info,
                "destination_info": target_info, "identical": source_info["sha256"] == target_info["sha256"],
                "reuse_allowed": compatible and source_info["sha256"] == target_info["sha256"],
                "sidecar_compatible": compatible, "headers": headers[:100], "id_column": id_column}

    def _verify_resolution(self, source, target, conflict, action, token, progress):
        if action not in {"reuse", "copy"}:
            raise FileHandlerError("Choose reuse, a separate copy, or cancel")
        original = Path(self.working_dir) / self.data_dir / conflict["filename"]
        if (str(source.absolute()) != conflict["source"]
                or str(original.absolute()) != conflict["destination"]):
            raise FileHandlerError("Import context changed; select the input again")
        if self._fingerprint(source, token, progress) != conflict["source_info"]:
            raise FileHandlerError("Source changed since the conflict; select it again")
        if self._fingerprint(original, token, progress) != conflict["destination_info"]:
            raise FileHandlerError("Existing input changed since the conflict; select it again")
        # Same-size writes can share a filesystem timestamp tick. Rehash the
        # source after destination verification, rather than trusting stat alone.
        if self._fingerprint(source, token, progress) != conflict["source_info"]:
            raise FileHandlerError("Source changed during verification; select it again")
        if action == "reuse":
            if target != original or not conflict["reuse_allowed"]:
                raise FileHandlerError("Reuse is available only for verified identical compatible files")
            self._reject_sidecars(self._sidecars(source) + self._sidecars(original))
            # Source can change while the destination is being hashed.
            for path, info in ((source, conflict["source_info"]), (original, conflict["destination_info"])):
                self._ordinary(path)
                if self._identity(path.stat()) != info["identity"] or path.stat().st_nlink > 1:
                    raise FileHandlerError("Input changed since verification; select it again")
        elif target == original:
            raise FileHandlerError("Choose a different filename for the separate copy")

    @staticmethod
    def _reject_sidecars(paths):
        present = [path.name for path in paths if path.exists() or path.is_symlink()]
        if present:
            raise FileHandlerError(
                "This raster depends on external mask or metadata files: " + ", ".join(present)
                + ". Export a GeoTIFF with internal masks and georeferencing before importing.")

    def validate_inputs(
        self,
        mastergrid_path: str,
        census_path: str,
        covariate_count: int,
        mask_path: Optional[str] = None,
        constrain_path: Optional[str] = None,
        agesex_path: Optional[str] = None,
    ) -> bool:
        """Validate required input files.

        Args:
            agesex_path: Path to agesex cencus file
            constrain_path: Path to constrain file
            mask_path: Path to watermask file
            mastergrid_path: Path to mastergrid file
            census_path: Path to census file
            covariate_count: Number of covariates

        Returns:
            bool: True if all required inputs are valid

        Raises:
            FileHandlerError: If validation fails
        """
        try:
            validation_errors = []

            if not mastergrid_path:
                validation_errors.append("Mastergrid file is required")
            elif not Path(mastergrid_path).exists():
                validation_errors.append(f"Mastergrid file not found: {mastergrid_path}")

            if not census_path:
                validation_errors.append("Census file is required")
            elif not Path(census_path).exists():
                validation_errors.append(f"Census file not found: {census_path}")

            if covariate_count == 0:
                validation_errors.append("At least one covariate is required")

            if mask_path and not Path(mask_path).exists():
                validation_errors.append(f"Water mask file not found: {mask_path}")

            if constrain_path and not Path(constrain_path).exists():
                validation_errors.append(f"Constrain file not found: {constrain_path}")

            if agesex_path and not Path(agesex_path).exists():
                validation_errors.append(f"Age-sex census file not found: {agesex_path}")

            if validation_errors:
                for error in validation_errors:
                    self.logger.error(error)
                return False

            return True

        except Exception as e:
            raise FileHandlerError(f"Input validation failed: {str(e)}")
