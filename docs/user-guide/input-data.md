# Input Data Requirements

This guide explains the required and optional input data for the pypopRF plugin.

## Required Files

### 1. Mastergrid
A raster file defining your analysis zones:

- Format: GeoTIFF (.tif)
- Values: Unique IDs for each zone
- Must match census data zone IDs
- No gaps or overlaps between zones

### 2. Census Data
Population counts in tabular format:

- Format: CSV file
- Required columns:
    - Zone ID (matching mastergrid)
    - Population count
- Example:

    | id | population |
    |----|------------|
    | 1  | 2500       |
    | 2  | 3200       |
    | 3  | 1800       |

### 3. Covariates

At least one raster file containing predictive variables:

- Format: GeoTIFF (.tif)
- Must cover mastergrid extent
- Common examples:
    - Building footprints
    - Road networks
    - Land use
    - Infrastructure

## Optional Files

### 1. Water Mask
Excludes water bodies from analysis:

- Format: GeoTIFF (.tif)
  - Binary values:
    - 1: Water
    - 0: Land
  - Must cover study area

### 2. Constraints
Defines areas with special population distribution rules:

- Format: GeoTIFF (.tif)
- Binary values for restricted areas
- Must match mastergrid extent

### 3. Age-Sex Structure Data
Additional demographic breakdown:

- Format: CSV file
  - Must include:
    - Zone ID (matching mastergrid)
    - Age-sex group columns (e.g., m0_4, f0_4)
  - Population totals should match main census

## Important Requirements

### Coordinate Systems
- All raster files must use the same CRS
- Check alignment of pixels
- Verify extent coverage

### Data Values
- No negative population values
- Census IDs must match mastergrid
- Valid ranges for all covariates
- Proper NoData values

### File Structure
- Use simple column names
- No special characters
- UTF-8 encoding for CSV files

---

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>

*Next: [Settings Guide](settings.md)*