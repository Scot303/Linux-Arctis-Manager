import logging
import os
import signal
import sys
from typing import Coroutine, Literal

from arctis_manager.dbus_manager import DBusManager
from arctis_manager.translations import Translations

# Setup the notify logging
NOTIFY = 19  # Right before "INFO"
notify_enabled = os.system('which notify-send 1>/dev/null 2>&1') == 0


def logging_notify(self: logging.Logger, summary: str, message: str, urgency: Literal['low', 'normal', 'critical'] = 'normal', *args, **kwargs):
    if notify_enabled:
        args = ['--app-name="Arctis Manager"', f'--urgency={urgency}', '--expire-time=2000']
        os.system(f'notify-send {' '.join(args)} "{summary}" "{message.format(*args, **kwargs).replace('"', '\\"')}"')
    else:
        self._log(logging.INFO, f'NOTIFICATION: {summary} :: {message}', args, **kwargs)


logging.Logger.notify = logging_notify
# Notify logging end


if __name__ == '__main__':
    import asyncio
    from argparse import ArgumentParser

    from PyQt6.QtWidgets import QApplication
    from qasync import QEventLoop

    from arctis_manager.arctis_manager_daemon import ArctisManagerDaemon
    from arctis_manager.systray_app import SystrayApp

    args = ArgumentParser()
    args.add_argument('-v', '--verbose', action='count', default=0)
    args.add_argument('--daemon-only', action='store_true')
    args = args.parse_args()

    logging.basicConfig(level=logging.CRITICAL, format='%(name)20s %(levelname)8s | %(message)s')

    # Initialize the QApplication here due to the asyncio loop (the app needs to run in the main thread)
    app = QApplication(sys.argv)

    log_level = logging.DEBUG if args.verbose else NOTIFY

    daemon = ArctisManagerDaemon(log_level=log_level)
    if not args.daemon_only:
        systray_app = SystrayApp(app=app, log_level=log_level)
        dbus_manager = DBusManager(systray_app)

    # Init the translations with the logging level
    i18n = Translations.get_instance(log_level=log_level)

    def sigterm_handler(sig=None, frame=None):
        daemon.stop()
        if not args.daemon_only:
            systray_app.stop()
            dbus_manager.stop()

        i18n.debug_hit_cache()

    signal.signal(signal.SIGINT, sigterm_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)

    if not args.daemon_only:
        daemon.register_device_change_callback(systray_app.on_device_status_update)
    daemon.register_shutdown_callback(sigterm_handler)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    async def async_exception(coro: Coroutine, logger: logging.Logger = logging.getLogger('ArctisManager')):
        try:
            await coro
        except Exception as e:
            logger.critical("Unhandled exception in async task:", exc_info=True)
            sigterm_handler()

    if not args.daemon_only:
        asyncio.ensure_future(async_exception(systray_app.start(), systray_app.log))
        asyncio.ensure_future(async_exception(dbus_manager.start(), dbus_manager.log))
    asyncio.ensure_future(async_exception(daemon.start('1.6.2'), daemon.log))

    with event_loop:
        event_loop.run_forever()
