# Settings Guide

This guide explains all available settings in the pypopRF plugin and how they affect your analysis.

## Settings Overview

The settings tab contains several groups of options:

- Logging Settings
- Census File Settings
- Process Settings
- Output Settings

## Logging Settings

Control how the plugin records its operations and provides feedback.

### Log File Options
- **Save Logs**: Enable/disable log file creation

  - Recommended: Enable for troubleshooting
  - Logs stored in output directory
  - Useful for error tracking

- **Log File Name**: Default "logs_pypoprf.log"

  - Can be customized
  - Previous log cleared on new run
  - UTF-8 encoding used

### Logging Level
- **INFO** (Default)

  - Standard processing information
  - Major steps and outcomes
  - Suitable for normal use

- **DEBUG**

  - Detailed technical information
  - Memory usage statistics
  - Processing details
  - Use for troubleshooting

## Census File Settings

Configure how the plugin reads your census data.

### Column Names
- **Population Column Name**: Default "pop"

  - Must match CSV header exactly
  - Case-sensitive
  - No spaces recommended

- **ID Column Name**: Default "id"

  - Must match mastergrid zone IDs
  - Case-sensitive
  - Numeric values required

### Important Considerations
- Column names must exist in CSV
- Values must be properly formatted
- No special characters in names
- Consistent with mastergrid IDs

## Process Settings

Control how the analysis is performed.

### Parallel Processing

- **Enable Parallel Processing**

  - Uses multiple CPU cores
  - Faster processing for large areas
  - Memory usage increases

- **CPU Cores Selection**
  ```
  Recommended cores = Total cores - 2
  Example: 8 core system → Use 6 cores
  ```

Memory Usage Guidelines:

| Cores | Min RAM  | Recommended RAM |
|-------|----------|-----------------|
| 2     | 8 GB     | 16 GB           |
| 4     | 16 GB    | 32 GB           |
| 6     | 24 GB    | 48 GB           |
| 8     | 32 GB    | 64 GB           |

### Block Processing

- **Enable Block Processing**

  - Processes raster in chunks
  - Reduces memory usage
  - Suitable for large datasets

- **Block Size Options**

  - Default: 512x512 pixels
  - Alternative: 256x256 for less memory
  - Custom sizes available

Memory Impact:

| Block Size  | Memory Usage | Speed     |
|-------------|--------------|-----------|
| 256x256     | Lower        | Slower    |
| 512x512     | Moderate     | Balanced  |
| 1024x1024   | Higher       | Faster    |

### Performance Optimization

Recommended settings based on data size:

**Small Areas** (< 1000x1000 pixels):

- Parallel: Enable
- Cores: 2-4
- Block Size: 512x512

**Medium Areas** (1000x5000 pixels):

- Parallel: Enable
- Cores: 4-6
- Block Size: 512x512

**Large Areas** (> 5000x5000 pixels):

- Parallel: Enable
- Cores: Based on RAM
- Block Size: 256x256

## Output Settings

Configure how results are handled.

### QGIS Integration
- **Add Layers to QGIS**

  - Automatically loads results
  - Creates appropriate styling
  - Groups outputs logically

### Output Files
Generated in project output directory:

- prediction.tif
- normalized_census.tif
- dasymetric.tif
- features.csv

## Advanced Configuration

### Manual Config Editing
The config.yaml file in your project directory contains additional settings:

```yaml
work_dir: "path/to/project"
output_dir: output
mastergrid: mastergrid.tif
mask: mask.tif
covariates:
  buildingCount: buildingCount.tif
  buildingSurface: buildingSurface.tif
  buildingVolume: buildingVolume.tif
constrain: constrain.tif
census_data: census.csv
census_pop_column: pop
census_id_column: id
by_block: true
block_size:
- 256
- 256
max_workers: 8
logging:
  level: INFO
  file: logs_pypoprf.log

```

### Memory Management

Tips for managing memory usage:

1. Monitor system resources
2. Adjust block size first
3. Reduce parallel cores if needed
4. Use task manager/system monitor

## Settings Checklist

Before running analysis:

- Verify column names match CSV
- Check available system memory
- Set appropriate block size
- Configure logging if needed
- Test with small area first

## Troubleshooting Settings

Common issues and solutions:

1. **Out of Memory**

   - Reduce block size
   - Decrease parallel cores
   - Enable block processing

2. **Slow Processing**

   - Increase block size
   - Add more cores
   - Check disk speed

3. **Column Errors**

   - Verify CSV structure
   - Check column names
   - Validate data types

## Best Practices

1. Memory Usage

   - Leave 25% RAM free
   - Monitor usage
   - Close other applications

2. Processing Speed

   - Balance cores vs memory
   - Use SSD if possible
   - Optimize input data

3. Configuration

   - Document settings
   - Test on samples
   - Back up config file

---

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>

*Next: [Running Analysis](running-analysis.md)*