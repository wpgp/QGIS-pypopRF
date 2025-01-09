# QGIS pypopRF Plugin

A QGIS plugin for high-resolution population mapping using machine learning and dasymetric techniques. This plugin integrates the pypopRF Python package into QGIS, providing a user-friendly interface for population prediction and mapping.

## Overview

pypopRF is a tool developed by the WorldPop SDI Team for creating detailed population distribution maps by combining:
- Census data at administrative unit level
- Geospatial covariates (building counts, footprints, heights)
- Machine learning (Random Forest) for prediction
- Dasymetric mapping techniques for high-resolution output

## Key Features

- **User-Friendly Interface**: Easy-to-use graphical interface integrated into QGIS
- **Project Management**: Create and manage pypopRF projects
- **Data Integration**:
  - Support for multiple geospatial covariates
  - Census data integration
  - Optional water mask and constraints
- **Processing Options**:
  - Parallel processing support
  - Block-based processing for large datasets
  - Customizable processing parameters
- **Output Visualization**: Direct visualization in QGIS
- **Progress Tracking**: Real-time progress monitoring and logging

## Installation

### Requirements
- QGIS 3.0 or later
- Python 3.12
- Required Python packages are handled automatically

### Installation Steps

1. Download the plugin:
   ```bash
   git clone --recursive https://github.com/wpgp/QGIS-pypopRF.git
    ```
2. Install to QGIS plugins directory:
    Windows: C:/Users/<username>/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/
    Linux: ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
    macOS: ~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/
3. Enable the plugin in QGIS:
    Open QGIS
    Go to Plugins → Manage and Install Plugins
    Find "pypopRF" in the list
    Check the box to enable

## Usage
1. Project Initialization

* Click "Initialize New Project"
* Select working directory
* Project structure will be created automatically



2. Data Configuration
Required files:

* Mastergrid: Zone definitions for analysis
* Census Data: Population counts by administrative unit
* Covariates: At least one covariate file (e.g., building counts)

Optional files:

* Water Mask: For excluding water bodies
* Constraints: Additional spatial constraints

3. Settings

    Processing parameters:

        * Parallel processing options
        * Block size for large datasets
        * CPU core allocation


    Census data configuration:
    
        * Population column name
        * ID column name


    Logging options

4. Analysis

    Click "Start" to begin processing
    Monitor progress in the console
    Results will be saved in the output directory

## Output Files
* prediction.tif: Population probability surface
* dasymetric.tif: Final population distribution
* normalized_census.tif: Normalized values
* features.csv: Extracted features
* Processing logs and visualizations

