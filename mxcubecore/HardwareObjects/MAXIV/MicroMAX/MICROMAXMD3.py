import logging

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.GenericDiffractometer import GenericDiffractometer
from mxcubecore.HardwareObjects.MAXIV.MAXIVMD3 import MAXIVMD3

log = logging.getLogger("HWR")

MONITORING_INTERVAL = 0.1
DEFAULT_TASK_TIMEOUT = 200
DEFAULT_TASK_RUNNING_TIMEOUT = 2
DEFAULT_PHASE_TIMEOUT = 20
# how often we poll when checking if the beamstop has reached its 'BEAM' position
CHECK_BEAMSTOP_INTERVAL = 0.25


class BeamstopPositionException(Exception):
    """raised when Beamstop fails to reach required position"""


class MICROMAXMD3(MAXIVMD3):
    def __init__(self, name):
        super().__init__(name)

    def init(self):
        super().init()

        self.image_width = None
        self.image_height = None

        self.set_direct_beam_enabled(False)

    def set_direct_beam_enabled(self, enabled: bool):
        self.channel_dict["DirectBeamEnabled"].set_value(enabled)

    def state_changed(self, state):
        logging.getLogger("HWR").debug("State changed %s" % str(state))
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

        log.info("waiting for Beamstop to reach 'BEAM' position")

        poll_attempts = int(DEFAULT_PHASE_TIMEOUT / CHECK_BEAMSTOP_INTERVAL)
        for _ in range(poll_attempts):
            beamstop_position = self.command_dict["getBeamstopPosition"]()
            log.info(f"Beamstop position {beamstop_position}")

            if beamstop_position == "BEAM":
                log.info(f"Beamstop is now at '{beamstop_position}'")
                return

            gevent.sleep(CHECK_BEAMSTOP_INTERVAL)

        log.error("giving up waiting for Beamstop to reach 'BEAM' position")
        raise BeamstopPositionException(
            f"Beamstop not at 'BEAM' position, current position '{beamstop_position}'."
        )

    def raster_scan(
        self,
        start,
        end,
        exptime,
        vertical_range,
        horizontal_range,
        nlines,
        nframes,
        invert_direction=1,
        wait=False,
        table_pitch=1,
        fast_scan=1,
    ):
        """
           raster_scan: snake scan by default
           start, end, exptime are the parameters per line
           Note: vertical_range and horizontal_range unit is mm, a test value could be 0.1,0.1
           example, raster_scan(20, 22, 5, 0.1, 0.1, 10, 10)

        Args:
            invert_direction: ``1`` to enable passes in the reverse direction.
            table_pitch: ``1`` to use the centring table to do the pitch movements.
            fast_scan: ``1`` to use the fast raster scan if available (power PMAC).
        """
        logging.getLogger("HWR").info("[MICROMAXMD3] MD3 raster oscillation requested")
        msg = "[MICROMAXMD3] MD3 raster scan params:"
        msg += " start: %s, end: %s, exptime: %s, range: %s, nframes: %s" % (
            start,
            end,
            exptime,
            end - start,
            nframes,
        )
        logging.getLogger("HWR").info(msg)

        self.channel_dict["ScanStartAngle"].set_value(start)
        self.channel_dict["ScanExposureTime"].set_value(exptime)
        self.channel_dict["ScanRange"].set_value(end - start)
        self.channel_dict["ScanNumberOfFrames"].set_value(1)

        raster_params = "%0.5f\t%0.5f\t%i\t%i\t%i\t%i\t%i" % (
            vertical_range,
            horizontal_range,
            nlines,
            1,
            invert_direction,
            table_pitch,
            fast_scan,
        )

        raster = self.command_dict["startRasterScan"]
        logging.getLogger("HWR").info(
            "[MICROMAXMD3] MD3 raster oscillation requested, params: %s"
            % (raster_params)
        )
        logging.getLogger("HWR").info(
            "[MICROMAXMD3] MD3 raster oscillation requested, waiting device ready"
        )

        self.wait_ready(200)
        logging.getLogger("HWR").info(
            "[MICROMAXMD3] MD3 raster oscillation requested, device ready."
        )

        try:
            task_id = raster(raster_params)
        except Exception as ex:
            logging.getLogger("HWR").error(f"[MAXIVMD3] MD3 oscillation excetion {ex}")
        logging.getLogger("HWR").info("[MAXIVMD3] MD3 raster oscillation launched.")

        if wait:
            task_info = self.waitTaskResult(
                task_id, timeout=DEFAULT_TASK_TIMEOUT + exptime * nlines
            )
            task_output, task_exception, task_result = task_info[4:7]
            if int(task_result) <= 0:  # either failed or aborted
                raise RuntimeError(
                    "MD3 Raster Oscillation failed or aborted, output: %s | exception: %s |result: %s"
                    % (task_output, task_exception, task_result)
                )
        else:
            # we only wait until task actually started
            self.waitTaskIsRunning(task_id, timeout=DEFAULT_TASK_RUNNING_TIMEOUT)
            return

        logging.getLogger("HWR").info(
            "[MICROMAXMD3] MD3 raster oscillation finished, task result %s."
            % str(task_info)
        )

    def set_calculate_flux_phase(self):
        if self.head_type == GenericDiffractometer.HEAD_TYPE_MINIKAPPA:
            motors = [
                "phi",
                "focus",
                "phiz",
                "phiy",
                "sampx",
                "sampy",
                "kappa",
                "kappa_phi",
            ]
        else:
            motors = ["phi", "focus", "phiz", "phiy", "sampx", "sampy"]
        ori_motors = {}

        for motor in motors:
            try:
                ori_motors[motor] = self.motor_hwobj_dict[motor].get_value()
            except:
                pass
        ori_phase = self.current_phase
        if self.current_phase != "DataCollection":
            self.set_phase("DataCollection", wait=True, timeout=200)
        self.motor_hwobj_dict["phiz"].set_value(2)
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
        except Exception as ex:
            error_msg = "[MICROMAXMD3] Error while moving {} to {}, {}".format(
                motor_name, pos_name, ex
            )
            logging.getLogger("HWR").error(error_msg)
            raise

    def move_to_beam(self, x, y, omega=None):  # noqa: ARG002
        # Temporary solution to use either alignment or
        # sample table motors for 'move to beam' movements,
        # depending if we run in SSX or normal mode.
        # Once the more permanent 'SSX fixed target' mode
        # is implemented, this method should be revised
        # and removed or updated accordingly.
        #
        ssx_mode = HWR.beamline.collect.ssx_mode
        log.info(f"[MICROMAXMD3]/move_to_beam({x:.4f} {y:.4f}) ssx_mode={ssx_mode}")

        if ssx_mode:
            horizontal_axis = self.phiz_motor_hwobj
            vertical_axis = self.phiy_motor_hwobj
        else:
            horizontal_axis = self.cent_vertical_pseudo_motor
            vertical_axis = self.phiy_motor_hwobj

        try:
            self.emit_progress_message("Move to beam...")
            beam_xc, beam_yc = HWR.beamline.beam.get_beam_position()
            # the amount below is the absolute move
            y_move_rel = (y - beam_yc) / float(self.pixels_per_mm_x)
            x_move_abs = horizontal_axis.get_value() - (x - beam_xc) / float(
                self.pixels_per_mm_y
            )
            self.emit_progress_message("")

            vertical_axis.set_value_relative(y_move_rel)
            horizontal_axis.set_value(x_move_abs)
            self.wait_ready(5)
        except Exception:
            log.exception("MD3: could not move to beam.")

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

        logging.getLogger("HWR").info("[MICROMAXMD3] fast shutter is already closed")
