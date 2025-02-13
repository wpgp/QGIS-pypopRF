# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-02-13

First release of the QGIS pypopRF Plugin.

### Added
- Create high-resolution population maps from census data
- Use building data and other geospatial covariates as predictive variables
- Automated machine learning workflow with Random Forest
- Support for age-sex population structure mapping
- Parallel processing for large datasets
- Real-time progress monitoring and logging
- Integration with QGIS layer system
- Support for constraining layers and water masks
- Detailed processing logs and model statistics
- Feature importance analysis
- Support for QGIS 3.0+
- Python 3.9 - 3.12 compatibility

### Dependencies
- numpy==1.26.4
- rasterio==1.4.3
- geopandas==1.0.1
- scikit-learn==1.4.2

### Documentation
- Installation instructions
- User guide with interface description
- Input data requirements
- Settings configuration guide
- Running analysis documentation