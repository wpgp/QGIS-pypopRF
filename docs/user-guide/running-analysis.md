# Running Analysis

This guide explains the process of running population analysis using the pypopRF plugin, including preparation, execution, monitoring, and interpreting results.

## Before Running Analysis

### Pre-run Checklist
- All required files loaded
- Settings configured
- Sufficient disk space
- Adequate memory available
- Column names verified
- CRS consistency checked

### System Preparation
1. Close unnecessary applications
2. Clear QGIS cache if needed
3. Ensure stable power supply
4. Check available disk space
   - Required: 3-4x input data size
   - Recommended: 10x for safety

## Running the Analysis

### Starting the Process

1. **Verification Phase**

   - Input validation
   - Settings check
   - Resource availability check
   - CRS consistency verification

2. **Initialization**

   - Project structure check
   - Temporary directory creation
   - Log file preparation
   - Resource allocation

3. **Click Start**

   - Green button indicates ready
   - Console shows initialization
   - Progress bar activates

### Processing Stages

#### 1. Feature Extraction (20%)
- Loading covariate data
- Calculating zonal statistics
- Feature normalization
- Status shown in console

#### 2. Model Training (40%)
- Random Forest initialization
- Feature importance calculation
- Cross-validation
- Model optimization

#### 3. Prediction Generation (60%)
- Population probability calculation
- Block-wise processing
- Intermediate results saving
- Memory management

#### 4. Dasymetric Mapping (80%)
- Population redistribution
- Constraint application
- Result normalization
- Quality checks

#### 5. Finalization (100%)
- Output validation
- Layer preparation
- Memory cleanup
- Result visualization

## Monitoring Progress

### Console Output
The console window shows:

- Current processing stage
- Detailed progress information
- Warnings and errors
- Memory usage statistics

Example console messages:
```
[INFO] Starting feature extraction...
[INFO] Processing block 1/10...
[INFO] Feature importance calculation...
[INFO] Model training R² score: 0.85
```

### Progress Bar
- Shows overall completion percentage
- Current stage indication
- Time estimation (if available)
- Color-coded status

### Process Control

#### Pause/Resume
- Not currently supported
- Must complete or stop

#### Stop Process
- Click "Stop" button (red)
- Graceful shutdown
- Cleanup temporary files
- May take few moments

## Understanding Results

### Output Files

1. **prediction.tif**

   - Population probability surface
   - Float values (0-1)
   - Higher values = higher probability

2. **normalized_census.tif**

   - Normalized population values
   - Used in final calculations
   - Preserves population totals

3. **dasymetric.tif**

   - Final population distribution
   - Integer values (people)
   - Main analysis result

4. **features.csv**

   - Extracted feature values
   - Model inputs
   - Statistical summaries

### Quality Assessment

#### Statistical Measures
- R² score (model fit)
- RMSE (prediction error)
- Cross-validation results
- Population total preservation

#### Visual Inspection
- Distribution patterns
- Edge effects
- Anomaly detection
- Consistency check

## Handling Errors

### Common Error Messages

1. **Memory Errors**
```
[ERROR] Out of memory in block processing
Solution: Reduce block size or parallel cores
```

2. **Input Data Errors**
```
[ERROR] Column 'population' not found
Solution: Verify CSV column names
```

3. **Processing Errors**
```
[ERROR] Failed to process block
Solution: Check input data validity
```

### Recovery Steps

1. **Process Fails**

   - Check error message
   - Review log file
   - Adjust settings
   - Clear temporary files
   - Restart analysis

2. **System Crashes**

   - Close QGIS
   - Clear temporary files
   - Check system resources
   - Restart with smaller area

## Best Practices

### Performance Optimization
1. Start with small test area
2. Monitor system resources
3. Adjust parameters gradually
4. Document optimal settings

### Quality Control
1. Compare with known data
2. Check population totals
3. Verify spatial patterns
4. Document anomalies

### Data Management
1. Back up input files
2. Save configuration
3. Archive results
4. Document process

## After Analysis

### Result Verification
1. Check total population
2. Verify spatial distribution
3. Compare with input data
4. Document any issues

### Output Management
1. Organize results
2. Create backups
3. Document settings used
4. Save log files

<div align="right">
  <a href="#top">↑ Back to Top</a>
</div>
