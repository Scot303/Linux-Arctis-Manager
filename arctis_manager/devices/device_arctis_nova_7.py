import logging
from enum import IntEnum
from typing import Any, Dict, Optional

from arctis_manager.config_manager import ConfigManager
from arctis_manager.device_manager import (DeviceManager, DeviceState, InterfaceEndpoint)
from arctis_manager.device_manager.device_settings import (DeviceSetting, SliderSetting, ToggleSetting)
from arctis_manager.device_manager.device_status import (DeviceStatus, DeviceStatusValue)

class ReportId(IntEnum):
    CHATMIX = 0x45
    STATUS_RESPONSE = 0xB0

class Command(IntEnum):
    POLL_STATUS = 0xB0
    SAVE_SETTINGS = 0x09
    MIC_VOLUME = 0x37
    MIC_MUTE_LED_BRIGHTNESS = 0xAE
    INACTIVE_TIME = 0xA3
    MIC_SIDETONE = 0x39
    VOLUME_LIMITER = 0x3A

class HeadsetStatus(IntEnum):
    OFFLINE = 0x00
    CHARGING = 0x01

_DEFAULT_SETTINGS = {
    'mic_volume': 127,          # 0 - 127
    'mic_side_tone': 0,         # 0 - 3
    'mic_led_brightness': 3,    # 0 - 3
    'pm_shutdown': 30,          # Check INACTIVE_TIME_MAP for possible values
    'game_volume': 100,         # 0 - 100
    'chat_volume': 100,         # 0 - 100
    'volume_limiter': 0,        # 0 - 1
}

INACTIVE_TIME_MAP = [0, 1, 5, 10, 15, 30, 45, 60, 75, 90]
INACTIVE_TIME_REVERSE_MAP = {val: i for i, val in enumerate(INACTIVE_TIME_MAP)}
BATTERY_MAX = 4

POWER_STATUS_MAP = {
    HeadsetStatus.OFFLINE: 'connection.offline',
    HeadsetStatus.CHARGING: 'connection.cable_charging',
}

