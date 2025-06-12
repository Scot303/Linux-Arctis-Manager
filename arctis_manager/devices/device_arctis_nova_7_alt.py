from arctis_manager.device_manager.device_manager import device_manager_factory
from arctis_manager.devices.device_arctis_nova_7 import ArctisNova7Device


@device_manager_factory(0x2206, 'Arctis Nova 7 X')
class ArctisNova7X(ArctisNova7Device):
    pass

@device_manager_factory(0x2258, 'Arctis Nova 7 X_v2 ')
class ArctisNova7XV2(ArctisNova7Device):
    pass

@device_manager_factory(0x220a, 'Arctis Nova 7 P')
class ArctisNova7P(ArctisNova7Device):
    pass

@device_manager_factory(0x223a, 'Arctis Nova 7 DIABLO_IV')
class ArctisNova7DiabloIV(ArctisNova7Device):
    pass
