import logging

from tango import DeviceProxy

from mxcubecore.HardwareObjects.MAXIV.MicroMAX.abstract_laser import AbstractLaser

TANGO_DEVICE = "B312A-E11/LAS/LCU01"

log = logging.getLogger("HWR")


class EksplaLaser(AbstractLaser):
    """Ekspla laser hardware object implementation.

    It uses the Ekspla Tango Device to control the laser.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._tango_device = DeviceProxy(TANGO_DEVICE)

    def arm(self) -> None:
        """Put the laser into 'running' mode

        The running laser will be emitting laser pulses,
        possibly triggered by external hardware signals.
        """
        log.info("[Ekspla] running the laser")
        self._tango_device.Run()

    def disarm(self) -> None:
        """Put laser into stopped (also called 'on') mode

        Laser in stopped mode will not emit any pulses.
        """
        log.info("[Ekspla] stopping the laser")
        self._tango_device.Stop()
