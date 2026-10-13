import platform
import os
import shutil
import tempfile
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
                         progress=None) -> Optional[str]:
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
            if not source_file.is_file():
                self.logger.error(f"Source file not found: {source_path}")
                raise FileNotFoundError(f"Source file not found: {source_path}")

            data_dir = Path(self.working_dir) / self.data_dir
            data_dir.mkdir(parents=True, exist_ok=True)

            dest_file = data_dir / source_file.name
            # Check if destination exists
            # GDAL resolves sidecars beside the selected pathname, not by inode.
            # An outside hardlink/symlink can therefore have a different mask.
            if (dest_file.exists() and source_file.samefile(dest_file)
                    and source_file.parent.resolve() == dest_file.parent.resolve()):
                return source_file.name
            if dest_file.exists():
                raise FileExistsError(f"Import would overwrite an existing input: {dest_file}")

            sidecars = []
            if source_file.suffix.lower() in {".tif", ".tiff"}:
                sidecars = [Path(str(source_file) + suffix) for suffix in (".msk", ".aux.xml")]
                sidecars += [source_file.with_suffix(suffix) for suffix in (".tfw", ".tifw", ".wld", ".prj")]
                self._reject_sidecars(sidecars)

            descriptor, pending_name = tempfile.mkstemp(prefix=".import-", suffix=".tmp", dir=data_dir)
            os.close(descriptor)
            pending = Path(pending_name)
            original_metadata = source_file.stat()
            try:
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
                if (original_metadata.st_size, original_metadata.st_mtime_ns) != (current_metadata.st_size, current_metadata.st_mtime_ns):
                    raise FileHandlerError("Source changed during import; retry after it finishes updating")
                # A writer can create a GDAL mask/metadata file without changing
                # the TIFF's size or timestamp while our staged copy is running.
                self._reject_sidecars(sidecars)
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
            return source_file.name

        except Exception as e:
            self.logger.error(f"Failed to copy file: {str(e)}")
            raise FileHandlerError(f"Failed to copy file: {str(e)}")

    @staticmethod
    def _reject_sidecars(paths):
        present = [path.name for path in paths if path.is_file()]
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

    def open_folder(self, folder_path: str) -> None:
        """Open folder in system file explorer.

        Args:
            folder_path: Path to folder to open

        Raises:
            FileHandlerError: If folder cannot be opened
        """

        if folder_path and Path(folder_path).exists():
            try:
                from qgis.PyQt.QtCore import QUrl
                from qgis.PyQt.QtGui import QDesktopServices
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(folder_path).resolve()))):
                    raise FileHandlerError("The system could not open this folder")
            except Exception as e:
                self.logger.error(f"Failed to open folder: {str(e)}")
                raise FileHandlerError(f"Failed to open folder: {str(e)}")
        else:
            self.logger.error("Folder not found")
