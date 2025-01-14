# Development Guide

This guide is for developers who want to understand, modify, or contribute to the QGIS pypopRF plugin.

## Project Structure

```
QGIS-pypopRF/
├── pypoprf/                  # Core Python package (submodule)
├── q_models/                 # QGIS-specific models
│   ├── console_handler.py    # Console output management
│   ├── config_manager.py     # Configuration handling
│   ├── covariate_table.py   # Covariate UI management
│   ├── file_handlers.py     # File operations
│   ├── process_executor.py  # Analysis execution
│   └── settings_handler.py  # Settings management
├── qgis_pypoprf_dialog.py   # Main dialog implementation
├── qgis_pypoprf_dialog_base.ui  # Qt UI definition
├── metadata.txt             # Plugin metadata
└── __init__.py             # Plugin entry point
```

## Core Components

### 1. Main Dialog (qgis_pypoprf_dialog.py)
- Manages plugin UI lifecycle
- Connects UI signals and slots
- Coordinates between components

### 2. Model Classes
- **ConsoleHandler**: Manages logging and output
- **ConfigManager**: Handles YAML configuration
- **CovariateTableHandler**: Manages covariate inputs
- **FileHandler**: Handles file operations
- **ProcessExecutor**: Manages analysis execution
- **SettingsHandler**: Handles plugin settings

### 3. UI Design (qgis_pypoprf_dialog_base.ui)
- Qt Designer UI definition
- Tab-based interface
- Progress monitoring
- File selection widgets

## Development Setup

### Requirements
```bash
# Development dependencies
pip install -r requirements-dev.txt

# Core package requirements
pip install -e pypoprf/
```

### Environment Setup
1. Clone repository:
```bash
git clone --recursive https://github.com/wpgp/QGIS-pypopRF.git
```

2. Install for development:
```bash
# Linux/macOS
ln -s /path/to/QGIS-pypopRF ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/

# Windows (PowerShell)
New-Item -ItemType SymbolicLink -Path "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\QGIS-pypopRF" -Target "path\to\QGIS-pypopRF"
```

3. Reload QGIS plugins

## Development Guidelines

### Code Style
- Follow PEP 8
- Use type hints
- Write docstrings
- Keep methods focused
- Comment complex logic

### UI Development
- Use Qt Designer for UI changes
- Maintain tab-based organization
- Follow QGIS UI guidelines
- Consider user workflow

### Error Handling
```python
try:
    # Operation
    process_data()
except Exception as e:
    # Log error
    self.logger.error(f"Operation failed: {str(e)}")
    # Inform user
    self.show_error_message("Operation failed", str(e))
```

### Logging
```python
# Use logger throughout code
self.logger.debug("Detailed information")
self.logger.info("General information")
self.logger.warning("Warning message")
self.logger.error("Error message")
```

## Threading and Performance

### ProcessWorker Class
- Handles long-running operations
- Runs in separate thread
- Emits progress signals
- Manages memory usage

Example:
```python
class ProcessWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    
    def run(self):
        try:
            # Long-running process
            self.progress.emit(50, "Processing...")
        except Exception as e:
            self.finished.emit(False, str(e))
```

### Memory Management
- Use block processing
- Monitor resource usage
- Clean temporary files
- Release resources properly

## Testing

### Running Tests
```bash
# Run all tests
pytest tests/

# Run specific test
pytest tests/test_process_executor.py
```

### Test Guidelines
- Write unit tests for models
- Test edge cases
- Mock QGIS dependencies
- Verify error handling

## Building and Deployment

### Building Plugin
```bash
# Create release zip
python build.py
```

### Release Checklist
1. Update version numbers
2. Run all tests
3. Update documentation
4. Create release notes
5. Tag release
6. Build plugin package

## Contributing

### Workflow
1. Fork repository
2. Create feature branch
3. Make changes
4. Run tests
5. Submit pull request

### Pull Request Guidelines
- Follow code style
- Include tests
- Update documentation
- Describe changes
- Reference issues

### Documentation
- Update relevant docs
- Include code examples
- Document API changes
- Update screenshots

## Plugin Integration

### QGIS Plugin System
- Plugin metadata
- Resource management
- Menu integration
- Tool button creation

### Core Package Integration
- pypopRF submodule
- Version compatibility
- API usage
- Error handling

## Debugging

### Development Tools
- QGIS Plugin Reloader
- Python Console
- Debugger setup
- Log analysis

### Common Issues
- Plugin loading failures
- UI update problems
- Thread synchronization
- Memory leaks

## Performance Optimization

### Code Optimization
- Profile critical paths
- Optimize algorithms
- Reduce memory usage
- Cache results

### UI Responsiveness
- Use background processing
- Update progress regularly
- Handle user interrupts
- Prevent UI freezing

## Security Considerations

### Data Handling
- Validate inputs
- Sanitize file paths
- Handle sensitive data
- Clean temporary files

### Error Messages
- Avoid exposing internals
- Log securely
- User-friendly messages
- Detailed debug logs

---
