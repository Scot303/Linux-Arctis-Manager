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

        pixmap = get_icon_pixmap()

        self.tray_icon = QSystemTrayIcon(QIcon(pixmap), parent=self.app)
        self.tray_icon.setToolTip('Arctis Manager')

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
        if hasattr(self, '_stopping') and self._stopping:
            return
        self._stopping = True

        self.log.debug('Received shutdown signal, shutting down.')
        self.app.quit()

    def on_device_status_update(self, device_manager: DeviceManager, status: DeviceStatus) -> None:
        if device_manager is None or status is None:
            return

        self.menu.clear()
        if not hasattr(self, '_menu_actions'):
            self._menu_actions = {}

        menu_sections = get_translated_menu_entries(status)
        current_device_name = device_manager.get_device_name()
        
        config_manager = ConfigManager.get_instance()
        device_specific_visibility_config = config_manager.get_device_config(
            device_name=current_device_name,
            log=self.log
        )

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
        
        self._device_manager = device_manager
        self._device_status = status

        if not '_refresh' in self._menu_actions:
            self._menu_actions['_refresh'] = QAction(Translations.get_instance().get_translation('app.refresh_button_label'))
            self._menu_actions['_refresh'].triggered.connect(self.refresh_device_data)
        # Ensure the action variable is consistently used if it was before, or stick to original direct access
        refresh_action = self._menu_actions['_refresh'] 
        refresh_action.setText(Translations.get_instance().get_translation('app.refresh_button_label'))
        self.menu.addAction(refresh_action)
        
        if len(device_manager.get_configurable_settings(status).keys()) > 0:
            if not '_settings' in self._menu_actions:
                self._menu_actions['_settings'] = QAction(Translations.get_instance().get_translation('app.settings_label'))
                self._menu_actions['_settings'].triggered.connect(self.open_settings_window)
            settings_action = self._menu_actions['_settings']
            settings_action.setText(Translations.get_instance().get_translation('app.settings_label'))
            self.menu.addAction(settings_action)

        # Menu cleanup
        expected_menu_keys = [item.dot_notation_key for item in displayed_menu_items_flatlist]
        if '_refresh' in self._menu_actions and self.menu.actions().__contains__(self._menu_actions['_refresh']):
            expected_menu_keys.append('_refresh')
        if '_settings' in self._menu_actions and self.menu.actions().__contains__(self._menu_actions['_settings']):
            expected_menu_keys.append('_settings')
        
        current_action_keys = list(self._menu_actions.keys())
        for key in current_action_keys:
            if key not in expected_menu_keys:
                if key in self._menu_actions:
                    action_to_remove = self._menu_actions.pop(key)
                    self.menu.removeAction(action_to_remove)
                    action_to_remove.deleteLater()

        # Update values in (opened) settings window
        if hasattr(self, '_settings_window'):
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
