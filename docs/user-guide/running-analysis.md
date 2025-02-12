# Running Analysis

This guide explains how to run population analysis using the pypopRF plugin and interpret the results.

## Before Starting

### Quick Checklist
✓ All required files loaded
✓ Optional files prepared (if using)
✓ Settings configured
✓ Sufficient disk space (3-4x input data size)
✓ Adequate memory available
✓ Column names verified

### Data Verification
- Census data columns match settings
- Mastergrid IDs match census data
- Covariates cover study area
- Optional files properly configured:
  - Water mask (if using)
  - Constraints (if using)
  - Age-sex data (if using)

## Running the Analysis

### 1. Starting the Process

The Start button will be enabled when:
- All required files are loaded
- Settings are properly configured
- Project is initialized

Click the green "Start" button to begin analysis.

### 2. Processing Stages

The analysis runs through several stages:

#### Feature Extraction (20%)
- Processing covariates
- Calculating zonal statistics
- Extracting predictive features

#### Model Training (40%)
- Training Random Forest model
- Calculating feature importance
- Validating model performance

#### Population Prediction (60%)
- Generating probability surface
- Applying water mask (if enabled)
- Processing spatial constraints (if enabled)

#### Distribution Mapping (80%)
- Creating normalized census
- Generating population distribution
- Processing age-sex structure (if enabled)

#### Finalization (100%)
- Saving output files
- Loading results in QGIS
- Cleaning temporary files

## Monitoring Progress

### Console Output
The console shows:
- Current processing stage
- Progress information
- Warnings or errors
- Processing statistics

### Progress Bar
- Shows overall completion
- Displays current stage
- Updates in real-time

### Process Control
- Use Stop button to cancel (red)
- Processing will complete current stage
- Results up to stop point are saved

## Output Files

### Main Outputs
1. **normalized_census.tif**
   - Census values adjusted to raster format
   - Shows population distribution zones

2. **population_unconstrained.tif**
   - Basic population distribution
   - Without spatial constraints

3. **population_constrained.tif**
   - Population distribution with constraints
   - Only if constraints enabled

### Additional Outputs
- **Age-sex maps** (if enabled)
  - Separate maps for each age-sex group
  - Located in 'agesex' folder

- **Model files**
  - model.pkl.gz: Trained model
  - scaler.pkl.gz: Data scaler
  - features.csv: Feature importance

---

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>