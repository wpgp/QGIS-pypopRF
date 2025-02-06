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
- Python 3.9 - 3.12
- Plugin dependencies will be installed automatically during installation

## Installation

1. Download the plugin ZIP file from the [GitHub repository](https://github.com/wpgp/QGIS-pypopRF/releases)
2. In QGIS, go to "Plugins" → "Manage and Install Plugins" → "Install from ZIP"
3. Select the downloaded ZIP file
4. During installation, a console window will open showing the automatic installation of required Python packages. Please do not interrupt this process as it may take several minutes.

Note: Installation through the official QGIS Plugin Repository will be available soon.


## Quick Start

1. **Initialize Project**
   - Open pypopRF from the QGIS plugins menu
   - Choose a working directory
   - Click "Initialize New Project"

2. **Configure Inputs**
   - Add mastergrid
   - Add census data
   - Add covariates
   - Optional: Add water mask and/or constraints

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

The plugin generates the following files in your project's output directory:

### When running without constraints:
- **dasymetric_unconstrained.tif**: Final high-resolution population distribution

### When running with constraints:
- **dasymetric_unconstrained.tif**: Population distribution without constraints applied
- **dasymetric_constrained.tif**: Population distribution with constraints applied

Additional outputs:
- **prediction.tif**: Probability surface
- **normalized_census.tif**: Normalized values
- **Logs**: Detailed processing information


## Getting Help

- Documentation: https://wpgp.github.io/QGIS-pypopRF/
- Issues & Support: https://github.com/wpgp/QGIS-pypopRF/issues
- WorldPop SDI: https://sdi.worldpop.org

## For Developers

Interested in contributing? Check our [documentation](https://wpgp.github.io/QGIS-pypopRF/developers/) for:
- Project structure
- Development setup

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

Developed by the WorldPop SDI Team at the University of Southampton:
- Borys Nosatiuk (b.nosatiuk@soton.ac.uk)
- Rhorom Priyatikanto (rhorom.priyatikanto@soton.ac.uk)
- Maksym Bondarenko (m.bondarenko@soton.ac.uk)
- Wenbin Zhang (wb.zhang@soton.ac.uk)
- Tom McKeen (t.l.mckeen@soton.ac.uk)
- Elena Vataga (e.vataga@soton.ac.uk)