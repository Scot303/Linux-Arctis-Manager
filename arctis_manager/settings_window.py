from typing import Callable, Optional
import logging
from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QCloseEvent
from PyQt6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLayout,
                             QListWidget, QMainWindow, QSlider, QStackedWidget,
                             QVBoxLayout, QWidget, QGridLayout)

from arctis_manager.custom_widgets.q_toggle import QToggle
from arctis_manager.device_manager.device_manager import DeviceManager
from arctis_manager.device_manager.device_settings import (SliderSetting,
                                                           ToggleSetting)
from arctis_manager.device_manager.device_status import DeviceStatus
from arctis_manager.i18n_helpers import get_translated_menu_entries
from arctis_manager.qt_utils import get_icon_pixmap
from arctis_manager.translations import Translations
from arctis_manager.config_manager import ConfigManager


class SettingsWindow(QWidget):
    manager: DeviceManager

    KEY_DEVICE_STATUS = 'device_status'
    KEY_AUDIO = 'audio'
    KEY_SECTIONS = 'sections'
    KEY_SETTINGS = 'settings'
    KEY_SETTING_VALUES = 'setting_values'
    KEY_APP_SETTINGS_WINDOW_TITLE = 'app.settings_window_title'
    KEY_CURRENT_VALUE = 'current_value'

    SLIDER_QSS = """
        QSlider::groove:horizontal {
            border: 1px solid #1E1E1E;
            background: #2E2E2E;
            height: 6px;
            border-radius: 5px;
        }

        QSlider::sub-page:horizontal {
            background: #0BF;
            border: 1px solid #00A0DD;
            height: 6px;
            border-radius: 5px;
        }

        QSlider::add-page:horizontal {
            background: #4A4A4A;
            border: 1px solid #1E1E1E;
            height: 6px;
            border-radius: 5px;
        }

        QSlider::handle:horizontal {
            background: #A9A9A9;
            border: 1px solid #808080;
            width: 12px;
            height: 12px;
            margin: -5px 0;
            border-radius: 7px;
        }

        QSlider::handle:horizontal:hover {
            background: #C0C0C0;
            border: 1px solid #A9A9A9;
        }

        QSlider::handle:horizontal:pressed {
            background: #808080;
            border: 1px solid #606060;
        }
    """

    def __init__(self, manager: DeviceManager, status: DeviceStatus, parent: QWidget = None):
        super().__init__(parent=parent)

        self.manager = manager
        self.log = logging.getLogger('SettingsWindow')

        i18n = Translations.get_instance()

        self.setWindowTitle(i18n.get_translation(self.KEY_APP_SETTINGS_WINDOW_TITLE))
        # Note: Wayland does not support window icons (yet?)
        self.setWindowIcon(QIcon(get_icon_pixmap()))

        # Set the minimum size and adjust to screen geometry
        self.setMinimumSize(800, 600)
        available_geometry = self.screen().availableGeometry()
        self.resize(min(800, available_geometry.width()), min(600, available_geometry.height()))

        all_configurable_settings = manager.get_configurable_settings(status)

        section_list = QListWidget()
        self.panel_stack = QStackedWidget()

        # --- Determine the order of sections ---
        # "device_status" is always first.
        # "audio" should be second if it exists.
        # Others follow in their original relative order.
        
        ordered_section_keys = []
        ordered_section_keys.append(self.KEY_DEVICE_STATUS)

        audio_section_key = self.KEY_AUDIO
        remaining_setting_keys = list(all_configurable_settings.keys()) 

        if audio_section_key in remaining_setting_keys:
            ordered_section_keys.append(audio_section_key)
            remaining_setting_keys.remove(audio_section_key)
        
        ordered_section_keys.extend(remaining_setting_keys)

        # --- Populate section_list and panel_stack in synchronized order ---
        setting_values_translations = i18n.get_translation(self.KEY_SETTING_VALUES)
        if not isinstance(setting_values_translations, dict):
            self.log.error(f"Failed to load '{self.KEY_SETTING_VALUES}' translations as a dictionary. Got: {type(setting_values_translations)}")
            setting_values_translations = {}

        for section_key in ordered_section_keys:
            section_list.addItem(i18n.get_translation(self.KEY_SECTIONS, section_key))

            if section_key == self.KEY_DEVICE_STATUS:
                self._status_panel = QWidget()
                status_layout = QFormLayout()
                status_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
                self._status_panel.setLayout(status_layout)
                self.panel_stack.addWidget(self._status_panel)
                self.update_status(status)
            else:
                # Regular settings panel
                settings_for_panel = all_configurable_settings[section_key]
                panel = QWidget()
                layout = QFormLayout()
                layout.setAlignment(Qt.AlignmentFlag.AlignTop)
                layout.setVerticalSpacing(15)

                for setting in settings_for_panel:
                    setting_name_translated = i18n.get_translation(self.KEY_SETTINGS, setting.setting_key)
                    master_label_widget = QLabel(setting_name_translated)
                    master_label_widget.setStyleSheet("color: #FFFFFF; font-weight: bold;")
                    layout.addRow(master_label_widget)

                    actual_widget_layout: QLayout = None
                    if isinstance(setting, SliderSetting):
                        min_label_translated = setting_values_translations.get(setting.min_label, setting.min_label)
                        max_label_translated = setting_values_translations.get(setting.max_label, setting.max_label)
                        actual_widget_layout = self.get_slider_configuration_widget(
                            setting.min_value, setting.max_value, setting.step,
                            setting.current_state, min_label_translated, max_label_translated,
                            setting.on_value_change
                        )
                    elif isinstance(setting, ToggleSetting):
                        untoggled_label_translated = setting_values_translations.get(setting.untoggled_label, setting.untoggled_label)
                        toggled_label_translated = setting_values_translations.get(setting.toggled_label, setting.toggled_label)
                        actual_widget_layout = self.get_checkbox_configuration_widget(
                            untoggled_label_translated, toggled_label_translated, setting.current_state,
                            setting.on_value_change
                        )
                    
                    if actual_widget_layout is not None:
                        layout.addRow(actual_widget_layout)
                
                panel.setLayout(layout)
                self.panel_stack.addWidget(panel)
        
        section_list.setFixedWidth(max(section_list.sizeHintForColumn(0), 200))
        section_list.currentRowChanged.connect(self.change_panel)

        # Window layout
        # Main body widget
        body_widget = QWidget()
        body_layout = QHBoxLayout()
        body_layout.addWidget(section_list)
        body_layout.addWidget(self.panel_stack)
        body_widget.setLayout(body_layout)

        # Device name widget
        device_name_label = QLabel(manager.get_device_name())
        font = device_name_label.font()
        font.setBold(True)
        font.setPointSize(16)
        device_name_label.setFont(font)

        main_layout = QVBoxLayout()
        main_layout.addWidget(device_name_label)
        main_layout.addWidget(body_widget)
        self.setLayout(main_layout)

    def update_status(self, status: DeviceStatus):
        if not hasattr(self, '_status_panel') or self._status_panel.layout() is None:
            self.log.warning("_status_panel or its layout not found during update_status. This might be an initialization order issue.")
            return

        layout = self._status_panel.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        menu_sections = get_translated_menu_entries(status)

        config_manager = ConfigManager.get_instance()
        device_specific_visibility_config = config_manager.get_device_config(
            device_name=self.manager.get_device_name(),
            log=self.log
        )
        
        has_previous_section = False

        # Iterate through all available sections for the device's current status
        for section_name, section_items in menu_sections.items():
            section_visibility_rules = device_specific_visibility_config.get(section_name.dot_notation_key, {})
            items_to_add_for_this_section = []

            if section_items:
                for item_name in section_items:
                    if section_visibility_rules.get(item_name.dot_notation_key, False):
                        items_to_add_for_this_section.append(item_name)
            
            if items_to_add_for_this_section:
                if has_previous_section:
                    # Add a little vertical space instead of a full separator for visual distinction
                    spacer_label = QLabel("") 
                    spacer_label.setFixedHeight(10)
                    layout.addWidget(spacer_label)
                has_previous_section = True
                
                section_label = QLabel(str(section_name))
                label_font = section_label.font()
                label_font.setBold(True)
                section_label.setFont(label_font)
                layout.addWidget(section_label)

                for item_to_display in items_to_add_for_this_section:
                    i18n = Translations.get_instance()
                    template_key = item_to_display.dot_notation_key
                    template_string = i18n.get_translation(template_key)

                    rendered_string = str(item_to_display)
                    
                    rich_text_content = self._create_rich_text_status(template_string, rendered_string)

                    value_label = QLabel(rich_text_content)
                    value_label.setTextFormat(Qt.TextFormat.RichText)
                    value_label.setStyleSheet("color: #FFFFFF;")
                    
                    layout.addRow('', value_label)

    def _create_rich_text_status(self, template_string: str, rendered_string: str, placeholder: str = "{status}") -> str:
        if placeholder in template_string:
            parts = template_string.split(placeholder, 1)
            prefix = parts[0]
            suffix = parts[1] if len(parts) > 1 else ""

            dynamic_value = rendered_string
            if rendered_string.startswith(prefix):
                dynamic_value = dynamic_value[len(prefix):]
            if suffix and rendered_string.endswith(suffix):
                dynamic_value = dynamic_value[:-len(suffix)]
            
            escaped_prefix = escape(prefix)
            escaped_dynamic_value = escape(dynamic_value)
            escaped_suffix = escape(suffix)
            
            return f"{escaped_prefix}<b>{escaped_dynamic_value}</b>{escaped_suffix}"
        else:
            return escape(rendered_string)

    def change_panel(self, index):
        if self.panel_stack:
            self.panel_stack.setCurrentIndex(index)
        else:
            self.log.error("self.panel_stack (QStackedWidget) not found in change_panel.")

    def get_slider_configuration_widget(
        self, min_val: int, max_val: int, step: int, default_value: int, min_label: str, max_label: str, on_value_changed: Optional[Callable[[int], None]]
    ) -> QLayout:
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)

        controller = QSlider(orientation=Qt.Orientation.Horizontal)
        
        controller.setStyleSheet(self.SLIDER_QSS)

        controller.setMinimum(min_val)
        controller.setMaximum(max_val)
        controller.setSingleStep(step)
        controller.setValue(default_value)

        current_value_label = QLabel(str(default_value))
        current_value_label.setFixedWidth(35)
        current_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        current_value_label.setStyleSheet("color: #FFFFFF;")

        controller.valueChanged.connect(lambda value: current_value_label.setText(str(value)))

        # Use translated labels passed as arguments
        min_label_widget = QLabel(min_label)
        min_label_widget.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        max_label_widget = QLabel(max_label)
        max_label_widget.setStyleSheet("color: #FFFFFF; font-weight: bold;")

        current_value_display_widget = QWidget()
        current_value_hbox = QHBoxLayout(current_value_display_widget)
        current_value_hbox.setContentsMargins(0, 0, 0, 0)
        current_value_hbox.setSpacing(3)

        current_value_text_label = QLabel(Translations.get_instance().get_translation(self.KEY_SETTING_VALUES, self.KEY_CURRENT_VALUE) + ":")
        current_value_text_label.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        
        current_value_hbox.addWidget(current_value_text_label)
        current_value_hbox.addWidget(current_value_label)
        current_value_hbox.addStretch(1)
        current_value_hbox.insertStretch(0,1)

        # Add widgets to the grid
        grid_layout.addWidget(min_label_widget, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid_layout.addWidget(controller, 0, 1)
        grid_layout.setColumnStretch(1, 1)
        grid_layout.addWidget(max_label_widget, 0, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid_layout.addWidget(current_value_display_widget, 1, 0, 1, 3, Qt.AlignmentFlag.AlignCenter)
        
        if on_value_changed is not None:
            controller.sliderReleased.connect(lambda: on_value_changed(controller.value()))

        return grid_layout

    def get_checkbox_configuration_widget(
        self, off_label: str, on_label: str, toggled: bool, on_value_changed: Optional[Callable[[int], None]]
    ) -> QLayout:
        layout = QHBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setSpacing(10)

        controller = QToggle()
        controller.setChecked(toggled)

        off_label_widget = QLabel(off_label)
        off_label_widget.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        layout.addWidget(off_label_widget)
        
        layout.addWidget(controller)
        
        on_label_widget = QLabel(on_label)
        on_label_widget.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        layout.addWidget(on_label_widget)

        if on_value_changed is not None:
            controller.stateChanged.connect(lambda: on_value_changed(controller.isChecked()))

        return layout

    def closeEvent(self, event: Optional[QCloseEvent]):
        self.hide()
        event.ignore()
