# QGIS pypopRF Plugin Documentation

<div align="center">
  <img src="images/wp_logo.png" alt="WorldPop Logo" width="200"/>
  <br/>
  <em>High-Resolution Population Mapping Made Easy</em>
</div>

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>

## Quick Navigation
- [About pypopRF](#about-pyPoprf)
- [How It Works](#how-it-works)
- [Plugin Interface](#plugin-interface)
- [Analysis Results](#analysis-results)
- [Getting Started](#getting-started)
- [Support](#support)

## About pypopRF

pypopRF is a powerful tool developed by the WorldPop SDI Team that transforms your input data into detailed population distribution maps. It combines census data, building information, and machine learning to create accurate population estimates.

## How It Works

```mermaid
graph LR
    A[Load Data] --> B[Configure Settings]
    B --> C[Run Analysis]
    C --> D[Get Results]
    style A fill:#e1f5fe
    style B fill:#e8f5e9
    style C fill:#fff3e0
    style D fill:#f3e5f5
```

## Plugin Interface

<div align="center">
  <img src="images/main_interface.png" alt="pypopRF Plugin Interface" width="800"/>
  <br/>
  <em>Main plugin interface with labeled components</em>
</div>

### Key Components:

1. **Project Tab**: Initialize your project and manage settings
2. **Input Data Tab**: Configure all required data files
3. **Settings Tab**: Adjust processing parameters
4. **Console**: Monitor progress and view logs
5. **Control Panel**: Start/stop analysis and view progress

💡 **Pro Tip:** Use the tabs to navigate through the workflow in a logical sequence.

## Analysis Results

The plugin generates three key outputs that show the progression of the analysis:

<div align="center">
  <div style="display: flex; justify-content: space-between; margin-bottom: 20px;">
    <div style="flex: 1; margin: 10px;">
      <img src="images/prediction.png" alt="Population Prediction" width="250"/>
      <p><strong>1. Population Prediction</strong><br/>
      Initial probability surface showing likely population distribution</p>
    </div>
    <div style="flex: 1; margin: 10px;">
      <img src="images/normalized_census.png" alt="Normalized Census" width="250"/>
      <p><strong>2. Normalized Census</strong><br/>
      Population values adjusted to match census totals</p>
    </div>
    <div style="flex: 1; margin: 10px;">
      <img src="images/dasymetric.png" alt="Final Distribution" width="250"/>
      <p><strong>3. Final Distribution</strong><br/>
      High-resolution population distribution map</p>
    </div>
  </div>
</div>

## Processing in Action

<div align="center">
  <img src="images/analysis.png" alt="Analysis Process" width="700"/>
  <br/>
  <em>Real-time processing feedback and progress monitoring</em>
</div>

## Key Features

✅ **User-Friendly Interface**
- Visual data management
- Intuitive configuration
- Real-time progress tracking
- Direct QGIS integration

⚠️ **Important Considerations**
- Ensure consistent coordinate systems
- Verify input data quality
- Monitor system resources
- Back up project files

## Input Requirements

The plugin needs three main types of data:

1. **Mastergrid File** (Required)
   - Defines analysis zones
   - Matches census boundaries
   - GeoTIFF format

2. **Census Data** (Required)
   - Population counts by zone
   - CSV format
   - Matches mastergrid IDs

3. **Covariates** (At least one required)
   - Building counts/footprints
   - Infrastructure data
   - Other relevant predictors

## Support and Resources

- 🐛 **Report Issues**: [GitHub Issues](https://github.com/wpgp/QGIS-pypopRF/issues)
- 📧 **Get Help**: Contact [WorldPop SDI Team](https://sdi.worldpop.org)
- 📚 **Documentation**: Continue reading guides below
- 🆕 **Updates**: Check [GitHub Releases](https://github.com/wpgp/QGIS-pypopRF/releases)

## About WorldPop SDI

The WorldPop Spatial Data Infrastructure (SDI) Team at the University of Southampton specializes in:
- Population mapping
- Spatial demographics
- Open-source geospatial tools
- Machine learning for population estimation

## License

The QGIS pypopRF plugin is released under the MIT License. See the [LICENSE](https://github.com/wpgp/QGIS-pypopRF/blob/main/LICENSE) file for details.

---

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>

*Next Steps:*
- [Installation Guide](getting-started/installation.md)
- [Quick Start Guide](getting-started/quickstart.md)
- [User Interface Guide](user-guide/interface.md)