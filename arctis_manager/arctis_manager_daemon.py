import asyncio
import inspect
import logging
import os
from pathlib import Path
import pkgutil
import re
import subprocess
import sys
from typing import Callable

import usb.core

from arctis_manager.device_manager import DeviceManager, DeviceStatus, InterfaceEndpoint
import arctis_manager.devices

PA_GAME_NODE_NAME = 'Arctis_Game'
PA_CHAT_NODE_NAME = 'Arctis_Chat'


class ArctisManagerDaemon:
    log: logging.Logger

    device: usb.core.Device

    device_manager: DeviceManager
    device_managers: list[DeviceManager]

    previous_sink: str

    device_status_callbacks: list[Callable[[DeviceManager, DeviceStatus], None]]
    shutdown_callbacks: list[Callable[[], None]]

    _shutdown: bool
    _shutting_down: bool

    def __init__(self, log_level: int = logging.INFO):
        self.setup_logger(log_level)

        self.device = None

        self.device_manager = None
        self.device_managers = []

        self.device_status_callbacks = []
        self.shutdown_callbacks = []

        self._shutdown = False
        self._shutting_down = False

    def setup_logger(self, log_level: int):
        self.log = logging.getLogger('Daemon')
        self.log.setLevel(log_level)

    def load_device_managers(self):
        registered_devices = []

        # Dynamically instantiate the device managers
        for _, name, _ in pkgutil.iter_modules(arctis_manager.devices.__path__):
            module = __import__(f'arctis_manager.devices.{name}', fromlist=[name])
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if issubclass(cls, DeviceManager) and cls is not DeviceManager:
                    device_manager = cls()
                    if device_manager.get_device_name() not in registered_devices:
                        self.register_device(cls())
                        registered_devices.append(device_manager.get_device_name())

    def register_device(self, device: DeviceManager):
        if next((
            d for d in self.device_managers
            if d.get_device_product_id() == device.get_device_product_id()
            and d.get_device_vendor_id() == device.get_device_vendor_id()
        ), None) is None:
            self.log.info(f'Registering device "{device.get_device_name()}"')
            self.device_managers.append(device)

    def cleanup_pulseaudio_nodes(self):
        # Blindly try to cleanup dirty nodes by removing the ones we're going to create
        self.log.debug('Cleaning up PulseAudio nodes.')
        try:
            os.system(f'pw-cli destroy {PA_GAME_NODE_NAME} 1>/dev/null 2>&1')
            os.system(f'pw-cli destroy {PA_CHAT_NODE_NAME} 1>/dev/null 2>&1')
        finally:
            pass

    def register_pulseaudio_nodes(self) -> None:
        self.cleanup_pulseaudio_nodes()

        default_sink = None

        self.log.debug('Getting Arctis sink.')
        try:
            pactl_short_sinks = os.popen("pactl list short sinks").readlines()
            # grab any elements from list of pactl sinks that are Arctis
            arctis = re.compile('.*[aA]rctis.*')
            arctis_sink = list(filter(arctis.match, pactl_short_sinks))[0]

            # split the arctis line on tabs (which form table given by 'pactl short sinks')
            tabs_pattern = re.compile(r'\t')
            tabs_re = re.split(tabs_pattern, arctis_sink)

            # skip first element of tabs_re (sink's ID which is not persistent)
            arctis_device = tabs_re[1]
            self.log.debug(f"Arctis sink identified as {arctis_device}")
            default_sink = arctis_device
        except Exception as e:
            self.log.error('Failed to get default sink.', exc_info=True)
            sys.exit(102)

        # Create the game and chat nodes
        self.log.info('Creating PulseAudio Audio/Sink nodes.')
        try:
            os.system(f"""pw-cli create-node adapter '{{
                factory.name=support.null-audio-sink
                node.name=Arctis_Game
                node.description="{self.device_manager.get_device_name()} Game"
                media.class=Audio/Sink
                monitor.channel-volumes=true
                object.linger=true
                audio.position=[{' '.join([p.value for p in self.device_manager.get_audio_position()])}]
                }}' 1>/dev/null
            """)

            os.system(f"""pw-cli create-node adapter '{{
                factory.name=support.null-audio-sink
                node.name=Arctis_Chat
                node.description="{self.device_manager.get_device_name()} Chat"
                media.class=Audio/Sink
                monitor.channel-volumes=true
                object.linger=true
                audio.position=[{' '.join([p.value for p in self.device_manager.get_audio_position()])}]
                }}' 1>/dev/null
            """)
        except Exception as e:
            self.log.error('Failed to create PulseAudio nodes.', exc_info=True)
            sys.exit(103)

        self.log.info('Setting PulseAudio channel links.')
        for node in [PA_GAME_NODE_NAME, PA_CHAT_NODE_NAME]:
            try:
                for position in self.device_manager.get_audio_position():
                    pos_name = position.value
                    self.log.debug(f'Setting "{node}:monitor_{pos_name}" > "{default_sink}:playback_{pos_name}"')
                    os.system(f'pw-link "{node}:monitor_{pos_name}" "{default_sink}:playback_{pos_name}" 1>/dev/null')
            except Exception as e:
                self.log.error(f'Failed to set {node}\'s audio positions.', exc_info=True)
                sys.exit(104)

    def set_default_audio_sink(self) -> None:
        self.log.info(f'Setting PulseAudio\'s default sink to {PA_GAME_NODE_NAME}.')
        self.previous_sink = subprocess.check_output(['pactl', 'get-default-sink']).decode('utf-8').strip()
        self.set_pa_audio_sink(PA_GAME_NODE_NAME)

    def get_pa_default_sink_description(self) -> str:
        default_sink_name = subprocess.check_output(['pactl', 'get-default-sink']).decode('utf-8').strip()

        env = os.environ
        env = dict(env, **{'LANG': 'en_US'})
        pactl_list_sinks = iter(subprocess.check_output(['pactl', 'list', 'sinks'], env=env).decode('utf-8').strip().split('\n'))

        while next(pactl_list_sinks).strip() != f'Name: {default_sink_name}':
            continue

        for line in pactl_list_sinks:
            line = line.strip()
            if line.startswith('Description: '):
                return line[len('Description: '):].strip()

        return 'Unknown'

    def set_pa_audio_sink(self, sink: str) -> None:
        os.system(f'pactl set-default-sink {sink}')

        self.log.notify('Audio sink manager', f'Default audio sink set to "{self.get_pa_default_sink_description()}".')

    async def start(self, version):
        """
        Start the Arctis Manager daemon.

        This method initializes and starts the daemon service by registering
        supported devices, identifying a compatible Arctis device, initializing
        the device, and registering PulseAudio nodes. It sets the default audio
        sink and begins listening to USB endpoints for device input data. The
        method runs an asynchronous loop to manage these tasks concurrently.

        Args:
            version (str): The version of the service to be logged during startup.
        """

        self.log.info('-------------------------------')
        self.log.info('- Arctis Manager is starting. -')
        self.log.info(f'-{('v ' + version).rjust(27)}  -')
        self.log.info('-------------------------------')

        self.log.notify('Startup', 'The service is starting up.', urgency='low')

        self.log.info('Registering supported devices.')
        self.load_device_managers()

        # Identify the (first) compatible device
        self.log.debug('Identifying Arctis device.')
        for manager in self.device_managers:
            try:
                self.device = usb.core.find(idVendor=manager.get_device_vendor_id(), idProduct=manager.get_device_product_id())
                if self.device is not None:
                    self.device_manager = manager
                    # very important, otherwise the manager won't be able to communicate to the device at init stage
                    self.device_manager.set_device(self.device)
                    # Detach the kernel drivers for the interfaces we need to access in I/O (otherwise the interface will be busy and we'll not be able to read/write into them)
                    self.device_manager.kernel_detach()
                    self.log.info(f'Identified device: {self.device_manager.get_device_name()}.')
                    break
            except Exception as e:
                self.log.error(f'Failed to identify device: {manager.get_device_name()} ({e}).')
                self.device = None

        if self.device is None:
            self.log.error(f'''Failed to identify the Arctis device. Please ensure it is connected.
                           Compatible devices are: {', '.join([d.get_device_name() for d in self.device_managers])}''')

            sys.exit(101)

        self.log.debug('Initializing device.')
        for interface_endpoint in self.device_manager.get_endpoint_addresses_to_listen():
            self.device_manager.kernel_detach(interface_endpoint)
        self.device_manager.init_device()

        self.log.info('Registering PulseAudio nodes.')
        self.register_pulseaudio_nodes()

        self.set_default_audio_sink()

        async with asyncio.TaskGroup() as tg:
            for interface_endpoint in self.device_manager.get_endpoint_addresses_to_listen():
                interface = interface_endpoint.interface
                endpoint = interface_endpoint.endpoint

                self.log.info(f"Starting to listen on device's {interface:02d}.{endpoint:02d}.")
                tg.create_task(self.listen_usb_endpoint(interface_endpoint))

            tg.create_task(self.request_headset_state_loop())

            self.log.debug('Starting main loop.')

    @staticmethod
    def _normalize_audio(volume, mix):
        return int(round((volume * mix) * 100, 0))

    async def listen_usb_endpoint(self, interface_endpoint: InterfaceEndpoint) -> None:
        endpoint_addr = None
        try:
            interface_obj: usb.core.Interface = self.device[0].interfaces()[interface_endpoint.interface]
            endpoint_obj = interface_obj.endpoints()[interface_endpoint.endpoint]
            endpoint_addr = endpoint_obj.bEndpointAddress
        except Exception:
            self.log.error(f'Unable to find interface {interface_endpoint.interface} / endpoint {interface_endpoint.endpoint}.', exc_info=True)
            self.die_gracefully(error_phase="identification of USB endpoint")
            return

        while not self._shutdown:
            try:
                if endpoint_addr is None:
                    self.log.error(f"Endpoint address not initialized for interface {interface_endpoint.interface}, endpoint {interface_endpoint.endpoint}. Skipping read.")
                    await asyncio.sleep(1) # Prevent tight loop
                    continue

                read_input = await asyncio.to_thread(self.device.read, endpoint_addr, 64)
                device_state = self.device_manager.manage_input_data(read_input, interface_endpoint)

                default_device_volume = "{}%".format(self._normalize_audio(device_state.game_volume, device_state.game_mix))
                virtual_device_volume = "{}%".format(self._normalize_audio(device_state.chat_volume, device_state.chat_mix))

                os.system(f'pactl set-sink-volume Arctis_Game {default_device_volume}')
                os.system(f'pactl set-sink-volume Arctis_Chat {virtual_device_volume}')

                # Propagate the device status to any registered listener
                if device_state.device_status is not None:
                    for callback in self.device_status_callbacks:
                        callback(self.device_manager, device_state.device_status)

            except Exception as e:
                if not isinstance(e, usb.core.USBTimeoutError):
                    if isinstance(e, usb.core.USBError) and e.errno == 19:  # device not found
                        self.die_gracefully()
                    else:
                        self.log.error(f'Failed to manage input data.', exc_info=True)
                        self.die_gracefully(error_phase="USB input management")

    async def request_headset_state_loop(self) -> None:
        '''
        Send the headset status request, if configured by the device manager.
        Otherwise exit immediately and do nothing.
        It is expected to read the response from the device in the device manager's manage_input_data function.
        '''

        interface_endpoint, message = self.device_manager.get_request_device_status()
        if interface_endpoint is None or message is None:
            return

        commands_endpoint_address = self.device[0] \
            .interfaces()[interface_endpoint.interface] \
            .endpoints()[interface_endpoint.endpoint] \
            .bEndpointAddress

        self.device_manager.kernel_detach(interface_endpoint)

        while not self._shutdown:
            try:
                self.device.write(commands_endpoint_address, message)
                await asyncio.sleep(5)
            except Exception as e:
                if not isinstance(e, usb.core.USBTimeoutError):
                    if isinstance(e, usb.core.USBError) and e.errno == 19:  # device not found
                        self.die_gracefully()
                    else:
                        self.log.error(f'Failed to request device status.', exc_info=True)
                        self.die_gracefully(error_phase="USB status request")

    def register_device_change_callback(self, callback: Callable[[DeviceManager, DeviceStatus], None]) -> None:
        self.device_status_callbacks.append(callback)

    def register_shutdown_callback(self, callback: Callable[[], None]) -> None:
        self.shutdown_callbacks.append(callback)

    def stop(self):
        if hasattr(self, '_stopping') and self._stopping:
            return
        self._stopping = True

        self.log.info('Received shutdown signal, shutting down.')

        self.die_gracefully()

    def die_gracefully(self, error_phase: str = None):
        if self._shutting_down:
            return

        self._shutting_down = True
        self._die_gracefully_actuator(error_phase)

    def _die_gracefully_actuator(self, error_phase: str) -> None:
        if error_phase:
            self.log.error(f'Shutting down due to error in: {error_phase}')
            self.log.notify('Critical error', f'Shutting down due to error in: {error_phase}', urgency='critical')
        else:
            self.log.notify('Shutdown event', 'Service is shutting down.', urgency='low')

        self.log.debug('Setting shutdown flag.')
        self._shutdown = True
        self.log.info('Removing PulseAudio nodes.')
        self.cleanup_pulseaudio_nodes()

        self.log.notify('Audio sink manager', f'Default audio sink set to "{self.get_pa_default_sink_description()}".')

        self.log.info('------------------------------')
        self.log.info('- Arctis Manager is stopped. -')
        self.log.info('------------------------------')

        for callback in self.shutdown_callbacks:
            callback()
