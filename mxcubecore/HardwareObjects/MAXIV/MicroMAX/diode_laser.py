import logging

from mxcubecore.HardwareObjects.MAXIV.MicroMAX.abstract_laser import AbstractLaser

log = logging.getLogger("HWR")


class DiodeLaser(AbstractLaser):
    def arm(self) -> None:
        log.info("[DiodeLaser] running the laser - this a no-op")

    def disarm(self) -> None:
        log.info("[DiodeLaser] stopping the laser - this a no-op")
