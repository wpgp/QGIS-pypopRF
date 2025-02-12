# Installing QGIS pypopRF Plugin

This guide walks you through the process of installing the pypopRF plugin for QGIS. The plugin provides advanced population mapping capabilities with support for age-sex structure analysis, water masking, and spatial constraints.

## System Requirements

### QGIS Version
- QGIS 3.10 or later (recommended: QGIS 3.28 or later)
- Both Long Term Release (LTR) and latest versions are supported
- Python 3.9 - 3.12 compatibility

### Operating Systems
- Windows 10/11 (64-bit)
- Ubuntu 20.04/22.04 or other Linux distributions
- macOS 11 (Big Sur) or later

### Hardware Requirements
- Minimum 8GB RAM (16GB recommended for large datasets)
- Multi-core processor recommended for parallel processing
- SSD storage recommended for better performance
- Sufficient free disk space for analysis outputs

## Installation Methods

### Method 1: Install from QGIS Plugin Repository (Recommended)

- Open QGIS
- Go to `Plugins` → `Manage and Install Plugins`
- In the Plugins dialog:
  - Select `All` or `Not installed` from the left sidebar
  - Type "pypopRF" in the search bar
  - Find "pypopRF Population Mapping" in the list
  - Click `Install Plugin`
- Wait for automatic dependency installation
- Click `Close` when complete

The plugin will appear in your `Plugins` menu and toolbar as "pypopRF Population Mapping".

### Method 2: Manual Installation

For offline installation or specific versions:

- Download the plugin ZIP file:
   - Visit [GitHub Releases](https://github.com/wpgp/QGIS-pypopRF/releases)
   - Download the latest release ZIP file

- Install in QGIS:
   - Go to `Plugins` → `Manage and Install Plugins`
   - Select `Install from ZIP` from the left sidebar
   - Click `Browse` and select the downloaded ZIP file
   - Click `Install Plugin`

- Plugin Location:
   - Windows: `C:/Users/<username>/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

## Dependencies

The plugin automatically installs required Python packages:
- numpy (1.26.4)
- rasterio (1.4.3)
- geopandas (1.0.1)
- scikit-learn (1.4.2)

## Post-Installation Steps

**Enable the Plugin:**
   - Go to `Plugins` → `Manage and Install Plugins`
   - Find "pypopRF Population Mapping" in the list
   - Check the box next to it to enable

**Verify Installation:**
   - The pypopRF icon should appear in your QGIS toolbar
   - The plugin should be listed under `Plugins` → `pypopRF`
   - Test plugin launch to ensure all dependencies are installed

**First Launch:**
   - Click the pypopRF icon or find it in the Plugins menu
   - The plugin interface should open showing all available tabs:
     - Project
     - Input Data
     - Settings
     - Console

## Troubleshooting

### Common Installation Issues

**Plugin Not Found in Repository**
   - Check your internet connection
   - Verify QGIS Plugin Repository settings
   - Try refreshing the plugin list
   - Check proxy settings if behind a firewall

**Dependencies Installation Failed**
   - Check Python console for specific error messages
   - Verify Python package installation permissions
   - Try manual installation of dependencies:
     ```bash
     pip install -r requirements.txt
     ```
   - Check system PATH settings

**Plugin Not Loading**
   - Verify QGIS version compatibility
   - Check Python version compatibility
   - Ensure all dependencies are properly installed
   - Check system permissions for plugin directory
   - Review QGIS log for error messages

**Memory or Performance Issues**
   - Check available system memory
   - Close unnecessary applications
   - Adjust block processing settings if needed
   - Consider hardware upgrades for large datasets

### Getting Help
- Check [GitHub Issues](https://github.com/wpgp/QGIS-pypopRF/issues) for known problems
- Search existing solutions in the documentation
- Create a new issue with detailed error information
- Contact the WorldPop SDI team for support

## Updating the Plugin

The plugin includes automatic update notifications:

**Automatic Updates:**
   - QGIS will notify you when updates are available
   - Click "Update" when prompted

**Manual Updates:**
   - Go to `Plugins` → `Manage and Install Plugins`
   - Select `Installed` from the left sidebar
   - Click `Upgrade All` or find pypopRF and click `Upgrade Plugin`
   - Wait for dependency updates to complete

## Uninstalling

To remove the plugin:

- Go to `Plugins` → `Manage and Install Plugins`
- Select `Installed` from the left sidebar
- Find "pypopRF Population Mapping"
- Click `Uninstall Plugin`
- Optional: Remove configuration files:
   - Delete plugin directory from QGIS plugins folder
   - Remove any remaining configuration files

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>

---

*Next: [Quick Start Guide](quickstart.md)*