import time

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.ISARA import ATTRIBUTE_POLLING, ISARA
from mxcubecore.utils.tango import add_attribute_channel

#
# Time to wait for MD3 until it's ready for mount and
# unmount operations, in seconds.
#
# We need to wait for a while, as some MD3 phase changes
# take long time.
#
MD3_READY_TIMEOUT = 200

#
# Error message shown to the user on 'empty mount' errors
#
EMPTY_MOUNT_USER_MSG = "No sample detected at requested position"

#
# Number of seconds to wait for the tool to cool down
#
WAIT_IN_SOAK_TIME = 30


def _is_empty_mount_message(message: str) -> bool:
    """Check if message indicates 'emtpy mount' error."""

    if message.startswith("ERROR 2130"):
        return True

    if message.startswith("ERROR 4130"):  # noqa: SIM103
        return True

    return False


class Isara(ISARA):
    """MicroMAX specific sample changer hardware object.

    Extends standard Isara HWO object with MicroMAX specific features.
    """

    def _create_attr_channels(self):
        super()._create_attr_channels()

        # we monitor `Message` to detect 'empty mount' errors
        add_attribute_channel(
            self,
            self.tangoname,
            "Message",
            ATTRIBUTE_POLLING,
            self._message_changed,
        )

    def _message_changed(self, message) -> None:
        self.log.debug("isara message: ==> %s", message)
        if not _is_empty_mount_message(message):
            # we only care about 'empty mount' messages
            return

        # tell the user about the 'empty mount' situation
        self.user_log.error(EMPTY_MOUNT_USER_MSG)
        self.user_log.critical(EMPTY_MOUNT_USER_MSG)

    def _maybe_move_to_soak(self):
        """Isara2 specific 'move to soak' routine.

        Extends 'move to soak' before mounting routine with Isara2
        specific behaviour.

        Compared to Isara1, Isara2 does not automatically wait in SOAK,
        until the tool is cooled. Implement this waiting here instead.
        """
        was_in_soak = self._is_in_soak_position()
        super()._maybe_move_to_soak()

        if not was_in_soak:
            #
            # If we needed to move SOAK position,
            # assume that the tool is warm.
            # Keep the tool in SOAK for a while,
            # to make sure it had time to cool down.
            #
            self.log.info(
                "Waiting %s seconds in SOAK to cool down the tool", WAIT_IN_SOAK_TIME
            )
            time.sleep(WAIT_IN_SOAK_TIME)
            self.log.info("Done with tool cooling, proceeding")

    def _prepare_sample_operation(self):
        # First we check if the diffractometer is in the ready State.
        # It is necessary, because MD3 ignores commands when not ready.
        self.log.debug("Checking if diffractometer is ready")
        HWR.beamline.diffractometer.wait_ready(MD3_READY_TIMEOUT)

        # continue with standard preporations
        super()._prepare_sample_operation()
