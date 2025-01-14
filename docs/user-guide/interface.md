# User Interface Guide

The pypopRF plugin interface is organized into several tabs for different aspects of the population mapping workflow. This guide explains each component of the interface in detail.

## Main Window Overview

The plugin window consists of four main sections:
1. Tab Navigation
2. Input/Settings Area
3. Console Output
4. Progress Bar and Control

### Tab Organization
- **Main**: Project initialization and overview
- **Input Data**: Data file configuration
- **Settings**: Processing and analysis parameters

## Main Tab

The main tab provides project management and quick start information.

### Project Configuration
- **Working Directory**: Select or enter the root folder for your project
- **Initialize New Project**: Create project structure and default configuration
- **Open Project Folder**: Quick access to project directory

### Quick Start Guide
- Built-in guide with basic steps
- Links to online documentation
- Contact information and support resources

## Input Data Tab

This tab manages all input data files required for analysis.

### Raster Inputs
- **Mastergrid**: Zone definition raster (required)
  - Format: GeoTIFF
  - Must contain unique zone IDs
  - Should align with census boundaries

- **Mask** (optional): Water or exclusion mask
  - Binary raster (0/1)
  - Used to exclude specific areas

- **Constrain** (optional): Additional constraints
  - Used for refining population distribution
  - Must match mastergrid extent

### Census Data
- **CSV File**: Population data input
  - Must contain zone IDs matching mastergrid
  - Population counts required
  - Additional attributes optional

### Covariates Table
- List of predictive variables
- **Add Covariate**: Add new raster files
- Table columns:
  - Name: Covariate identifier
  - Size: File size
  - File Path: Location on disk
  - Actions: Delete/modify options

## Settings Tab

Configure processing parameters and analysis options.

### Logging Settings
- **Save Logs**: Enable/disable log file creation
- **Log File Name**: Custom name for log file
- **Logging Level**: 
  - INFO: Standard processing information
  - DEBUG: Detailed debugging information

### Census File Settings
- **Population Column Name**: Name of population count column
- **ID Column Name**: Name of zone ID column
- Default values can be changed based on your data

### Process Settings
- **Parallel Processing**: Enable multi-core processing
  - CPU Cores: Number of parallel workers
  - Recommended: Leave 1-2 cores free for system

- **Block Processing**: For large datasets
  - Block Size: Processing chunk dimensions
  - Default: 512x512 pixels
  - Adjust based on available memory

### Additional Options
- **Add Output to QGIS**: Automatically load results
- Progress bar visibility
- Processing feedback options

## Console Area

The lower section of the plugin window shows:
- Processing progress
- Error messages
- Status updates
- Important notifications

### Progress Monitoring
- Progress bar shows current operation status
- Percentage complete indication
- Current processing step display
- Start/Stop button for process control

## Using the Interface Effectively

### Workflow Tips
1. Always initialize project first
2. Verify input data before processing
3. Monitor console for feedback
4. Use appropriate block size for your data

### Best Practices
- Keep input data in project's data directory
- Use descriptive names for covariates
- Monitor memory usage with large datasets
- Save logs for troubleshooting

### Keyboard Shortcuts
- Delete: Remove selected covariates
- Tab: Navigate between fields
- Enter: Activate buttons/controls

## Interface Customization

The interface adapts to your workflow:
- Resizable window
- Adjustable console area
- Collapsible sections
- Persistent settings between sessions

## Error Handling

The interface provides visual feedback for:
- Missing required files
- Invalid input data
- Processing errors
- Configuration issues

Error messages appear in:
1. Console output
2. Status bar
3. Log files
4. Pop-up notifications when critical
