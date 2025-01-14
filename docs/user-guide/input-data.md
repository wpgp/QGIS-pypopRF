# Input Data Requirements

This guide details the requirements and specifications for all input data used in the pypopRF plugin.

## Required Input Files

### 1. Mastergrid (Required)

The mastergrid is a raster file defining analysis zones that match your census units.

**Technical Requirements:**
- Format: GeoTIFF (.tif)
- Data Type: Integer
- Values: Unique IDs for each zone
- No Data Value: Typically -99 or 0
- CRS: Must match other input rasters

**Important Considerations:**
- Zone IDs must match census data
- Continuous, non-overlapping zones
- Complete coverage of study area
- Consistent with administrative boundaries

**Common Issues:**
- Missing or duplicate zone IDs
- Gaps between zones
- Inconsistent resolution with covariates
- CRS mismatches

### 2. Census Data (Required)

Population counts and zone information in tabular format.

**Technical Requirements:**
- Format: CSV file (.csv)
- Required Columns:
  - Zone ID (matching mastergrid)
  - Population count
- Encoding: UTF-8
- No special characters in headers

**Example Structure:**
```csv
id,population
1,2500
2,3200
3,1800
```

**Data Validation:**
- No negative population values
- No missing zone IDs
- Population values as numbers
- Zone IDs match mastergrid

### 3. Covariates (At least one required)

Raster files containing predictive variables for population distribution.

**Technical Requirements:**
- Format: GeoTIFF (.tif)
- Resolution: Consistent across all covariates
- Extent: Must cover mastergrid extent
- CRS: Must match mastergrid

**Common Covariates:**
1. Building Counts
   - Count of structures per pixel
   - Integer values
   - Indicates settlement density

2. Building Footprints
   - Built-up area per pixel
   - Float values (m²)
   - Represents development intensity

3. Building Volume
   - 3D building information
   - Float values (m³)
   - Indicates vertical development

**Important Considerations:**
- Consistent resolution with mastergrid
- Proper alignment of pixels
- Appropriate No Data values
- Value ranges make sense

## Optional Input Files

### 1. Water Mask

Used to exclude water bodies from analysis.

**Technical Requirements:**
- Format: GeoTIFF (.tif)
- Data Type: Binary (0/1)
- Resolution: Match mastergrid
- Value Definition:
  - 1: Water
  - 0: Land


### 2. Constraints

Additional spatial constraints for population distribution.

**Technical Requirements:**
- Format: GeoTIFF (.tif)
- Data Type: Binary or float
- Resolution: Match mastergrid
- Values: 0-1 range for weighting

## Data Preparation Tips

### Coordinate Reference System (CRS)
1. Check CRS of all inputs
2. Reproject if necessary
3. Use consistent CRS across dataset
4. Document transformations

### Resolution and Extent
1. Match all raster resolutions
2. Align pixel grids
3. Set consistent extent
4. Handle edge effects

### Data Quality
1. Check for missing values
2. Validate value ranges
3. Verify spatial alignment
4. Test for artifacts

## Common Data Issues and Solutions

### Mastergrid Issues
- **Problem**: Gaps between zones
  - **Solution**: Fill gaps using GIS tools
- **Problem**: Duplicate IDs
  - **Solution**: Verify and correct zone numbering

### Census Data Issues
- **Problem**: Missing values
  - **Solution**: Fill or remove affected zones
- **Problem**: ID mismatches
  - **Solution**: Align IDs with mastergrid

### Covariate Issues
- **Problem**: Different resolutions
  - **Solution**: Resample to consistent resolution
- **Problem**: Misaligned pixels
  - **Solution**: Snap to reference grid

## Data Validation Checklist

Before running analysis:

- [ ] All required files present
- [ ] Consistent CRS across datasets
- [ ] Matching resolutions
- [ ] Census IDs match mastergrid
- [ ] No missing or invalid values
- [ ] Proper file formats
- [ ] Correct column names
- [ ] Valid value ranges
- [ ] Complete spatial coverage

## File Size Considerations

Recommended maximum file sizes:
- Raster files: < 4 GB each
- Census CSV: < 100 MB
- Total project data: < 20 GB


## Additional Resources

- [QGIS Raster Processing Guide](https://docs.qgis.org/latest/en/docs/user_manual/processing/index.html)
- [Census Data Preparation](https://wpgp.github.io/pypopRF/data-preparation)
- [Building Data Resources](https://sdi.worldpop.org/resources)

---

*Next: [Settings Guide](settings.md)*