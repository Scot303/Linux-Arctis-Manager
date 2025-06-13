from arctis_manager.device_manager import (DeviceState, DeviceManager,
                                           DeviceStatus, InterfaceEndpoint)

BATTERY_MIN = 0x00
BATTERY_MAX = 0x04


class Arctis7PlusDevice(DeviceManager):
    def get_device_product_id(self) -> int:
        return 0x220e

    def get_device_name(self) -> str:
        return 'Arctis 7+'

    def manage_input_data(self, data: list[int], endpoint: InterfaceEndpoint) -> DeviceState:
        if endpoint == self.utility_guess_endpoint(7, 'in'):
            # This probably needs some more work. Taken from original project.
            # see https://github.com/Sapd/HeadsetControl/blob/master/src/devices/steelseries_arctis_7_plus.c#L103

            return DeviceState(data[1] / 100, data[2] / 100, 1, 1, DeviceStatus())

    def get_endpoint_addresses_to_listen(self) -> list[InterfaceEndpoint]:
        return [self.utility_guess_endpoint(7, 'in')]

    def get_request_device_status(self):
        return self.utility_guess_endpoint(7, 'out'), [0x06, 0xb0]

    def refresh_device_data(self) -> None:
        # TODO: Implement actual data refresh logic if needed for Arctis 7+
        pass
