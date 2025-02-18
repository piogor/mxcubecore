"""A client to control the Ekspla Laser tango device"""

import logging

from tango import DeviceProxy

TANGO_DEVICE = "B312A-E11/LAS/LCU01"

log = logging.getLogger("HWR")


class Ekspla:
    def __init__(self):
        self._tango_device = DeviceProxy(TANGO_DEVICE)

    def run(self):
        """put the laser into 'running' mode

        The running laser will be emitting laser pulses,
        possibly triggerd by external hardware signals.
        """
        log.info("[Ekspla] running the laser")
        self._tango_device.Run()

    def stop(self):
        """put laser into stopped (also called 'on') mode

        Laser in stopped mode will not emit any pulses.
        """
        log.info("[Ekspla] stopping the laser")
        self._tango_device.Stop()
