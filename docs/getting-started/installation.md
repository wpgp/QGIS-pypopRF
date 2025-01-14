# Installing QGIS pypopRF Plugin

This guide walks you through the process of installing the pypopRF plugin for QGIS.

## System Requirements

### QGIS Version
- QGIS 3.0 or later (recommended: QGIS 3.28 or later)
- Both Long Term Release (LTR) and latest versions are supported

### Operating Systems
- Windows 10/11
- Ubuntu 20.04/22.04 or other Linux distributions
- macOS 11 (Big Sur) or later

### Hardware Recommendations
- **Minimum:**
  - 8 GB RAM
  - Dual-core processor
  - 10 GB free disk space
- **Recommended:**
  - 16 GB RAM or more
  - Quad-core processor
  - 50 GB free disk space for large projects

## Installation Methods

### Method 1: Install from QGIS Plugin Repository (Recommended)

1. Open QGIS
2. Go to `Plugins` → `Manage and Install Plugins`
3. In the Plugins dialog:
   - Select `All` or `Not installed` from the left sidebar
   - Type "pypopRF" in the search bar
   - Find "pypopRF Population Mapping" in the list
   - Click `Install Plugin`
4. Wait for the installation to complete
5. Click `Close`

The plugin will now appear in your `Plugins` menu as "pypopRF Population Mapping".

### Method 2: Manual Installation

For cases where you can't access the QGIS Plugin Repository or need a specific version:

1. Download the plugin ZIP file:
   - Visit [GitHub Releases](https://github.com/wpgp/QGIS-pypopRF/releases)
   - Download the latest release ZIP file

2. Install in QGIS:
   - Go to `Plugins` → `Manage and Install Plugins`
   - Select `Install from ZIP` from the left sidebar
   - Click `Browse` and select the downloaded ZIP file
   - Click `Install Plugin`

3. Plugin Location:
   - Windows: `C:/Users/<username>/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

## Post-Installation Steps

1. **Enable the Plugin:**
   - Go to `Plugins` → `Manage and Install Plugins`
   - Find "pypopRF Population Mapping" in the list
   - Check the box next to it to enable

2. **Verify Installation:**
   - The pypopRF icon should appear in your QGIS toolbar
   - The plugin should be listed under `Plugins` → `pypopRF`

3. **First Launch:**
   - Click the pypopRF icon or find it in the Plugins menu
   - The plugin interface should open without errors

## Troubleshooting

### Common Installation Issues

1. **Plugin Not Found in Repository**
   - Check your internet connection
   - Verify QGIS Plugin Repository settings
   - Try refreshing the plugin list

2. **Dependencies Installation Failed**
   - Open QGIS Python Console (Plugins → Python Console)
   - Check error messages
   - Verify Python package installation permissions

3. **Plugin Not Loading**
   - Check QGIS version compatibility
   - Verify Python dependencies
   - Check system permissions


## Updating the Plugin

- QGIS will automatically notify you of plugin updates
- To update manually:
  1. Go to `Plugins` → `Manage and Install Plugins`
  2. Select `Installed` from the left sidebar
  3. Click `Upgrade All` or find pypopRF and click `Upgrade Plugin`

## Uninstalling

To remove the plugin:

1. Go to `Plugins` → `Manage and Install Plugins`
2. Select `Installed` from the left sidebar
3. Find "pypopRF Population Mapping"
4. Click `Uninstall Plugin`

---

*Next: [Quick Start Guide](quickstart.md)*