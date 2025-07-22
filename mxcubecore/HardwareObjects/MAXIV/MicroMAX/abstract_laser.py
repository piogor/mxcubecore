from abc import ABC, abstractmethod
from contextlib import contextmanager

from mxcubecore.BaseHardwareObjects import HardwareObject


class AbstractLaser(ABC, HardwareObject):
    """Abstract class for laser device used by HVE time resolved experiments.

    Its subclasses should be available under ``HWR.beamline.laser``.
    """

    @abstractmethod
    def arm(self) -> None:
        """Allow the laser to emit laser pulses."""

    @abstractmethod
    def disarm(self) -> None:
        """Stop the laser from emitting laser pulses."""

    @contextmanager
    def armed(self):
        """Context manager to arm the laser for the duration of the block.

        It makes sure that the laser is disarmed, once we no longer need it to be armed.

        Example::

            with laser.armed():
                perform_some_action_with_laser()
        """
        self.arm()
        try:
            yield
        finally:
            self.disarm()
