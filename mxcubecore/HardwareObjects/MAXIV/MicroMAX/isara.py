from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.ISARA import ISARA

#
# Time to wait for MD3 until it's ready for mount and
# unmount operations, in seconds.
#
# We need to wait for a while, as some MD3 phase changes
# take long time.
#
MD3_READY_TIMEOUT = 200


class Isara(ISARA):
    """MicroMAX specific sample changer hardware object.

    Extends standard Isara HWO object with MicroMAX specific features.
    """

    def _prepare_sample_operation(self):
        # First we check if the diffractometer is in the ready State.
        # It is necessary, because MD3 ignores commands when not ready.
        self.log.debug("Checking if diffractometer is ready")
        HWR.beamline.diffractometer.wait_ready(MD3_READY_TIMEOUT)

        # continue with standard preporations
        super()._prepare_sample_operation()
