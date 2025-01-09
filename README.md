# QGIS pypopRF Plugin

A QGIS plugin for high-resolution population mapping using machine learning and dasymetric techniques. This plugin integrates the pypopRF Python package into QGIS, providing a user-friendly interface for population prediction and mapping.

## Overview

pypopRF is a tool developed by the WorldPop SDI Team for creating detailed population distribution maps by combining census data with geospatial covariates using machine learning techniques. The tool uses Random Forest regression for prediction and dasymetric mapping for high-resolution population redistribution.

## Features

### Core Functionality
- Feature extraction from geospatial covariates
- Random Forest-based population modeling
- Dasymetric mapping for high-resolution output
- Support for parallel processing and block-based computation
- Comprehensive logging and progress tracking

### QGIS Integration
- Intuitive graphical user interface
- Project management tools
- Real-time progress monitoring
- Direct visualization in QGIS
- Integrated logging console

## Installation

### Requirements
- QGIS 3.0 or later
- Python 3.12
- Required Python packages:
  - numpy >= 1.24.0
  - pandas >= 2.0.0
  - geopandas >= 0.14.0
  - rasterio >= 1.3.0
  - scikit-learn >= 1.3.0
  - matplotlib >= 3.7.0
  - tqdm >= 4.65.0
  - pyyaml >= 6.0.0
  - joblib >= 1.3.0

### Installation Steps

1. Download the plugin:
```bash
git clone https://github.com/wpgp/QGIS-pypopRF.git
```

2. Install to QGIS plugins directory:
   - Windows: `C:/Users/<username>/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

3. Enable the plugin in QGIS:
   - Open QGIS
   - Go to Plugins → Manage and Install Plugins
   - Find "pypopRF" in the list
   - Check the box to enable

## Usage

### 1. Project Setup

1. Open the pypopRF plugin in QGIS
2. Select working directory
3. Click "Initialize New Project"
   - Creates project directory structure
   - Generates default configuration file
   - Sets up data and output directories

### 2. Data Configuration

#### Required Files:
- **Mastergrid (GeoTIFF)**: 
  - Defines analysis zones
  - Must align with census boundaries
  - Consistent CRS and resolution with covariates

- **Census Data (CSV)**:
  - Population counts by administrative unit
  - Must include:
    - ID column (matching mastergrid zones)
    - Population column
    - Additional attributes as needed

- **Covariates (GeoTIFF)**:
  - At least one covariate required
  - Common examples:
    - Building counts
    - Building footprint area
    - Building volume
  - Must match mastergrid resolution and extent

#### Optional Files:
- **Water Mask (GeoTIFF)**:
  - For excluding water bodies
  - Binary raster (1 = water, 0 = land)

- **Constraints (GeoTIFF)**:
  - Additional spatial constraints
  - Used to refine population distribution

### 3. Settings Configuration

#### Processing Options:
- **Parallel Processing**:
  - Enable/disable parallel computation
  - Set number of CPU cores
  - Memory usage management

- **Block Processing**:
  - Enable for large datasets
  - Configurable block size
  - Default: 512x512 pixels

#### Census Data Settings:
- Population column name (default: "pop")
- ID column name (default: "id")

#### Additional Options:
- Logging level (INFO/DEBUG)
- Progress bar display
- Output visualization settings

### 4. Running Analysis

1. Validate inputs using built-in checks
2. Click "Start" to begin processing
3. Monitor progress in console window:
   - Feature extraction status
   - Model training progress
   - Prediction generation
   - Dasymetric mapping steps

### 5. Output Files

The plugin generates several output files in the project's output directory:

#### Main Outputs:
- **prediction.tif**: Population probability surface
- **dasymetric.tif**: Final high-resolution population distribution
- **normalized_census.tif**: Normalized population values
- **features.csv**: Extracted covariate features

#### Additional Files:
- **feature_selection.png**: Feature importance visualization
- **visualization.png**: Combined visualization of results
- **pypoprf.log**: Processing log file
- **model.pkl.gz**: Trained Random Forest model
- **scaler.pkl.gz**: Fitted feature scaler

## Troubleshooting

### Common Issues:
1. **Memory Errors**:
   - Reduce block size
   - Decrease number of parallel workers
   - Process larger areas in segments

2. **Input Data Errors**:
   - Ensure consistent CRS across all rasters
   - Verify matching resolutions and extents
   - Check census data column names

3. **Processing Errors**:
   - Check log file for detailed error messages
   - Verify input data validity
   - Ensure sufficient disk space

## Development

### Project Structure:
```
pypopRF/
├── core/
│   ├── feature_extraction.py
│   ├── model.py
│   └── dasymetric.py
├── utils/
│   ├── raster.py
│   ├── vector.py
│   └── visualization.py
└── config/
    └── settings.py
```

### Contributing:
1. Fork the repository
2. Create a feature branch
3. Submit pull request with:
   - Clear description of changes
   - Updated tests
   - Documentation updates

## License
MIT License - See LICENSE file for details

## Contact
- Authors: 
  - Borys Nosatiuk (b.nosatiuk@soton.ac.uk)
  - Rhorom Priyatikanto (rhorom.priyatikanto@soton.ac.uk)
- WorldPop SDI Team: https://sdi.worldpop.org
- Issues: https://github.com/wpgp/pypopRF/issues