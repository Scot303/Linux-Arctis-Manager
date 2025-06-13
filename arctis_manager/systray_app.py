import locale
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6 import QtSvg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from arctis_manager.device_manager import DeviceStatus
from arctis_manager.device_manager.device_manager import DeviceManager
from arctis_manager.i18n_helpers import get_translated_menu_entries
from arctis_manager.qt_utils import get_icon_pixmap
from arctis_manager.settings_window import SettingsWindow
from arctis_manager.translations import Translations
from arctis_manager.config_manager import ConfigManager


class SystrayApp:
    log: logging.Logger

    APP_TOOLTIP = 'Arctis Manager'
    ACTION_KEY_REFRESH = '_refresh'
    ACTION_KEY_SETTINGS = '_settings'
    TRANSLATION_KEY_REFRESH_BUTTON = 'app.refresh_button_label'
    TRANSLATION_KEY_SETTINGS_LABEL = 'app.settings_label'

    app: QApplication
    tray_icon: QSystemTrayIcon
    menu: QMenu

    def get_systray_icon_pixmap(self, path: Path) -> QPixmap:
        brush_color = QApplication.palette().color(QPalette.ColorRole.Text)

        xml_tree = ET.parse(path.absolute().as_posix())
        xml_root = xml_tree.getroot()

        xml_str = ET.tostring(xml_root)

        svg_renderer = QtSvg.QSvgRenderer(xml_str)

        # Create the empty image
        image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)

        # Initialize the painter
        painter = QPainter(image)
        painter.setBrush(brush_color)
        painter.setPen(Qt.PenStyle.NoPen)

        # Render the image on the QImage
        svg_renderer.render(painter)

        # Rendering end
        painter.end()

        pixmap = QPixmap.fromImage(image)

        return pixmap

    def __init__(self, app: QApplication, log_level: int):
        self.setup_logger(log_level)
        self.app = app
        self._stopping = False

        pixmap = get_icon_pixmap()

        self.tray_icon = QSystemTrayIcon(QIcon(pixmap), parent=self.app)
        self.tray_icon.setToolTip(self.APP_TOOLTIP)

        lang_code, _ = locale.getdefaultlocale()
        lang_code = lang_code.split('_')[0]

        self.menu = QMenu()
        self.tray_icon.setContextMenu(self.menu)

    def setup_logger(self, log_level: int):
        self.log = logging.getLogger('SystrayApp')
        self.log.setLevel(log_level)

    async def start(self):
        self.log.info('Starting Systray app.')
        self.tray_icon.show()

        self.app.exec()

    def stop(self):
        if self._stopping:
            return
        self._stopping = True

        self.log.debug('Received shutdown signal, shutting down.')
        self.app.quit()

    def _populate_menu_items(self, menu_sections: dict, device_specific_visibility_config: dict) -> list:
        displayed_menu_items_flatlist = []
        has_previous_section = False

        for section_name, section_items in menu_sections.items():
            section_visibility_rules = device_specific_visibility_config.get(section_name.dot_notation_key, {})
            items_to_add_for_this_section = []

            if section_items:
                for item_name in section_items:
                    if section_visibility_rules.get(item_name.dot_notation_key, False):
                        items_to_add_for_this_section.append(item_name)
            
            if items_to_add_for_this_section:
                if has_previous_section:
                    self.menu.addSeparator()
                has_previous_section = True

                for item_to_display in items_to_add_for_this_section:
                    action_key = item_to_display.dot_notation_key
                    if action_key not in self._menu_actions:
                        self._menu_actions[action_key] = QAction(str(item_to_display))
                        self._menu_actions[action_key].setEnabled(False)
                    else:
                        self._menu_actions[action_key].setText(str(item_to_display))
                    
                    self.menu.addAction(self._menu_actions[action_key])
                    displayed_menu_items_flatlist.append(item_to_display)
        
        if has_previous_section:
            self.menu.addSeparator()
        return displayed_menu_items_flatlist

    def _add_utility_actions(self, device_manager: DeviceManager, status: DeviceStatus):
        """Adds refresh and settings actions to the menu."""
        translations = Translations.get_instance()

        # Refresh action
        if self.ACTION_KEY_REFRESH not in self._menu_actions:
            self._menu_actions[self.ACTION_KEY_REFRESH] = QAction(translations.get_translation(self.TRANSLATION_KEY_REFRESH_BUTTON))
            self._menu_actions[self.ACTION_KEY_REFRESH].triggered.connect(self.refresh_device_data)
        
        refresh_action = self._menu_actions[self.ACTION_KEY_REFRESH]
        refresh_action.setText(translations.get_translation(self.TRANSLATION_KEY_REFRESH_BUTTON))
        self.menu.addAction(refresh_action)
        
        # Settings action (if applicable)
        if len(device_manager.get_configurable_settings(status).keys()) > 0:
            if self.ACTION_KEY_SETTINGS not in self._menu_actions:
                self._menu_actions[self.ACTION_KEY_SETTINGS] = QAction(translations.get_translation(self.TRANSLATION_KEY_SETTINGS_LABEL))
                self._menu_actions[self.ACTION_KEY_SETTINGS].triggered.connect(self.open_settings_window)
            settings_action = self._menu_actions[self.ACTION_KEY_SETTINGS]
            settings_action.setText(translations.get_translation(self.TRANSLATION_KEY_SETTINGS_LABEL))
            self.menu.addAction(settings_action)

    def _cleanup_menu_actions(self, displayed_menu_items_flatlist: list):
        """Removes unused actions from the menu and _menu_actions dictionary."""
        expected_menu_keys = [item.dot_notation_key for item in displayed_menu_items_flatlist]
        
        # Include utility action keys if they are present and in the menu
        if self.ACTION_KEY_REFRESH in self._menu_actions and self._menu_actions[self.ACTION_KEY_REFRESH] in self.menu.actions():
            expected_menu_keys.append(self.ACTION_KEY_REFRESH)
        if self.ACTION_KEY_SETTINGS in self._menu_actions and self._menu_actions[self.ACTION_KEY_SETTINGS] in self.menu.actions():
            expected_menu_keys.append(self.ACTION_KEY_SETTINGS)
        
        current_action_keys = list(self._menu_actions.keys())
        for key in current_action_keys:
            if key not in expected_menu_keys:
                if key in self._menu_actions:
                    action_to_remove = self._menu_actions.pop(key)
                    self.menu.removeAction(action_to_remove)
                    action_to_remove.deleteLater()

    def on_device_status_update(self, device_manager: DeviceManager, status: DeviceStatus) -> None:
        if device_manager is None or status is None:
            return

        self.menu.clear()
        if not hasattr(self, '_menu_actions'):
            self._menu_actions = {}

        menu_sections = get_translated_menu_entries(status)
        config_manager = ConfigManager.get_instance()
        device_specific_visibility_config = config_manager.get_device_config(
            device_name=device_manager.get_device_name(),
            log=self.log
        )

        displayed_menu_items = self._populate_menu_items(menu_sections, device_specific_visibility_config)
        
        self._device_manager = device_manager
        self._device_status = status

        self._add_utility_actions(device_manager, status)
        self._cleanup_menu_actions(displayed_menu_items)

        # Update values in (opened) settings window
        if hasattr(self, '_settings_window') and self._settings_window:
            self._settings_window.update_status(self._device_status)

    def refresh_device_data(self):
        if hasattr(self, '_device_manager') and self._device_manager:
            self.log.info("Systray: Refreshing device data...")
            try:
                self._device_manager.refresh_device_data()
            except Exception as e:
                self.log.error(f"Error calling refresh_device_data: {e}", exc_info=True)
        else:
            self.log.warning("Systray: No device manager available to refresh data.")

    def open_settings_window(self):
        if hasattr(self, '_settings_window') and self._settings_window.isVisible():
            self._settings_window.raise_()
            return

        self._settings_window = SettingsWindow(self._device_manager, self._device_status)
        self._settings_window.setWindowFlags(Qt.WindowType.Window)

        self._settings_window.show()
