# Settings Guide

This guide explains the available settings in the pypopRF plugin and how to configure them for optimal results.

## Settings Overview

The settings tab contains four main sections:
- Census Settings
- Processing Options
- Logging Settings
- Output Options

## Census Settings

### Basic Census Fields
- **Population Column**: Name of the column containing population counts
  - Default: "pop"
  - Must match your CSV header exactly
  - Case-sensitive

- **ID Column**: Name of the column containing zone IDs
  - Default: "id"
  - Must match zone IDs in mastergrid
  - Case-sensitive

### Age-Sex Structure Settings
When using age-sex data:
- Column names should start with 'm' or 'f'
- Example: m0_4, f0_4, m5_9, f5_9
- Must match zone IDs with main census

## Processing Options

### Parallel Processing
- **Enable Parallel Processing**: Use multiple CPU cores
  - Recommended for faster processing
  - Requires more memory
  - Default: Enabled

- **CPU Cores**: Number of cores to use
  - Recommended: Leave 2 cores free
  - Example: On 8-core system, use 6 cores
  - Adjust based on available memory

### Block Processing
- **Enable Block Processing**: Process data in chunks
  - Recommended for large datasets
  - Helps manage memory usage
  - Default: Enabled

- **Block Size**: Size of processing chunks
  - Default: 512x512
  - Options: 256x256, 512x512, 1024x1024
  - Smaller blocks use less memory

## Logging Settings

### Log Level
- **INFO**: Standard processing information
- **DEBUG**: Detailed technical information
  - Use for troubleshooting
  - Provides more detailed output

### Log File
- **File Name**: Name for log file
  - Default: "logs_pypoprf.log"
  - Saved in output directory
  - Previous log cleared on new run

## Output Options

### QGIS Integration
- **Add Layers to QGIS**: Automatically load results
  - Default: Enabled
  - Creates layer group
  - Applies basic styling

### Output Files
Results saved in project output directory:
- Population prediction
- Normalized census
- Population distribution (unconstrained)
- Population distribution (constrained)
- Age-sex distribution maps (if enabled)

---

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>

*Next: [Running Analysis](running-analysis.md)*