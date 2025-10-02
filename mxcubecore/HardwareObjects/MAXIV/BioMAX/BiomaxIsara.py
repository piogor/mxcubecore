"""Isara hardware object with BioMAX specificities."""

#
# Disable 'Invalid module name' check.
#
# We can possibly make module name ruff compliant once we migrated to
# YAML config files. With YAML configs we get more flexibility with module
# names.
#
# ruff: noqa: N999
#
# Temporary disabling 'Create your own exception' check.
# We should do what the check instructs us to do.
#
# ruff: noqa: TRY002
#

import logging

import gevent

import mxcubecore.HardwareObjects.ISARA
from mxcubecore.utils.tango import add_attribute_channel

HWR_LOGGER = logging.getLogger("HWR")
USER_LOGGER = logging.getLogger("user_level_log")

CHANNEL_POLLING_PERIOD = 1000
"""Default polling period for channels, in milliseconds."""

PUCK_GRAB_MESSAGE = (
    "Warning: the puck has been pulled out of its base."
    " Please follow recovering instructions"
)


class BiomaxIsara(mxcubecore.HardwareObjects.ISARA.ISARA):
    """Isara hardware objects with BioMAX specificities."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._is_handling_md3_not_safe = False
        """Flag for the case where 'MD3 not safe' is being handled.

        This is used to prevent from retriggering the recovery procedure more than once.
        """

    def init(self) -> None:
        super().init()

        self._is_handling_md3_not_safe = False

    def _create_attr_channels(self):
        super()._create_attr_channels()

        #
        # Set-up ISARA1 specific channels
        #
        add_attribute_channel(self, self.tangoname, "PoseRX")
        add_attribute_channel(self, self.tangoname, "PoseRY")
        add_attribute_channel(self, self.tangoname, "PoseRZ")
        add_attribute_channel(self, self.tangoname, "PoseX")
        add_attribute_channel(self, self.tangoname, "PoseY")
        add_attribute_channel(self, self.tangoname, "PoseZ")
        add_attribute_channel(
            self,
            self.tangoname,
            "Message",
            CHANNEL_POLLING_PERIOD,
            self._message_changed,
        )

    def _create_tango_commands(self):
        super()._create_tango_commands()

        #
        # Set-up commands used on BioMAX only.
        #
        self._add_tango_command("Abort")
        self._add_tango_command("Back")
        self._add_tango_command("ClearMemory")
        self._add_tango_command("Dry")
        # The actual Isara command name is `safe` on Isara1 and `recover` on Isara2.
        # This discrepancy is abstracted in the Tango device server.
        self._add_tango_command("Recover")
        self._add_tango_command("Reset")

    def _message_changed(self, message) -> None:
        HWR_LOGGER.debug('[SC] Message changed: "%s"', message)
        if message:
            if message.startswith("WAIT for SafeMd condition / 9"):
                self._handle_md3_not_safe()
            elif message.startswith("WAIT for SplOn condition / "):
                self._handle_no_sample_mounted()
            elif message == PUCK_GRAB_MESSAGE:
                self._handle_puck_grab()

    def _handle_puck_grab(self) -> None:
        message = (
            "[SC][Puck grab] Puck has been pulled out of its base."
            " Follow the recovery procedure."
        )
        HWR_LOGGER.error(message)
        USER_LOGGER.error(message)

    def _is_in_mount_pose(self) -> bool:
        """Check if the sample changer robot arm is in the "mounting" pose."""

        ref_rx = self.get_property("mount_pose_rx")
        ref_ry = self.get_property("mount_pose_ry")
        ref_rz = self.get_property("mount_pose_rz")
        ref_x = self.get_property("mount_pose_x")
        ref_y = self.get_property("mount_pose_y")
        ref_z = self.get_property("mount_pose_z")
        tolerance = self.get_property("mount_pose_tolerance")

        pose_rx = self.get_channel_value("PoseRX")
        pose_ry = self.get_channel_value("PoseRY")
        pose_rz = self.get_channel_value("PoseRZ")
        pose_x = self.get_channel_value("PoseX")
        pose_y = self.get_channel_value("PoseY")
        pose_z = self.get_channel_value("PoseZ")

        is_rx = ref_rx - tolerance < pose_rx < ref_rx + tolerance
        is_ry = ref_ry - tolerance < pose_ry < ref_ry + tolerance
        is_rz = ref_rz - tolerance < pose_rz < ref_rz + tolerance
        is_x = ref_x - tolerance < pose_x < ref_x + tolerance
        is_y = ref_y - tolerance < pose_y < ref_y + tolerance
        is_z = ref_z - tolerance < pose_z < ref_z + tolerance

        is_in_mount_pose = is_rx and is_ry and is_rz and is_x and is_y and is_z

        if not is_in_mount_pose:
            # Check also against the reference mounting pose for `put` operations
            ref_rx = self.get_property("mount_put_pose_rx")
            ref_ry = self.get_property("mount_put_pose_ry")
            ref_rz = self.get_property("mount_put_pose_rz")
            ref_x = self.get_property("mount_put_pose_x")
            ref_y = self.get_property("mount_put_pose_y")
            ref_z = self.get_property("mount_put_pose_z")
            is_rx = ref_rx - tolerance < pose_rx < ref_rx + tolerance
            is_ry = ref_ry - tolerance < pose_ry < ref_ry + tolerance
            is_rz = ref_rz - tolerance < pose_rz < ref_rz + tolerance
            is_x = ref_x - tolerance < pose_x < ref_x + tolerance
            is_y = ref_y - tolerance < pose_y < ref_y + tolerance
            is_z = ref_z - tolerance < pose_z < ref_z + tolerance
            is_in_mount_pose = is_rx and is_ry and is_rz and is_x and is_y and is_z

        return is_in_mount_pose

    def _handle_md3_not_safe(self) -> None:
        """Handle case where the MD3 diffractometer is not safe (ready) quickly enough.

        The sample can not stay out of the cold for too long because it might die.
        If the MD3 is too slow to get ready we should abort the sample mount.
        This means that we put the sample that is in the gripper back into the dewar.
        """
        if not self._is_handling_md3_not_safe:
            self._is_handling_md3_not_safe = True
            HWR_LOGGER.warning(
                "[SC][MD3 not safe] Sample changer detected 'MD3 not safe' message."
                " Recovery in progress...",
            )
            error_message = (
                "[SC] Timeout when waiting MD3 to move to transfer phase,"
                " will put the sample back if applies."
            )
            HWR_LOGGER.error("[SC] Error %s", error_message)
            USER_LOGGER.error("[SC] Error %s", error_message)
            HWR_LOGGER.debug("[SC][MD3 not safe] Running command 'Abort'...")
            self.execute_command("Abort")
            gevent.sleep(0.5)
            HWR_LOGGER.debug("[SC][MD3 not safe] Running command 'Reset'...")
            self.execute_command("Reset")
            gevent.sleep(0.5)
            if self._is_in_mount_pose():
                HWR_LOGGER.info(
                    "[SC] Sample changer is stopped in the normal mount/check position"
                    " after detecting 'MD3 not safe'.",
                )
                HWR_LOGGER.debug("[SC][MD3 not safe] Running command 'Back'...")
                self.execute_command("Back")
            else:
                HWR_LOGGER.warning(
                    "[SC][MD3 not safe] Sample changer was not"
                    " in normal mount/check position",
                )
                HWR_LOGGER.debug("[SC][MD3 not safe] Running command 'Recover'...")
                self.execute_command("Recover")  # aka `safe` on Isara1
                gevent.sleep(0.5)
                HWR_LOGGER.debug("[SC][MD3 not safe] Running command 'Dry'...")
                self.execute_command("Dry")
                error_message = (
                    "SC is NOT stopped in the normal check position,"
                    " have run safe and dried the gripper."  # `safe` aka `recover`
                    " Sample in the gripper(if applies) was lost!"
                    " Sample changer is back to normal."
                )
                HWR_LOGGER.error(error_message)
                USER_LOGGER.error(error_message)
                self._is_handling_md3_not_safe = False

    def _recover_after_md3_not_safe(self) -> None:
        """Handle more recovery steps after an "MD3 not safe" case.

        Make sure the gripper does not end in a strange position after drying.
        Display message to the user on the UI.
        """
        try:
            # Here we wait twice, because there might be a small window of time
            # between the `back` and `dry` operations
            # during which the sample changer claims to be "ready".
            HWR_LOGGER.debug("[SC][MD3 not safe] Waiting for device 180s... [1/2]")
            self._wait_device_ready(180)
            gevent.sleep(1)
            HWR_LOGGER.debug("[SC][MD3 not safe] Waiting for device 180s... [2/2]")
            self._wait_device_ready(180)
            HWR_LOGGER.debug("[SC][MD3 not safe] Waited for device 180s twice.")
        except Exception as exception:
            HWR_LOGGER.warning(
                "[SC] Sample changer not ready after recovery from 'MD3 not safe': %s",
                exception,
            )
            message = self.get_channel_value("Message")

            # Disabling 'Call `startswith` once with a `tuple`' check for now.
            # We should perform the suggested refactoring in the future.
            is_drying = message.startswith(  # noqa: PIE810
                "WAIT for Dew_C condition / 31",
            ) or message.startswith("Gripper drying in progress")

            if is_drying:
                HWR_LOGGER.info(
                    "[SC] Drying after recovery from 'MD3 not safe'. Message: '%s'",
                    message,
                )
                HWR_LOGGER.info(
                    "[SC] Running recovery procedure for "
                    "drying after 'MD3 not safe'...",
                )
                HWR_LOGGER.debug("[SC][MD3 not safe] Running command 'Abort'...")
                self.execute_command("Abort")
                gevent.sleep(0.5)
                HWR_LOGGER.debug("[SC][MD3 not safe] Running command 'Reset'...")
                self.execute_command("Reset")
                gevent.sleep(0.5)
                HWR_LOGGER.debug("[SC][MD3 not safe] Running command 'Recover'...")
                self.execute_command("Recover")  # aka `safe` on Isara1
                self._wait_device_ready(20)
            else:
                error_message = (
                    f"Cannot load/unload sample and get error {exception!s}"
                    " while waiting for SC to put sample back,"
                    " please contact support."
                )
                raise Exception(error_message) from exception
        finally:
            self._is_handling_md3_not_safe = False
            HWR_LOGGER.info(
                "[SC][MD3 not safe] Recovery procedure after 'MD3 not safe' is over.",
            )

        error_message = (
            "[SC] Timeout when waiting MD3 to move to transfer phase."
            " Have put the sample back (if applies),"
            " please try to mount/unmount again when the Sample Changer is ready!"
        )
        HWR_LOGGER.error(error_message)
        raise Exception(error_message)

    def after_load_or_unload_sample(self) -> None:
        """Operations to run after loading or unloading a sample."""
        # Continue recovering procedure for "MD3 not safe" if necessary
        if self._is_handling_md3_not_safe:
            self._recover_after_md3_not_safe()

    def before_load_or_unload_sample(self) -> None:
        """Operations to run before loading or unloading a sample."""
        # Reset the flag for "MD3 not safe"
        self._is_handling_md3_not_safe = False

    def _handle_no_sample_mounted(self) -> None:
        message = "[SC][Empty mount] No sample detected on MD3."
        HWR_LOGGER.error(message)
        USER_LOGGER.error(
            "%s You might want to check visually."
            " Maybe run the beamline action called 'Empty Mount'.",
            message,
        )


# EOF
