# Quick Start Guide

This guide will help you create your first population map using the QGIS pypopRF plugin. We'll walk through a basic workflow from project setup to final output, including optional advanced features.

## Overview

A typical workflow consists of these steps:

1. Project initialization
2. Data preparation
3. Optional feature setup
4. Running the analysis
5. Viewing results

## Before You Begin

Ensure you have:

- QGIS installed and pypopRF plugin enabled

- Required data files:

  - Census data with population counts (CSV)
  - Mastergrid file defining analysis zones (GeoTIFF)
  - Covariate rasters (e.g., building footprints, infrastructure)
  
- Optional data files:

  - Water mask for excluding water bodies
  - Constraint rasters for specific areas
  - Age-sex population structure data (CSV)

## Step 1: Initialize Project

1. Open QGIS
2. Click the pypopRF icon in the toolbar or find it in `Plugins → pypopRF`
3. In the plugin window:
   - Select the "Project" tab
   - Choose a working directory
   - Click "Initialize New Project"

A new project structure will be created:
```
my_project/
├── data/      (for input files)
├── output/    (for results)
│   ├── agesex/  (for age-sex outputs)
│   └── logs/    (processing logs)
└── config.yaml
```

## Step 2: Prepare Input Data

### Required Files

1. In the "Input Data" tab:
   
**Mastergrid File:**
   - Click "Browse" next to Mastergrid
   - Select your zone definition raster
   - Format: GeoTIFF with unique zone IDs

**Census Data:**
   - Click "Browse" next to Census File
   - Select your population data CSV
   - Must contain: zone IDs and population counts

**Covariates:**
   - Click "Add Covariate"
   - Select building/infrastructure rasters
   - Add at least one covariate
   
### Optional Files

**Water Mask:**
   - Click "Browse" next to Water Mask
   - Select raster defining water bodies
   - Areas with value 1 will be excluded

**Constraints:**
   - Click "Browse" next to Constraints
   - Select raster with constraint areas
   - Used to refine population distribution

**Age-Sex Data:**
   - Click "Browse" next to Age-Sex Census
   - Select CSV with age-sex structure


## Step 3: Configure Settings

In the "Settings" tab:

**Census Fields:**
   - Set Population Column Name (e.g., "pop")
   - Set ID Column Name (e.g., "id")

**Processing Options:**
   - Enable parallel processing for faster analysis
   - Set number of CPU cores (recommended: 6+)
   - Adjust block size for memory management
   - Enable block processing for large areas

**Output Options:**
   - Choose whether to add layers to QGIS
   - Set logging level for process monitoring

## Step 4: Run Analysis

1. Verify inputs (green indicators show ready state)
2. Click the "Start" button
3. Monitor progress in the console window:
   - Feature extraction progress
   - Model training status
   - Prediction and mapping progress
4. Wait for completion message

## Step 5: View Results

The analysis produces several output layers:

### Main Outputs
- `prediction.tif`: Initial population prediction
- `normalized_census.tif`: Census-adjusted values
- `population_unconstrained.tif`: Basic distribution
- `population_constrained.tif`: Distribution with constraints

### Additional Outputs (if using optional features)
- `normalized_census_unconstrained.tif`: Unconstrained census-adjusted values
- `agesex/*.tif`: Age-sex structure maps
- `model.pkl.gz`: Trained Random Forest model
- `scaler.pkl.gz`: Feature scaler
- `features.csv`: Extracted features with importance metrics

All outputs are saved in your project's output directory and can be automatically added to QGIS.

## Getting Help
- Review detailed [User Guide](../user-guide/interface.md)
- Check [Common Issues](../user-guide/troubleshooting.md)
- Report problems on [GitHub](https://github.com/wpgp/QGIS-pypopRF/issues)
- Contact WorldPop SDI team for support

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>

---

*Next: [User Interface Guide](../user-guide/interface.md)*