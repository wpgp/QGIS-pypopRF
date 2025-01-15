# Quick Start Guide

This guide will help you create your first population map using the QGIS pypopRF plugin. We'll walk through a basic workflow from project setup to final output.

## Overview

A typical workflow consists of these steps:

1. Project initialization
2. Data preparation
3. Running the analysis
4. Viewing results

Expected time: 15-30 minutes (depending on the size and complexity of your data)

## Before You Begin

Ensure you have:

- QGIS installed and pypopRF plugin enabled
- Sample data files:

  - Census boundaries with population counts
  - Building footprints or similar covariates
  - Administrative boundaries

## Step 1: Initialize Project

1. Open QGIS
2. Click the pypopRF icon in the toolbar or find it in `Plugins → pypopRF`
3. In the plugin window:

   - Select the "Main" tab
   - Choose a working directory
   - Click "Initialize New Project"


A new project structure will be created with the necessary folders:
```
my_project/
├── data/      (for input files)
├── output/    (for results)
└── config.yaml
```

## Step 2: Prepare Input Data

### Add Required Files
1. In the "Input Data" tab:
   
   **Mastergrid File:**

   - Click "Browse" next to Mastergrid
   - Select your zone definition raster
   - Format: GeoTIFF with zone IDs

   **Census Data:**

   - Click "Browse" next to Census File
   - Select your population data CSV
   - Must contain: zone IDs and population counts

   **Covariates:**

   - Click "Add Covariate"
   - Select building/infrastructure rasters
   - Add at least one covariate
   
   **Optional Files:**
   - Water mask to exclude water bodies
   - Constraints for specific areas

## Step 3: Configure Settings

In the "Settings" tab:

1. **Census Fields:**

   - Set Population Column Name (e.g., "pop")
   - Set ID Column Name (e.g., "id")

2. **Processing Options:**

   - Enable parallel processing if needed
   - Set number of CPU cores
   - Adjust block size for large areas


## Step 4: Run Analysis

1. Verify all required inputs are set (green indicators)
2. Click the "Start" button
3. Monitor progress in the console window
4. Wait for processing to complete


## Step 5: View Results

Once processing is complete:

1. Output files are automatically added to QGIS
2. You'll see three new layers:
   - Prediction surface
   - Normalized census
   - Final population distribution


The main output files are saved in your project's output directory:

- `prediction.tif`: Initial population prediction
- `dasymetric.tif`: Final high-resolution distribution
- `normalized_census.tif`: Intermediate normalization
- `features.csv`: Extracted covariate features

## Next Steps

- Adjust symbolization for better visualization
- Export maps for reports
- Try different covariates
- Experiment with processing parameters

## Common Issues

1. **Missing Data Error:**

   - Ensure all required files are loaded
   - Check file paths in config.yaml

2. **Processing Stops:**

   - Reduce number of CPU cores
   - Increase block size
   - Check available memory

3. **Unexpected Results:**

   - Verify census data columns
   - Check covariate alignment
   - Review mastergrid zones

## Getting Help
- See detailed [User Guide](../user-guide/interface.md)
- Report issues on [GitHub](https://github.com/wpgp/QGIS-pypopRF/issues)

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>

---

*Next: [User Interface Guide](../user-guide/interface.md)*