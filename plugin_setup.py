import os
import sys
import subprocess
import pkg_resources


def get_package_dependencies():
    """Get list of required packages from metadata.txt"""
    try:
        metadata_path = os.path.join(os.path.dirname(__file__), 'metadata.txt')
        with open(metadata_path, 'r') as f:
            for line in f:
                if line.startswith('plugin_dependencies='):
                    # Get dependencies and clean the string
                    deps = line.replace('plugin_dependencies=', '').strip()
                    # Split by comma and clean each package name
                    return [pkg.strip() for pkg in deps.split(',')]
    except Exception as e:
        print(f"Error reading dependencies from metadata: {str(e)}")
        return []


def check_package(package_name):
    """Check if a package is installed"""
    try:
        pkg_resources.get_distribution(package_name)
        return True
    except pkg_resources.DistributionNotFound:
        return False


def install_dependencies():
    """Install required packages using pip"""
    try:
        # Get required packages
        required_packages = get_package_dependencies()

        if not required_packages:
            print("No dependencies found in metadata.txt")
            return False

        # Filter only missing packages
        missing_packages = [pkg for pkg in required_packages if not check_package(pkg)]

        if not missing_packages:
            print("All dependencies are already installed")
            return True

        print(f"Installing missing dependencies: {', '.join(missing_packages)}")

        # Get path to QGIS Python
        qgis_python = sys.executable

        # Install each missing package
        for package in missing_packages:
            try:
                subprocess.check_call([qgis_python, '-m', 'pip', 'install', package])
                print(f"Successfully installed {package}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to install {package}: {str(e)}")
                return False

        print("All dependencies installed successfully")
        return True

    except Exception as e:
        print(f"Failed to install dependencies: {str(e)}")
        return False


if __name__ == '__main__':
    install_dependencies()