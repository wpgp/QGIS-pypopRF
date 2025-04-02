# -*- coding: utf-8 -*-
"""
/***************************************************************************
 pypopRF
                                 A QGIS plugin
 A plugin for population prediction and dasymetric mapping using machine learning
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2025-01-07
        git sha              : $Format:%H$
        copyright            : (C) 2025 by WorldPop SDI Team
        email                : b.nosatiuk@soton.ac.uk
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import os

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .qgis_pypoprf_dialog import PyPopRFDialog


class PyPopRF:
    """QGIS Plugin Implementation for Population Modeling.

    A plugin for high-resolution population mapping using machine learning
    and dasymetric techniques. Creates detailed population distribution maps
    by combining census data with geospatial covariates.

    Attributes:
        iface: QGIS interface instance
        plugin_dir: Plugin's root directory path
        actions: List of plugin actions in QGIS interface
        menu: Plugin menu entry name
        first_start: Flag indicating first plugin start in session
    """

    def __init__(self, iface):
        """Initialize the plugin.

        Args:
            iface: QGIS interface instance for manipulating the application
        """

        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr("&QGIS pypopRF")

        # Check if plugin was started the first time in current QGIS session
        # Must be set in initGui() to survive plugin reloads
        self.first_start = None

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate("PyPopRF", message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None,
    ):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create menu entries and toolbar icons in the QGIS GUI.

        Initializes the plugin's visual components and connects them
        to their respective actions.
        """
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        self.add_action(
            icon_path,
            text=self.tr("Run Population Modeling"),
            callback=self.run,
            parent=self.iface.mainWindow(),
            status_tip=self.tr("Start population modeling process"),
        )
        self.first_start = True

    def unload(self):
        """Removes plugin components from QGIS GUI.

        Cleans up all plugin UI elements and references when plugin
        is being unloaded.
        """
        for action in self.actions:
            self.iface.removePluginMenu(self.tr("&QGIS pypopRF"), action)
            self.iface.removeToolBarIcon(action)

        # Clear references
        self.actions = []

    def run(self) -> None:
        """Run the main plugin functionality.

        Creates and shows the main plugin dialog. Dialog is created only
        once per QGIS session to improve performance.
        """
        # if self.first_start:
        #     self.first_start = False
        #     self.dlg = PyPopRFDialog(iface=self.iface)

        self.dlg = PyPopRFDialog(iface=self.iface)

        try:
            self.dlg.show()
            result = self.dlg.exec_()
            if result:
                # Handle any post-execution tasks if needed
                pass

        except Exception as e:
            # Log error and show user-friendly message
            self.iface.messageBar().pushCritical(
                "PyPopRF Error", f"An error occurred: {str(e)}"
            )
