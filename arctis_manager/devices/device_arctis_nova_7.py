from typing import Optional

from arctis_manager.config_manager import ConfigManager
from arctis_manager.device_manager import (DeviceState, DeviceManager,
                                           DeviceStatus, InterfaceEndpoint)
from arctis_manager.device_manager.device_settings import (DeviceSetting,
                                                           SliderSetting)
from arctis_manager.device_manager.device_status import DeviceStatusValue

BATTERY_MAX = 0x04
HEADSET_STATUS_OFFLINE = 0x00
HEADSET_STATUS_CHARGING = 0x01

REPORT_ID_CHATMIX = 0x45
REPORT_ID_STATUS_RESPONSE = 0xb0

CMD_POLL_STATUS = 0xb0
CMD_SAVE_SETTINGS = 0x09
CMD_MIC_VOLUME = 0x37
CMD_MIC_MUTE_LED_BRIGHTNESS = 0xae
CMD_INACTIVE_TIME = 0xa3
CMD_MIC_SIDETONE = 0x39
CMD_MIC_VOLUME_LIMITER = 0x3a # 0x00 off - 0x01 on  NOT IMPLEMENTED YET

# DEFAULT SETTINGS VALUES               CHANGE IF NEEDED
DEFAULT_MIC_VOLUME = 127                # 0-127
DEFAULT_MIC_SIDE_TONE = 0               # 0-3
DEFAULT_INACTIVE_TIME = 30              # 0-90 !STEP 15!
DEFAULT_MIC_MUTE_LED_BRIGHTNESS = 3     # 0-3
DEFAULT_GAME_VOLUME = 100               # 0-100
DEFAULT_CHAT_VOLUME = 100               # 0-100

INACTIVE_TIME_MINUTES = {
    0: 0,
    1: 1,
    2: 5,
    3: 10,
    4: 15,
    5: 30,
    6: 45,
    7: 60,
    8: 75,
    9: 90
}

