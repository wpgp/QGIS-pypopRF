# QGIS pypopRF Plugin

A QGIS plugin for high-resolution population mapping using machine learning and dasymetric techniques. Create detailed population distribution maps by combining census data with geospatial covariates.

![WorldPop SDI](wp_logo.png)

## Features

- Create high-resolution population maps from census data
- Use building data and other geospatial information as predictive variables
- Automated machine learning workflow with Random Forest
- User-friendly interface integrated into QGIS
- Parallel processing support for large datasets
- Real-time progress monitoring and logging

## Requirements

- QGIS 3.0 or later
- Python packages (installed automatically):
  - numpy, pandas, scikit-learn
  - geopandas, rasterio
  - Other dependencies handled by plugin installer

## Installation

1. Open QGIS
2. Go to "Plugins" → "Manage and Install Plugins"
3. Search for "pypopRF"
4. Click "Install Plugin"

## Quick Start

1. **Initialize Project**
   - Open pypopRF from the QGIS plugins menu
   - Choose a working directory
   - Click "Initialize New Project"

2. **Configure Inputs**
   - Add mastergrid (zone definitions)
   - Add census data (population counts)
   - Add building covariates (counts, footprints, heights)
   - Optional: Add water mask or constraints

3. **Adjust Settings**
   - Set processing parameters
   - Configure census column names
   - Enable/disable parallel processing

4. **Run Analysis**
   - Click "Start"
   - Monitor progress in the console
   - Results automatically load in QGIS

## Input Data Requirements

### Required Files:
- **Mastergrid**: GeoTIFF file defining analysis zones
- **Census Data**: CSV file with population counts
- **Covariates**: One or more GeoTIFF files (e.g., building data)

### Optional Files:
- **Water Mask**: For excluding water bodies
- **Constraints**: Additional spatial constraints

## Outputs

The plugin generates several files in your project's output directory:

- **Final Map**: High-resolution population distribution (dasymetric.tif)
- **Intermediate**: Probability surface and normalized values
- **Analysis**: Feature importance plots and statistics
- **Logs**: Detailed processing information

## Getting Help

- Documentation: https://wpgp.github.io/QGIS-pypopRF/
- Issues & Support: https://github.com/wpgp/QGIS-pypopRF/issues
- WorldPop SDI: https://sdi.worldpop.org

## For Developers

Interested in contributing? Check our [documentation](https://wpgp.github.io/QGIS-pypopRF/developers/) for:
- Project structure
- Development setup
- Contributing guidelines
- API reference

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

Developed by the WorldPop SDI Team at the University of Southampton:
- Borys Nosatiuk (b.nosatiuk@soton.ac.uk)
- Rhorom Priyatikanto (rhorom.priyatikanto@soton.ac.uk)
- Maksym Bondarenko (m.bondarenko@soton.ac.uk)
- Andrew Tatem (a.j.tatem@soton.ac.uk)