class ArctisNova7Device(DeviceManager):
    def __init__(self, log_level: int = logging.INFO):
        super().__init__(log_level)
        self.game_mix: Optional[float] = None
        self.chat_mix: Optional[float] = None
        self.game_volume: Optional[int] = None
        self.chat_volume: Optional[int] = None
        self.device_status: Optional[DeviceStatus] = None
        self._local_config: Dict[str, Any] = {}

    def get_device_product_id(self): return 0x2202

    def get_device_name(self): return 'Arctis Nova 7'

    def get_endpoint_addresses_to_listen(self) -> list[InterfaceEndpoint]:
        return [self.utility_guess_endpoint(7, 'in'), self.utility_guess_endpoint(5, 'in')]

    def _ensure_config_loaded(self):
        if self._local_config:
            return

        config_manager = ConfigManager.get_instance()
        
        self._local_config = _DEFAULT_SETTINGS.copy()
        user_config = config_manager.get_config(self.get_device_vendor_id(), self.get_device_product_id())
        if user_config:
            self._local_config.update(user_config)
            
        self.game_volume = self._local_config['game_volume']
        self.chat_volume = self._local_config['chat_volume']

    def init_device(self):
        self._ensure_config_loaded()

        self.kernel_detach(InterfaceEndpoint(interface=5, endpoint=0))
        self.kernel_detach(InterfaceEndpoint(interface=7, endpoint=0))
        
        commands = [
            [Command.MIC_VOLUME, min(self._local_config['mic_volume'] // 16, 7)],
            [Command.MIC_SIDETONE, self._local_config['mic_side_tone']],
            [Command.INACTIVE_TIME, self._local_config['pm_shutdown']],
            [Command.MIC_MUTE_LED_BRIGHTNESS, self._local_config['mic_led_brightness']],
            [Command.VOLUME_LIMITER, self._local_config['volume_limiter']],
            [Command.SAVE_SETTINGS],
            [Command.POLL_STATUS],
        ]

        for command in commands:
            self.send_command(command)

        if not self.device_status:
            self.device_status = DeviceStatus()

    def manage_input_data(self, data: list[int], endpoint: InterfaceEndpoint) -> DeviceState:
        self._ensure_config_loaded()

        if endpoint.interface == 7 and data and data[0] == ReportId.CHATMIX:
            self.game_mix = data[1] / 100
            self.chat_mix = data[2] / 100

        elif endpoint.interface == 5 and data and data[0] == ReportId.STATUS_RESPONSE:
            self.device_status = DeviceStatus(
                headset_battery_charge=DeviceStatusValue(data[2], mapped_val=lambda x: x / BATTERY_MAX),
                headset_power_status=DeviceStatusValue(data[3], POWER_STATUS_MAP.get(data[3], 'connection.online')),
                bluetooth_powerup_state=DeviceStatusValue(data[6], 'on_off.off' if data[6] == HeadsetStatus.OFFLINE else 'on_off.on'),
                mic_led_brightness=DeviceStatusValue(data[10], mapped_val=lambda x: {0: 0, 1: 0.33, 2: 0.66, 3: 1}.get(x, 0))
            )
            if data[3] != HeadsetStatus.OFFLINE:
                self.game_mix = data[4] / 100
                self.chat_mix = data[5] / 100
                
        else:
            self.log.debug(f"Received unknown packet on ep {endpoint}: {data}")
            self.send_command([Command.POLL_STATUS])


        return DeviceState(
            game_volume=self.game_volume / 100.0,
            chat_volume=self.chat_volume / 100.0,
            game_mix=self.game_mix or 1.0,
            chat_mix=self.chat_mix or 1.0,
            device_status=self.device_status,
        )

    def get_configurable_settings(self, state: Optional[DeviceStatus] = None) -> dict[str, list[DeviceSetting]]:
        self._ensure_config_loaded()

        settings_definitions = {
            'microphone': [
                ('mic_volume', 'mic_volume_muted', 'perc_100', 0, 127, self.on_mic_volume_change, 'slider'),
                ('mic_side_tone', 'mic_side_tone_none', 'mic_side_tone_high', 0, 3, self.on_mic_side_tone_change, 'slider'),
                ('mic_led_brightness', 'mic_led_off', 'mic_led_high', 0, 3, self.on_mic_led_brightness_change, 'slider'),
            ],
            'power_management': [
                ('pm_shutdown', 'pm_shutdown_disabled', 'pm_shutdown_90_minutes', 0, len(INACTIVE_TIME_MAP) - 1, self.on_pm_shutdown_change, 'slider'),
            ],
            'audio': [
                ('game_volume', 'volume_0_perc', 'volume_100_perc', 0, 100, self.on_game_volume_change, 'slider'),
                ('chat_volume', 'volume_0_perc', 'volume_100_perc', 0, 100, self.on_chat_volume_change, 'slider'),
                ('volume_limiter', 'volume_limiter_on', 'volume_limiter_off', None, None, self.on_volume_limiter_change, 'toggle'),
            ]
        }
        
        ui_settings = {}
        for category, definitions in settings_definitions.items():
            ui_settings[category] = []
            for d in definitions:
                setting_type = d[-1]
                if setting_type == 'slider':
                    ui_settings[category].append(self._create_slider_setting(*d[:-1]))
                elif setting_type == 'toggle':
                    ui_settings[category].append(self._create_toggle_setting(*d[:-1]))
        return ui_settings
    
    def _create_slider_setting(self, key, min_trans, max_trans, min_val, max_val, on_change):
        current_val = self._local_config[key]
        if key == 'pm_shutdown':
            current_val = INACTIVE_TIME_REVERSE_MAP.get(current_val, 0)
        return SliderSetting(key, min_trans, max_trans, min_val, max_val, 1, current_val, on_change)

    def _create_toggle_setting(self, key, off_trans, on_trans, _, __, on_change): # min/max_val are not used for toggles
        current_val = self._local_config[key]
        return ToggleSetting(key, off_trans, on_trans, current_val == 0x01, on_change)

    def _update_setting(self, config_key: str, config_value: Any, command: Optional[Command] = None, device_value: Any = None):
        self._ensure_config_loaded()     
        self._local_config[config_key] = config_value
        
        ConfigManager.get_instance().save_config(self.get_device_vendor_id(), self.get_device_product_id(), self._local_config)

        if command:
            value_to_send = device_value if device_value is not None else config_value
            self.send_command([command, value_to_send])
            self.send_command([Command.SAVE_SETTINGS])
        self.refresh_device_data()

    def on_mic_volume_change(self, value: int):
        device_value_for_mic = min(value // 16, 7)
        self._update_setting('mic_volume', value, Command.MIC_VOLUME, device_value_for_mic)

    def on_mic_led_brightness_change(self, value: int):
        self._update_setting('mic_led_brightness', value, Command.MIC_MUTE_LED_BRIGHTNESS)
        
    def on_mic_side_tone_change(self, value: int):
        self._update_setting('mic_side_tone', value, Command.MIC_SIDETONE)

    def on_pm_shutdown_change(self, index: int):
        time_minutes = INACTIVE_TIME_MAP[index] if 0 <= index < len(INACTIVE_TIME_MAP) else 0
        self._update_setting('pm_shutdown', time_minutes, Command.INACTIVE_TIME)
        
    def on_game_volume_change(self, value: int):
        self.game_volume = value
        self._update_setting('game_volume', value)

    def on_chat_volume_change(self, value: int):
        self.chat_volume = value
        self._update_setting('chat_volume', value)

    def on_volume_limiter_change(self, value: bool):
        setting_value = 0x01 if value else 0x00
        self._update_setting('volume_limiter', setting_value, Command.VOLUME_LIMITER)

    def send_command(self, command: list[int]):
        try:
            packet = command + [0] * (64 - len(command))
            self.device.ctrl_transfer(0x21, 9, 0x0200, 3, packet)
        except Exception as e:
            self.log.error(f'Failed to send ctrl transfer: {e}', exc_info=True)

    def refresh_device_data(self) -> None:
        self.send_command([Command.POLL_STATUS])