class ArctisNova7Device(DeviceManager):
    game_mix: int = None
    chat_mix: int = None
    game_volume: int = None
    chat_volume: int = None
    device_status: Optional[DeviceStatus] = None

    def init_device(self):
        # Detach interface responsible for Status Report
        self.kernel_detach(InterfaceEndpoint(interface=5, endpoint=0))
        # Detach interface responsible for ChatMix
        self.kernel_detach(InterfaceEndpoint(interface=7, endpoint=0))

        local_settings = self.get_local_settings()
        mic_value = min(local_settings.get('mic_volume', DEFAULT_MIC_VOLUME) // 16, 7)

        commands = [
            ([CMD_MIC_VOLUME, mic_value]),
            ([CMD_MIC_SIDETONE, local_settings.get('mic_side_tone', DEFAULT_MIC_SIDE_TONE)]),
            ([CMD_INACTIVE_TIME, local_settings.get('pm_shutdown', DEFAULT_INACTIVE_TIME)]),
            ([CMD_MIC_MUTE_LED_BRIGHTNESS, local_settings.get('mic_led_brightness', DEFAULT_MIC_MUTE_LED_BRIGHTNESS)]),
            ([CMD_SAVE_SETTINGS]),
            ([CMD_POLL_STATUS])
        ]

        for command in commands:
            self.send_command(command)

        self.device_status = DeviceStatus()

    def get_local_settings(self) -> dict[str, int]:
        self._local_config = ConfigManager.get_instance().get_config(self.get_device_vendor_id(), self.get_device_product_id()) or {
            'mic_volume': DEFAULT_MIC_VOLUME,
            'mic_side_tone': DEFAULT_MIC_SIDE_TONE,
            'mic_led_brightness': DEFAULT_MIC_MUTE_LED_BRIGHTNESS,
            'pm_shutdown': DEFAULT_INACTIVE_TIME,
            'game_volume': DEFAULT_GAME_VOLUME,
            'chat_volume': DEFAULT_CHAT_VOLUME,
        }
        self.game_volume = self._local_config.get('game_volume', DEFAULT_GAME_VOLUME)
        self.chat_volume = self._local_config.get('chat_volume', DEFAULT_CHAT_VOLUME)
        return self._local_config

    def save_local_settings(self) -> None:
        ConfigManager.get_instance().save_config(self.get_device_vendor_id(), self.get_device_product_id(), self._local_config)

    def get_device_product_id(self):
        return 0x2202

    def get_device_name(self):
        return 'Arctis Nova 7'

    def get_endpoint_addresses_to_listen(self) -> list[InterfaceEndpoint]:
        return [self.utility_guess_endpoint(7, 'in'), self.utility_guess_endpoint(5, 'in')]

    def get_request_device_status(self):
        # Disable the daemon's polling loop.
        return None, None

    def manage_input_data(self, data: list[int], endpoint: InterfaceEndpoint) -> DeviceState:
        device_status = None
        print(data)

        if endpoint == InterfaceEndpoint(7, 0):
            if data[0] == REPORT_ID_CHATMIX:
                self.game_mix = data[1] / 100
                self.chat_mix = data[2] / 100
            else:
                self.send_command([CMD_POLL_STATUS])

        elif endpoint == InterfaceEndpoint(5, 0):
            if data[0] == REPORT_ID_STATUS_RESPONSE:
                data[10] = self.get_local_settings().get('mic_led_brightness', DEFAULT_MIC_MUTE_LED_BRIGHTNESS)

                device_status = DeviceStatus(
                    headset_battery_charge=DeviceStatusValue(
                        data[2], mapped_val=lambda x: (x / BATTERY_MAX)
                    ),
                    headset_power_status=DeviceStatusValue(
                        data[3], 'connection.offline' if data[3] == HEADSET_STATUS_OFFLINE else 'connection.cable_charging' if data[3] == HEADSET_STATUS_CHARGING else 'connection.online'
                    ),
                    bluetooth_powerup_state=DeviceStatusValue(
                        data[6], 'on_off.off' if data[6] == HEADSET_STATUS_OFFLINE else 'on_off.on'
                    ),
                    mic_led_brightness=DeviceStatusValue(
                        data[10], mapped_val=lambda x: {0: 0, 1: 0.33, 2: 0.66, 3: 1}.get(x, 0)
                    )
                )
                
                if data[3] != HEADSET_STATUS_OFFLINE:
                    self.game_mix = data[4] / 100
                    self.chat_mix = data[5] / 100
            else:
                self.log.debug(f"Received a short/unknown packet: {data}")
        else:
                self.log.debug(f"Received a short/unknown packet: {data}")


        # Ensure volumes are loaded if not already
        if self.game_volume is None:
            self.game_volume = self.get_local_settings().get('game_volume', DEFAULT_GAME_VOLUME)
        if self.chat_volume is None:
            self.chat_volume = self.get_local_settings().get('chat_volume', DEFAULT_CHAT_VOLUME)

        return DeviceState(
            game_volume=self.game_volume / 100.0,
            chat_volume=self.chat_volume / 100.0,
            game_mix=self.game_mix if self.game_mix is not None else 1,
            chat_mix=self.chat_mix if self.chat_mix is not None else 1,
            device_status=device_status
        )

    def refresh_device_data(self) -> None:
        self.send_command([CMD_POLL_STATUS])

    @staticmethod
    def packet_0_filler(packet: list[int], size: int):
        return [*packet, *[0 for _ in range(size - len(packet))]]

    def get_configurable_settings(self, state: Optional[DeviceStatus] = None) -> dict[str, list[DeviceSetting]]:
        state = state or DeviceStatus()
        local_settings = self.get_local_settings()

        return {
            'microphone': [
                SliderSetting(
                    setting_key='mic_volume',
                    min_value_translation_key='mic_volume_muted',
                    max_value_translation_key='perc_100',
                    min_value=0,
                    max_value=127,
                    step=1,
                    current_state=local_settings.get('mic_volume', DEFAULT_MIC_VOLUME),
                    on_value_changed=self.on_mic_volume_change
                ),
                SliderSetting(
                    setting_key='mic_side_tone',
                    min_value_translation_key='mic_side_tone_none',
                    max_value_translation_key='mic_side_tone_high',
                    min_value=0,
                    max_value=3,
                    step=1,
                    current_state=local_settings.get('mic_side_tone', DEFAULT_MIC_SIDE_TONE),
                    on_value_changed=self.on_mic_side_tone_change
                ),
                SliderSetting(
                    setting_key='mic_led_brightness',
                    min_value_translation_key='mic_led_off',
                    max_value_translation_key='mic_led_high',
                    min_value=0,
                    max_value=3,
                    step=1,
                    current_state=local_settings.get('mic_led_brightness', DEFAULT_MIC_MUTE_LED_BRIGHTNESS),
                    on_value_changed=self.on_mic_led_brightness_change
                ),
            ],
            'power_management': [
                SliderSetting(
                    setting_key='pm_shutdown',
                    min_value_translation_key='pm_shutdown_disabled',
                    max_value_translation_key='pm_shutdown_90_minutes',
                    min_value=0,
                    max_value=9,
                    step=1,
                    current_state=local_settings.get('pm_shutdown', DEFAULT_INACTIVE_TIME),
                    on_value_changed=self.on_pm_shutdown_change
                )
            ],
            'audio': [
                SliderSetting(
                    setting_key='game_volume',
                    min_value_translation_key='volume_0_perc',
                    max_value_translation_key='volume_100_perc',
                    min_value=0,
                    max_value=100,
                    step=1,
                    current_state=local_settings.get('game_volume', DEFAULT_GAME_VOLUME),
                    on_value_changed=self.on_game_volume_change
                ),
                SliderSetting(
                    setting_key='chat_volume',
                    min_value_translation_key='volume_0_perc',
                    max_value_translation_key='volume_100_perc',
                    min_value=0,
                    max_value=100,
                    step=1,
                    current_state=local_settings.get('chat_volume', DEFAULT_CHAT_VOLUME),
                    on_value_changed=self.on_chat_volume_change
                ),
            ]
        }

    def send_command(self, command: list[int]):
        try:
            self.device.ctrl_transfer(bmRequestType=0x21, bRequest=9, wValue=0x0200, wIndex=3, data_or_wLength=self.packet_0_filler(command, 64))
            self.log.debug(f"Sent command: {command}")
        except Exception as e:
            self.log.error('Failed to send ctrl transfer.', exc_info=True)
        

    def on_mic_volume_change(self, value: int):
        # 0x00 off
        # 0x07 max
        device_value = min(value // 16, 7)
        self.send_command([CMD_MIC_VOLUME, device_value])
        self.send_command([CMD_SAVE_SETTINGS])
        self._local_config['mic_volume'] = value
        self.save_local_settings()
        self.send_command([CMD_POLL_STATUS])

    def on_mic_led_brightness_change(self, value: int):
        # 0x00 off
        # 0x03 max
        self.send_command([CMD_MIC_MUTE_LED_BRIGHTNESS, value])
        self.send_command([CMD_SAVE_SETTINGS])
        self._local_config['mic_led_brightness'] = value
        self.save_local_settings()
        self.send_command([CMD_POLL_STATUS])

    def on_mic_side_tone_change(self, value: int):
        # 0x00 off
        # 0x03 max
        self.send_command([CMD_MIC_SIDETONE, value])
        self.send_command([CMD_SAVE_SETTINGS])
        self._local_config['mic_side_tone'] = value
        self.save_local_settings()
        self.send_command([CMD_POLL_STATUS])

    def on_pm_shutdown_change(self, value: int):
        # 0-90
        # step 15
        time = INACTIVE_TIME_MINUTES[value] if value >= 0 and value <= 9 else 0
        self.send_command([CMD_INACTIVE_TIME, time])
        self.send_command([CMD_SAVE_SETTINGS])
        self._local_config['pm_shutdown'] = time
        self.save_local_settings()
        self.send_command([CMD_POLL_STATUS])

    def on_game_volume_change(self, value: int):
        self.game_volume = value
        self._local_config['game_volume'] = value
        self.save_local_settings()
        self.send_command([CMD_POLL_STATUS]) 

    def on_chat_volume_change(self, value: int):
        self.chat_volume = value
        self._local_config['chat_volume'] = value
        self.save_local_settings()
        self.send_command([CMD_POLL_STATUS])
