import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractDiffractometer import (
    DiffractometerPhase,
)
from mxcubecore.HardwareObjects.GenericDiffractometer import GenericDiffractometer
from mxcubecore.HardwareObjects.MAXIV.MAXIVMD3 import MAXIVMD3, MD3TaskFailed

MONITORING_INTERVAL = 0.1
DEFAULT_TASK_TIMEOUT = 200
DEFAULT_TASK_RUNNING_TIMEOUT = 2
DEFAULT_PHASE_TIMEOUT = 20
# how often we poll when checking if the beamstop has reached its 'BEAM' position
CHECK_BEAMSTOP_INTERVAL = 0.25


class BeamstopPositionException(Exception):
    """raised when Beamstop fails to reach required position"""


class MICROMAXMD3(MAXIVMD3):
    def init(self):
        super().init()

        self.image_width = None
        self.image_height = None

        self.set_direct_beam_enabled(False)

    def set_direct_beam_enabled(self, enabled: bool):
        self.channel_dict["DirectBeamEnabled"].set_value(enabled)

    def state_changed(self, state):
        self.log.debug("State changed %s", state)
        self.current_state = state
        self.emit("valueChanged", (self.current_state))

    def check_beamstop_is_at_beam_position(self) -> None:
        """Check that the beamstop is at its ``BEAM`` position.

        Poll the beamstop position for ``DEFAULT_PHASE_TIMEOUT`` seconds until:

        - either the beamstop reaches its ``BEAM`` position,
          in that case the method returns;
        - or the time runs out and the beamstop is still not at its ``BEAM`` position,
          in that case ``BeamstopPositionException`` is raised.
        """

        self.log.info("waiting for Beamstop to reach 'BEAM' position")

        poll_attempts = int(DEFAULT_PHASE_TIMEOUT / CHECK_BEAMSTOP_INTERVAL)
        for _ in range(poll_attempts):
            beamstop_position = self.command_dict["getBeamstopPosition"]()
            self.log.info("Beamstop position '%s'", beamstop_position)

            if beamstop_position == "BEAM":
                self.log.info("Beamstop is now at '%s'", beamstop_position)
                return

            gevent.sleep(CHECK_BEAMSTOP_INTERVAL)

        self.log.error("giving up waiting for Beamstop to reach 'BEAM' position")
        raise BeamstopPositionException(
            f"Beamstop not at 'BEAM' position, current position '{beamstop_position}'."
        )

    def goto_centered_position(self):
        """Move MD3 to centered position"""
        self.wait_ready(10)

        self.command_dict["setCentringTablePosition"]("centred")
        self.command_dict["setAlignmentTablePosition"]("aligned")

    def raster_scan(
        self,
        start,
        end,
        exptime,
        vertical_range,
        horizontal_range,
        columns,
        invert_direction=1,
        wait=False,
        table_pitch=1,
        fast_scan=1,
    ):
        """Perform a raster scan.

        raster_scan: snake scan by default
        start, end, exptime are the parameters per line

        Note: vertical_range and horizontal_range unit is mm,
        a test value could be ``0.1, 0.1`` for example::

            raster_scan(20, 22, 5, 0.1, 0.1, 10, 10)

        Args:
            invert_direction: ``1`` to enable passes in the reverse direction.
            table_pitch: ``1`` to use the centring table to do the pitch movements.
            fast_scan: ``1`` to use the fast raster scan if available (power PMAC).
        """
        self.log.info("MD3 raster oscillation requested")
        msg = "MD3 raster scan params:"
        msg += " start: %s, end: %s, exptime: %s, range: %s" % (
            start,
            end,
            exptime,
            end - start,
        )
        self.log.info(msg)

        self.channel_dict["ScanStartAngle"].set_value(start)
        self.channel_dict["ScanExposureTime"].set_value(exptime)
        self.channel_dict["ScanRange"].set_value(end - start)
        self.channel_dict["ScanNumberOfFrames"].set_value(1)

        if HWR.beamline.tango_keystore.is_enabled("ssx_mode"):
            self.log.info("Setting scan range to 0.0 for ssx_mode mesh scan")
            self.channel_dict["ScanRange"].set_value(0.0)

        raster_params = "%0.5f\t%0.5f\t%i\t%i\t%i\t%i\t%i" % (
            vertical_range,
            horizontal_range,
            columns,
            1,
            invert_direction,
            table_pitch,
            fast_scan,
        )

        raster = self.command_dict["startRasterScan"]
        self.log.info("MD3 raster oscillation requested, params: %s", raster_params)
        self.log.info("MD3 raster oscillation requested, waiting device ready")

        self.wait_ready(200)
        self.log.info("MD3 raster oscillation requested, device ready.")

        try:
            task_id = raster(raster_params)
        except Exception:
            self.log.exception("error running raster command")

        self.log.info("MD3 raster oscillation launched.")

        if wait:
            task_info = self.wait_task_result(
                task_id, timeout=DEFAULT_TASK_TIMEOUT + exptime * columns
            )
            task_output, task_exception, task_result = task_info[4:7]
            if int(task_result) <= 0:  # either failed or aborted
                raise MD3TaskFailed(
                    MD3TaskFailed.RASTER_SCAN, task_output, task_exception, task_result
                )
        else:
            # we only wait until task actually started
            self.wait_task_running(task_id, timeout=DEFAULT_TASK_RUNNING_TIMEOUT)
            return

        self.log.info("MD3 raster oscillation finished, task result %s.", task_info)

    def set_calculate_flux_phase(self):
        if HWR.beamline.is_hve_sample_delivery():
            self.wait_ready(10)
            self.set_organ_pos("beamstopZ", -10)
            self.wait_ready(10)

        if self.head_type == GenericDiffractometer.HEAD_TYPE_MINIKAPPA:
            motors = [
                "omega",
                "focus",
                "phiz",
                "phiy",
                "sampx",
                "sampy",
                "kappa",
                "kappa_phi",
            ]
        else:
            motors = ["omega", "focus", "phiz", "phiy", "sampx", "sampy"]
        ori_motors = {}

        for motor in motors:
            try:
                ori_motors[motor] = self.motors_hwobj_dict[motor].get_value()
            except:
                pass
        ori_phase = self.current_phase
        if self.current_phase != DiffractometerPhase.COLLECT:
            self.set_phase(DiffractometerPhase.COLLECT, timeout=200)

        if HWR.beamline.tango_keystore.is_enabled("serialx_chip"):
            self.motors_hwobj_dict["phiy"].set_value(-20)
            self.wait_ready(10)
        else:
            self.motors_hwobj_dict["phiz"].set_value(2)
        self.wait_ready(10)
        self.set_organ_pos("beamstopZ", -10)
        self.wait_ready(10)
        return ori_motors, ori_phase

    def set_organ_pos(self, motor_name, pos_name):
        try:
            if motor_name == "beamstop":
                self.command_dict["setBeamstopPosition"](pos_name)
                self.wait_device_ready(DEFAULT_PHASE_TIMEOUT)
                return
            elif motor_name == "cameraExposure":
                name = "CameraExposure"
            else:
                name = "{}{}Position".format(motor_name[0].upper(), motor_name[1:])
            self.channel_dict[name].set_value(pos_name)
            self.wait_device_ready(DEFAULT_PHASE_TIMEOUT)
        except Exception:
            self.log.exception("Error while moving %s %s", motor_name, pos_name)
            raise

    def close_fast_shutter(self, timeout: float = 2.0) -> None:
        """Closes fast shutter.

        On MicroMAX MD3Up closing the fast shutter, while it's already closed,
        leads to some weird behaviour, so we want to avoid that.

        Args:
            timeout: Timeout for the operation, in seconds.
        """
        if self.is_fast_shutter_open():
            super().close_fast_shutter(timeout)
            return

        self.log.info("fast shutter is already closed")
