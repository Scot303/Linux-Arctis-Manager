from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Literal, Optional

import usb.core
import usb.util

from arctis_manager.device_manager.channel_position import ChannelPosition
from arctis_manager.device_manager.chat_mix_state import DeviceState
from arctis_manager.device_manager.device_settings import DeviceSetting
from arctis_manager.device_manager.device_status import DeviceStatus
from arctis_manager.device_manager.interface_endpoint import InterfaceEndpoint


def device_manager_factory(product_id: int, device_name: str) -> 'DeviceManager':
    def device_manager_decorator(cls):
        def get_product_id(self) -> int:
            return product_id

        def get_device_name(self) -> str:
            return device_name

        cls.get_device_product_id = get_product_id
        cls.get_device_name = get_device_name

        return cls

    return device_manager_decorator


class DeviceManager(ABC):
    device: usb.core.Device
    log: logging.Logger

    def __init__(self, log_level: int = logging.INFO):
        self.log = logging.getLogger('Device')
        self.log.level = log_level

    def set_device(self, device: usb.core.Device):
        '''
        Called by the daemon before init_device
        '''
        self.device = device

    def kernel_detach(self, ie: Optional[InterfaceEndpoint] = None) -> None:
        '''
        Ensure that the kernel driver is detached for all the interfaces we need to access in I/O
        '''

        if ie is not None:
            interfaces = [ie.interface]
        else:
            interfaces = list(set([ie.interface for ie in self.get_endpoint_addresses_to_listen()]))

        for interface in interfaces:
            interface = self.device[0].interfaces()[interface]
            interface_num = interface.bInterfaceNumber

            if self.device.is_kernel_driver_active(interface_num):
                self.device.detach_kernel_driver(interface_num)

    def init_device(self) -> None:
        '''
        Initialize the device. Overwrite when needed.
        '''
        pass

    def get_device_vendor_id(self) -> int:
        '''
        Get the vendor's identifier (should always be SteelSerie's)
        '''
        return 0x1038

    @abstractmethod
    def get_device_product_id(self) -> int:
        '''
        Get the product's identifier
        '''
        pass

    @abstractmethod
    def get_device_name(self) -> str:
        '''
        Get the device's friendly name (for example "Arctis Nova Pro Wireless")
        '''
        pass

    @abstractmethod
    def refresh_device_data(self) -> None:
        '''
        Refresh the device data/state.
        '''
        pass

    def get_audio_position(self) -> list[ChannelPosition]:
        '''
        Get the list of channel positions, defaulting to FL, FR.
        Override when different.
        '''
        return [ChannelPosition.FRONT_LEFT, ChannelPosition.FRONT_RIGHT]

    @abstractmethod
    def get_endpoint_addresses_to_listen(self) -> list[InterfaceEndpoint]:
        '''
        Get the list of endpoint addresses to listen.
        '''
        pass

    def get_configurable_settings(self, state: Optional[DeviceStatus] = None) -> dict[str, list[DeviceSetting]]:
        '''
        Get the list of configurable settings, split in sections.
        For example: {
            'Section1: [{ToggleSetting(...), SliderSetting(...)}, ...],
            'Section2': [...]
        }
        '''
        return {}

    def get_request_device_status(self) -> tuple[Optional[InterfaceEndpoint], Optional[list[int]]]:
        '''
        If the device supports the device status, define the interface/endpoint and the request status message here.
        It will be read by the manage_input_data function.
        '''

        return None, None

    def utility_guess_endpoint(self, interface_index: int, direction_out: Literal['out', 'in']) -> Optional[InterfaceEndpoint]:
        '''
        Guess the endpoint index based on the interface index and the direction.
        out: host-to-device
        in: device-to-host
        '''

        if getattr(self, '_endpoint_cache', None) is None:
            self._endpoint_cache = {}

        index = f'{self.get_device_product_id()}::{interface_index}::{direction_out}'
        if index in self._endpoint_cache:
            return self._endpoint_cache[index]

        if self.device is None:
            self.log.debug('Device is not initialized yet.')

            return None

        interface = self.device[0].interfaces()[interface_index]
        for endpoint_index, endpoint in enumerate(interface.endpoints()):
            if usb.util.endpoint_direction(endpoint.bEndpointAddress) == usb.util.ENDPOINT_OUT if direction_out == 'out' else usb.util.ENDPOINT_IN:
                result = InterfaceEndpoint(interface_index, endpoint_index)
                self._endpoint_cache[index] = result

                return result

        return None

    @abstractmethod
    def manage_input_data(self, data: list[int], endpoint: InterfaceEndpoint) -> DeviceState:
        '''
        Manage the data received from the device at the given endpoint, returning the new state.
        '''
        pass
