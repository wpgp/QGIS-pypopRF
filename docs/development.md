# Development Guide

This guide is for developers who want to understand, modify, or contribute to the QGIS pypopRF plugin. We welcome contributions and suggestions from the community!

## Project Structure

```
QGIS-pypopRF/
├── core/                    # Core functionality
│   ├── pypoprf/            # Population modeling components
├── q_models/               # QGIS-specific models
│   ├── console_handler.py  # Console output management
│   ├── config_manager.py   # Configuration handling
│   ├── covariate_table.py # Covariate UI management
│   ├── file_handlers.py   # File operations
│   ├── process_executor.py # Analysis execution
│   └── settings_handler.py # Settings management
├── qgis_pypoprf_dialog.py  # Main dialog implementation
├── qgis_pypoprf_dialog_base.ui  # Qt UI definition
├── metadata.txt           # Plugin metadata
└── __init__.py           # Plugin entry point
```

## Core Components

### 1. Main Dialog (qgis_pypoprf_dialog.py)
- Manages plugin UI lifecycle
- Connects UI signals and slots
- Coordinates between components
- Handles user interactions

### 2. Model Classes

#### Console and Logging (console_handler.py)
- Real-time console output
- Log file management
- Progress reporting
- Error handling

#### Configuration (config_manager.py)
- YAML configuration handling
- Settings validation
- Project structure management
- Default configurations

#### Data Management
- **CovariateTableHandler**: Manages covariate inputs and table UI
- **FileHandler**: Handles file operations and validation
- **ProcessExecutor**: Manages analysis execution and threading
- **SettingsHandler**: Manages plugin settings and preferences

### 3. UI Design (qgis_pypoprf_dialog_base.ui)
- Qt Designer UI definition
- Intuitive tab-based interface
- Progress monitoring
- File selection widgets
- Advanced settings panels

## Development Setup

### Requirements
```bash
# Install plugin requirements
pip install -r requirements.txt
```

### Environment Setup
1. Clone repository:
```bash
git clone https://github.com/wpgp/QGIS-pypopRF.git
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
- Follow PEP 8 conventions
- Use type hints for better code clarity
- Write comprehensive docstrings
- Keep methods focused and maintainable
- Comment complex logic sections
- Use meaningful variable names

### UI Development
- Use Qt Designer for UI modifications
- Maintain consistent tab-based organization
- Follow QGIS UI guidelines
- Consider user workflow and experience
- Ensure responsive interface

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
finally:
    # Cleanup
    self.cleanup_resources()
```

### Logging Best Practices
```python
# Use appropriate log levels
self.logger.debug("Detailed technical information")
self.logger.info("General process information")
self.logger.warning("Warning about potential issues")
self.logger.error("Error that needs attention")
```

## Threading and Performance

### Thread Management
- Use QThread for heavy processing
- Emit progress signals
- Handle cancellation properly
- Manage memory usage

```python
class ProcessWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    
    def run(self):
        try:
            # Processing steps
            self.progress.emit(50, "Processing...")
            
            # Check for cancellation
            if not self._is_running:
                return
                
        except Exception as e:
            self.finished.emit(False, str(e))
```

### Resource Management
- Implement block processing for large datasets
- Monitor memory usage
- Clean up temporary files
- Release resources properly
- Handle large input files efficiently

## Contributing

We welcome contributions from the community! Here's how you can help:

### How to Contribute
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Write/update tests
5. Submit a pull request

### What to Contribute
- Bug fixes
- New features
- Documentation improvements
- Performance enhancements
- UI/UX improvements
- Translations

### Development Process
1. Check existing issues or create a new one
2. Discuss proposed changes
3. Implement changes
4. Submit pull request
5. Respond to review comments

### Code Review Process
- All changes require review
- Follow the pull request template
- Include test cases
- Update documentation
- Maintain code quality

## Getting Help

- GitHub Issues: Report bugs and feature requests
- Discussions: Ask questions and share ideas
- Wiki: Additional documentation
- Email: Contact the development team

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

We appreciate your interest in contributing to the QGIS pypopRF plugin! Your contributions help make the tool better for everyone.