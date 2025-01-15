# -*- coding: utf-8 -*-
"""
/***************************************************************************
 PyPopRF
                                 A QGIS plugin
 A plugin for population prediction and dasymetric mapping using machine learning
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2025-01-07
        copyright            : (C) 2025 by WorldPop SDI Team
        email                : b.nosatiuk@soton.ac.uk
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load PyPopRF class from file PyPopRF.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    try:
        # Try importing core dependencies
        import numpy
        import pandas
        import geopandas
        import rasterio
        import sklearn
    except ImportError as e:
        # If imports fail, try installing dependencies
        from qgis.PyQt.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setText("Installing required packages...")
        msg.setInformativeText("This may take a few minutes. Please wait.")
        msg.setWindowTitle("pypopRF Plugin")
        msg.show()

        try:
            from .plugin_setup import install_dependencies
            success = install_dependencies()
            if not success:
                error_msg = QMessageBox()
                error_msg.setIcon(QMessageBox.Critical)
                error_msg.setText("Failed to install dependencies")
                error_msg.setInformativeText("Please check your internet connection and try again.")
                error_msg.setWindowTitle("PyPopRF Plugin")
                error_msg.exec_()
                raise ImportError("Failed to install required dependencies")
            msg.close()
        except Exception as setup_error:
            msg.close()
            error_msg = QMessageBox()
            error_msg.setIcon(QMessageBox.Critical)
            error_msg.setText("Error during dependency installation")
            error_msg.setInformativeText(str(setup_error))
            error_msg.setWindowTitle("pypopRF Plugin")
            error_msg.exec_()
            raise

    from .qgis_pypoprf import PyPopRF
    return PyPopRF(iface)
