import shutil
import platform
import subprocess
from pathlib import Path


class FileHandler:
    """Handler for file operations in QGIS plugin"""

    def __init__(self, working_dir: str, logger):
        """
        Initialize FileHandler.

        Args:
            working_dir: Working directory path
            logger: Logger instance for output messages
        """
        self.working_dir = working_dir
        self.logger = logger

    def set_working_dir(self, working_dir: str):
        """
        Set working directory.

        Args:
            working_dir: New working directory path
        """
        self.working_dir = working_dir

    def copy_to_data_dir(self, source_path: str, file_type: str):
        """
        Copy file to project's data directory.

        Args:
            source_path: Original file path
            file_type: Type of file (mastergrid, mask, covariate, etc.)

        Returns:
            str: Filename of copied file or None if failed
        """
        try:
            source_file = Path(source_path)
            if not source_file.exists():
                self.logger.error(f"Source file not found: {source_path}")
                return None

            data_dir = Path(self.working_dir) / 'data'
            data_dir.mkdir(exist_ok=True)

            dest_file = data_dir / source_file.name
            shutil.copy2(source_path, str(dest_file))

            self.logger.info(f"Copied {file_type} file to data directory: {source_file.name}")
            return source_file.name

        except Exception as e:
            self.logger.error(f"Failed to copy file: {str(e)}")
            return None

    def validate_inputs(self, mastergrid_path: str,
                        census_path: str,
                        covariate_count: int) -> bool:
        """
        Validate required input files.

        Args:
            mastergrid_path: Path to mastergrid file
            census_path: Path to census file
            covariate_count: Number of covariates

        Returns:
            bool: True if all required inputs are valid
        """
        if not mastergrid_path:
            self.logger.error("Mastergrid file is required")
            return False

        if not census_path:
            self.logger.error("Census file is required")
            return False

        if covariate_count == 0:
            self.logger.error("At least one covariate is required")
            return False

        return True

    def open_folder(self, folder_path: str):
        """
        Open folder in system file explorer.

        Args:
            folder_path: Path to folder to open
        """
        if folder_path and Path(folder_path).exists():
            try:
                if platform.system() == "Windows":
                    subprocess.run(['explorer', folder_path])
                elif platform.system() == "Darwin":  # macOS
                    subprocess.run(['open', folder_path])
                else:  # Linux
                    subprocess.run(['xdg-open', folder_path])
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to open folder with error code "
                                  f"{e.returncode}: {str(e)}")
            except Exception as e:
                self.logger.error(f"Failed to open folder: {str(e)}")
        else:
            self.logger.error("Folder not found")
