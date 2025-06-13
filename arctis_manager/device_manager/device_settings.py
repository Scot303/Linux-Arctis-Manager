
from abc import ABC, abstractmethod
from typing import Any, Callable

from arctis_manager.translations import Translations


class DeviceSetting(ABC):
    setting_key: str
    name: str

    def __init__(self, setting_key: str):
        self.setting_key = setting_key
        self.name = Translations.get_instance().get_translation('settings', setting_key)

    @abstractmethod
    def on_value_change(self, value: Any) -> None:
        pass


class SliderSetting(DeviceSetting):
    min_label: str
    max_label: str

    min_value: int
    max_value: int
    step: int

    current_state: int

    def __init__(
            self, setting_key, min_value_translation_key: str, max_value_translation_key: str,
            min_value: int, max_value: int, step: int,
            current_state: int, on_value_changed: Callable[[int], None]
    ):
        super().__init__(setting_key)

        self.min_label = Translations.get_instance().get_translation('setting_values', min_value_translation_key)
        self.max_label = Translations.get_instance().get_translation('setting_values', max_value_translation_key)

        self.min_value = min_value
        self.max_value = max_value
        self.step = step
        self.current_state = current_state
        self.callback = on_value_changed

    def on_value_change(self, value):
        self.callback(value)


class ToggleSetting(DeviceSetting):
    toggled_label: str
    untoggled_label: str

    current_state: bool

    def __init__(
            self, setting_key: str, toggled_translation_key: str, untoggled_translation_key: str,
            current_state: bool, on_value_toggle: Callable[[bool], None]
    ):
        super().__init__(setting_key)

        self.toggled_label = Translations.get_instance().get_translation('setting_values', toggled_translation_key)
        self.untoggled_label = Translations.get_instance().get_translation('setting_values', untoggled_translation_key)
        self.current_state = current_state
        self.callback = on_value_toggle

    def on_value_change(self, value) -> None:
        self.callback(value)
