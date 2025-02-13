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
- Support for age-sex population structure mapping

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

## Input Data Requirements

### Required Files:
- **Mastergrid**: GeoTIFF file defining analysis zones
- **Census Data**: CSV file with population counts
- **Covariates**: One or more GeoTIFF files (e.g., building data)

### Optional Files:
- **Age-Sex Data**: CSV file with age-sex population structure
- **Water Mask**: For excluding water bodies
- **Constraints**: Additional spatial constraints

## Outputs

The plugin generates the following files in your project's output directory:

### Population Distribution:
- **normalized_census.tif**: Normalized census values
- **population_unconstrained.tif**: Default population distribution output
- **population_constrained.tif**: Distribution with constraints (when provided)

### Machine Learning:
- **model.pkl.gz**: Trained Random Forest model
- **scaler.pkl.gz**: Feature scaler
- **features.csv**: Extracted features with importance metrics

### Additional Outputs:
- **agesex/**: Age-sex structure outputs (when age-sex data provided)
- Detailed processing logs

## Getting Help

- Documentation: https://wpgp.github.io/QGIS-pypopRF/
- Issues & Support: https://github.com/wpgp/QGIS-pypopRF/issues
- WorldPop SDI: https://sdi.worldpop.org


## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Citation

If you use QGIS-pypopRF in your research, please cite:

```bibtex
@software{QGIS-pypopRF,
  author = {Nosatiuk B., Priyatikanto R., Zhang W., McKeen T., Vataga E., Tejedor-Garavito N, Bondarenko M.},
  title = {QGIS-pypopRF: Population Prediction and Dasymetric Mapping Tool},
  publisher = {GitHub},
  url = {https://github.com/wpgp/QGIS-pypopRF}
}
```


## Development Team

Developed by the WorldPop SDI Team:
- Borys Nosatiuk (b.nosatiuk@soton.ac.uk) - Project Lead
- Rhorom Priyatikanto (rhorom.priyatikanto@soton.ac.uk)
- Maksym Bondarenko (m.bondarenko@soton.ac.uk)
- Wenbin Zhang (wb.zhang@soton.ac.uk)
- Tom McKeen (t.l.mckeen@soton.ac.uk)
- Elena Vataga (e.vataga@soton.ac.uk)
- Natalia Tejedor Garavito (n.tejedor-garavito@soton.ac.uk)
