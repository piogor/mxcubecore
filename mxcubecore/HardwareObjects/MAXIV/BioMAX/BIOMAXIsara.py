"""Isara hardware object with BioMAX specificities."""

import time

import gevent

import mxcubecore.HardwareObjects.ISARA
from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractDiffractometer import (
    DiffractometerPhase,
)
from mxcubecore.utils.tango import add_attribute_channel

CHANNEL_POLLING_PERIOD = 1000
"""Default polling period for channels, in milliseconds."""

PUCK_GRAB_MESSAGE = (
    "Warning: the puck has been pulled out of its base."
    " Please follow recovering instructions"
)


class BIOMAXIsara(mxcubecore.HardwareObjects.ISARA.ISARA):
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
        self.safe_position = self.get_property("safe_position")

    def before_load_sample(self):  # noqa: C901, PLR0915
        """
        Ensure that the detector is in safe position and sample changer in SOAK
        """
        self.log.debug("Patched sample before load version.")
        # Abort any centring
        try:
            HWR.beamline.sample_view.reset_centring_for_sample_mount()
        except Exception:
            self.log.exception(
                "Problem aborting sample view centring before sample mount"
            )

        # clean up stale sample centring state before resetting the sample changer
        # and before a new auto-centring starts for the next mounted sample.
        if HWR.beamline.sample_view is not None:
            HWR.beamline.sample_view.current_centring_method = None
        if HWR.beamline.diffractometer is not None:
            HWR.beamline.diffractometer.last_centered_position = None

        # Applies reset (safe to do) always just in case the sc is in false fault
        HWR.beamline.sample_changer_maintenance.send_command("reset")

        if self.get_status() == "fault":
            msg = "Cannot operate sample changer, state is in FAULT."
            raise RuntimeError(msg)

        self.before_load_or_unload_sample()

        if HWR.beamline.diffractometer.get_transfer_mode() != "SAMPLE_CHANGER":
            msg_0 = 'MD3 sample transfer mode is not set to SAMPLE_CHANGER! \
                Please check the setting  in MD3 user preferences and also make sure \
                "Sample changer auto change phase" is checked'
            raise Exception(msg_0)  # noqa: TRY002

        if HWR.beamline.diffractometer.last_centered_position is not None:
            phiy = HWR.beamline.diffractometer.last_centered_position.get("phiy", 999)
            kappa = HWR.beamline.diffractometer.last_centered_position.get("kappa", 0)
            kappa_phi = HWR.beamline.diffractometer.last_centered_position.get(
                "kappa_phi", 0
            )
            self.log.info("The PhiY after centering is %s", phiy)
            if abs(kappa) < 0.1 and abs(kappa_phi) < 0.1 and phiy < -4.6:
                msg_1 = "Sample pin is too long and there is a risk of collision! \
                    Please remove the sample manually and \
                    run empty_sample_mounted afterwards!"
                raise RuntimeError(msg_1)

        curr_dtox_pos = HWR.beamline.detector.distance.get_value()
        if (
            HWR.beamline.detector.distance is not None
            and curr_dtox_pos < self.safe_position
        ):
            self.log.info("Moving detector to safe position before loading a sample.")
            self.user_log.info(
                "Moving detector to safe position before loading a sample."
            )
            HWR.beamline.detector.distance.wait_ready(30)

            try:
                HWR.beamline.detector.distance.set_value(self.safe_position)
                HWR.beamline.detector.distance.wait_end_of_move(30)
            except Exception as e:
                msg = (
                    "Cannot move detector, please contact support and check the key!!!"
                )
                self.log.exception(msg)
                raise Exception(msg) from e  # noqa: TRY002
            finally:
                msg = "Detector in safe position, position: {}".format(
                    HWR.beamline.detector.distance.get_value()
                )
                self.log.info(msg)
                self.user_log.info(msg)
        else:
            self.log.info("Detector already in safe position.")
            self.user_log.info("Detector already in safe position.")

        if self.is_path_running():
            timeout = 240
            self._wait_device_ready(timeout)
            if self.is_path_running():
                msg_2 = (
                    "Cannot load sample, sample changer has been moving for over {} s. \
                        Please check the device".format(timeout)
                )
                raise RuntimeError(msg_2)

        try:
            self.log.info(
                "Waiting for Diffractometer to be ready before proceeding \
                with the sample loading."
            )
            """
            The two wait_device_ready here is a temporary solution.
            It's to deal with the scenario when users change phase after
            launching sample mount. As the datacollection-> centring phase
            change in MD3 hwobj is actually a phase change followed by
            move_sync_motors and between the two commands there is a small window
            that the MD3 device is ready. So here we added two wait to make sure
            the isara doesn't run getput until after the move_sync_motor is finished.
            """
            HWR.beamline.diffractometer.wait_ready(30)
            time.sleep(2)
            HWR.beamline.diffractometer.wait_ready(30)
        except Exception as e:
            self.log.exception("Diffractometer not ready. Check diffractometer status")
            msg_3 = "Diffractometer not ready. \
                Check diffractometer status. Sample loading cancelled."
            raise RuntimeError(msg_3) from e
        else:
            self.log.info("Diffractometer ready, proceeding with the sample loading.")
            time.sleep(1)

    def sc_recovery_after_timeout(self):
        """Recover in case "MD3 not safe" was detected on sample changer."""
        self.after_load_or_unload_sample()

    def after_load_sample(self):
        """
        Move to centring after loading the sample
        """
        if not self.is_powered():
            msg = "Not proceeding with the steps after sample loading, \
                sample changer not powered"
            raise RuntimeError(msg)

        if (
            HWR.beamline.diffractometer is not None
            and HWR.beamline.diffractometer.get_phase() != DiffractometerPhase.CENTRE
        ):
            self.log.info("Changing diffractometer phase to Centring")
            self.user_log.info("Changing diffractometer phase to Centring")
            HWR.beamline.diffractometer.wait_ready(15)
            HWR.beamline.diffractometer.set_phase(DiffractometerPhase.CENTRE)
            self.log.info(
                "Diffractometer phase changed, current phase: %s",
                HWR.beamline.diffractometer.get_phase(),
            )
        else:
            self.log.info("Diffractometer already in Centring")
            self.user_log.info("Diffractometer already in Centring")

        if not HWR.beamline.diffractometer.get_channel_value("SampleIsLoaded"):
            self.log.error(
                "[SC][Empty mount] No sample detected on the goniometer, \
                please check the camera!"
            )
            msg_0 = "No sample detected on the goniometer!"
            raise Exception(msg_0)  # noqa: TRY002

    def load(self, sample, **kwargs):
        """
        Load a sample.

        Args:
            sample (tuple): sample address on the form
                            (component1, ... ,component_N-1, component_N)
            wait (boolean): True to wait for load to complete False otherwise

        Returns
            (Object): Value returned by _execute_task either a Task or result of the
                      operation
        """
        self.before_load_sample()
        result = super().load(sample, **kwargs)
        self.sc_recovery_after_timeout()
        self.after_load_sample()

        return result

    def unload(self, sample_slot=None, **kwargs):
        """
        Unload sample to location sample_slot, unloads to the same slot as it
        was loaded from if None is passed

        Args:
            sample_slot (tuple): sample address on the form
                               (component1, ... ,component_N-1, component_N)

        Returns:
            (Object): Value returned by _execute_task either a Task or result of the
                      operation
        """
        self.before_load_sample()
        super().unload(sample_slot, **kwargs)
        self.sc_recovery_after_timeout()

    def gripper_drying(self) -> bool:
        """Check if the gripper is drying."""
        # Isara1 does not implement GripperDrying
        # but it can be detected by parsing the Message attribute.
        message = self.get_channel_value("Message")
        drying_message = "WAIT for Dew_C condition / 31", "Gripper drying in progress"
        if message.startswith(drying_message):
            self.log.info("Gripper drying in progress. Message: '%s'", message)
            return True
        return False

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
        self.log.debug('[SC] Message changed: "%s"', message)
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
        self.log.error(message)
        self.user_log.error(message)

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
            self.log.warning(
                "[SC][MD3 not safe] Sample changer detected 'MD3 not safe' message."
                " Recovery in progress...",
            )
            error_message = (
                "[SC] Timeout when waiting MD3 to move to transfer phase,"
                " will put the sample back if applies."
            )
            self.log.error("[SC] Error %s", error_message)
            self.user_log.error("[SC] Error %s", error_message)
            self.log.debug("[SC][MD3 not safe] Running command 'Abort'...")
            self.execute_command("Abort")
            gevent.sleep(0.5)
            self.log.debug("[SC][MD3 not safe] Running command 'Reset'...")
            self.execute_command("Reset")
            gevent.sleep(0.5)
            if self._is_in_mount_pose():
                self.log.info(
                    "[SC] Sample changer is stopped in the normal mount/check position"
                    " after detecting 'MD3 not safe'.",
                )
                self.log.debug("[SC][MD3 not safe] Running command 'Back'...")
                self.execute_command("Back")
            else:
                self.log.warning(
                    "[SC][MD3 not safe] Sample changer was not"
                    " in normal mount/check position",
                )
                self.log.debug("[SC][MD3 not safe] Running command 'Recover'...")
                self.execute_command("Recover")  # aka `safe` on Isara1
                gevent.sleep(0.5)
                self.log.debug("[SC][MD3 not safe] Running command 'Dry'...")
                self.execute_command("Dry")
                error_message = (
                    "SC is NOT stopped in the normal check position,"
                    " have run safe and dried the gripper."  # `safe` aka `recover`
                    " Sample in the gripper(if applies) was lost!"
                    " Sample changer is back to normal."
                )
                self.log.error(error_message)
                self.user_log.error(error_message)
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
            self.log.debug("[SC][MD3 not safe] Waiting for device 180s... [1/2]")
            self._wait_device_ready(180)
            gevent.sleep(1)
            self.log.debug("[SC][MD3 not safe] Waiting for device 180s... [2/2]")
            self._wait_device_ready(180)
            self.log.debug("[SC][MD3 not safe] Waited for device 180s twice.")
        except Exception as exception:
            self.log.warning(
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
                self.log.info(
                    "[SC] Drying after recovery from 'MD3 not safe'. Message: '%s'",
                    message,
                )
                self.log.info(
                    "[SC] Running recovery procedure for "
                    "drying after 'MD3 not safe'...",
                )
                self.log.debug("[SC][MD3 not safe] Running command 'Abort'...")
                self.execute_command("Abort")
                gevent.sleep(0.5)
                self.log.debug("[SC][MD3 not safe] Running command 'Reset'...")
                self.execute_command("Reset")
                gevent.sleep(0.5)
                self.log.debug("[SC][MD3 not safe] Running command 'Recover'...")
                self.execute_command("Recover")  # aka `safe` on Isara1
                self._wait_device_ready(20)
            else:
                error_message = (
                    f"Cannot load/unload sample and get error {exception!s}"
                    " while waiting for SC to put sample back,"
                    " please contact support."
                )
                raise Exception(error_message) from exception  # noqa: TRY002
        finally:
            self._is_handling_md3_not_safe = False
            self.log.info(
                "[SC][MD3 not safe] Recovery procedure after 'MD3 not safe' is over.",
            )

        error_message = (
            "[SC] Timeout when waiting MD3 to move to transfer phase."
            " Have put the sample back (if applies),"
            " please try to mount/unmount again when the Sample Changer is ready!"
        )
        self.log.error(error_message)
        raise Exception(error_message)  # noqa: TRY002

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
        self.log.error(message)
        self.user_log.error(
            "%s You might want to check visually."
            " Maybe run the beamline action called 'Empty Mount'.",
            message,
        )
