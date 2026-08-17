import ast
import contextlib
import time
from enum import StrEnum

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractDiffractometer import (
    AbstractDiffractometer,
    DiffractometerHead,
    DiffractometerPhase,
)
from mxcubecore.HardwareObjects.ExporterMotor import ExporterMotor

# time we wait after issuing MD3 abort() command, to let MD3 'settle down'
WAIT_AFTER_ABORT = 5.0

MONITORING_INTERVAL = 0.1
DEFAULT_TASK_TIMEOUT = 200
DEFAULT_TASK_RUNNING_TIMEOUT = 2
ARRAY_SEPARATOR = ""
# 0x001F


class MD3TaskFailed(Exception):
    RASTER_SCAN = "Raster scan"
    OSCILLATION_SCAN = "Oscillation"
    HELICAL_SCAN = "Helical Oscillation"
    SET_PHASE = "Set Phase"

    def __init__(self, task_name: str, output: str, exception: str, result: str):
        super().__init__(
            f"MD3 {task_name} failed or aborted, output: {output} | "
            f"exception: {exception} | result: {result}"
        )


class AlignmentTablePosition(StrEnum):
    DEFAULT = "DEFAULT"
    ALIGNED = "ALIGNED"
    CLEAR_SCINTILLATOR = "CLEAR_SCINTILLATOR"
    TRANSFER = "TRANSFER"
    CLEARED = "CLEARED"
    STORED = "STORED"
    UNKNOWN = "UNKNOWN"


class MD3State:
    """
    Enumeration of diffractometer states
    """

    Created = 0
    Initializing = 1
    On = 2
    Off = 3
    Closed = 4
    Open = 5
    Ready = 6
    Busy = 7
    Moving = 8
    Standby = 9
    Running = 10
    Started = 11
    Stopped = 12
    Paused = 13
    Remote = 14
    Reset = 15
    Closing = 16
    Disable = 17
    Waiting = 18
    Positioned = 19
    Starting = 20
    Loading = 21
    Unknown = 22
    Alarm = 23
    Fault = 24
    Invalid = 25
    Offline = 26

    STATE_DESC = {
        Created: "Created",
        Initializing: "Initializing",
        On: "On",
        Off: "Off",
        Closed: "Closed",
        Open: "Open",
        Ready: "Ready",
        Busy: "Busy",
        Moving: "Moving",
        Standby: "Standby",
        Running: "Running",
        Started: "Started",
        Stopped: "Stopped",
        Paused: "Paused",
        Remote: "Remote",
        Reset: "Reset",
        Closing: "Closing",
        Disable: "Disable",
        Waiting: "Waiting",
        Positioned: " Positioned",
        Starting: "Starting",
        Loading: "Loading",
        Unknown: "Unknown",
        Alarm: "Alarm",
        Fault: "Fault",
        Invalid: "Invalid",
        Offline: "Offline",
    }

    @staticmethod
    def tostring(state):
        return MD3State.STATE_DESC.get(state, "Unknown")


class MAXIVMD3(AbstractDiffractometer):
    """Diffractometer class to control motors and functionality of MD3."""

    MOTOR_TO_EXPORTER_NAME = {
        "focus": "AlignmentX",
        "kappa": "Kappa",
        "kappa_phi": "Phi",
        "omega": "Omega",
        "phix": "AlignmentX",
        "phiy": "AlignmentY",
        "phiz": "AlignmentZ",
        "sampx": "CentringX",
        "sampy": "CentringY",
        "zoom": "Zoom",
    }

    CENTRING_METHOD_MANUAL = "Manual 3-click"
    CENTRING_METHOD_AUTO = "Computer automatic"
    CENTRING_METHOD_MOVE_TO_BEAM = "Move to beam"

    def __init__(self, name):
        super().__init__(name=name)

        # Compatibility line
        self.C3D_MODE = self.CENTRING_METHOD_AUTO
        self.MANUAL3CLICK_MODE = "Manual 3-click"
        self.last_centered_position = None

        # Channels and commands -----------------------------------------------
        self.channel_dict = {}
        self.used_channels_list = []
        self.command_dict = {}
        self.used_commands_list = []
        self.zoom_centre = {"x": 0, "y": 0}

        # other attributes
        self.pixels_per_mm_x = 1.0
        self.pixels_per_mm_y = 1.0

        self.sample_is_loaded = False

    def init(self):
        super().init()

        # initial phase is unknown, will be updated when channel updates are received
        self.current_phase = DiffractometerPhase.UNKNOWN

        # convenience attributes
        self.zoom_centre = self.get_property("zoom_centre")
        if isinstance(self.zoom_centre, str):
            self.zoom_centre = ast.literal_eval(self.zoom_centre)

        self.rex = self.get_object_by_role("rex")

        # motor attributes for convininces
        self.omega_motor_hwobj = self.motors_hwobj_dict["omega"]
        self.phix_motor_hwobj = self.motors_hwobj_dict["phix"]
        self.phiy_motor_hwobj = self.motors_hwobj_dict["phiy"]
        self.phiz_motor_hwobj = self.motors_hwobj_dict["phiz"]
        self.sample_x_motor_hwobj = self.motors_hwobj_dict["sampx"]
        self.sample_y_motor_hwobj = self.motors_hwobj_dict["sampy"]
        self.front_light = self.motors_hwobj_dict["frontlight"]
        self.back_light = self.motors_hwobj_dict["backlight"]

        # optional motor attributes
        try:
            self.beamstop_z = self.get_object_by_role("beamstop_z")
        except:
            self.beamstop_z = None
        try:
            self.kappa_motor_hwobj = self.motors_hwobj_dict["kappa"]
        except:
            self.kappa_motor_hwobj = None
        try:
            self.kappa_phi_motor_hwobj = self.motors_hwobj_dict["kappa_phi"]
        except:
            self.kappa_phi_motor_hwobj = None

        # nstate attributes for convininces
        self.zoom_motor_hwobj = self.nstate_equipment_hwobj_dict["zoom"]
        self.focus_motor_hwobj = self.nstate_equipment_hwobj_dict["focus"]
        self.back_light_switch = self.nstate_equipment_hwobj_dict["backlightswitch"]
        self.front_light_switch = self.nstate_equipment_hwobj_dict["frontlightswitch"]

        # other convenience attributes
        self.beam_info_hwobj = HWR.beamline.beam

        # Gathering and connecting to exporter channels
        self.used_channels_list = self.get_property("used_channels", [])
        if isinstance(self.used_channels_list, str):
            self.used_channels_list = ast.literal_eval(self.used_channels_list)

        for channel_name in self.used_channels_list:
            self.channel_dict[channel_name] = self.get_channel_object(channel_name)

        if "TransferMode" in self.channel_dict:
            self.connect(
                self.channel_dict["TransferMode"],
                "update",
                self.transfer_mode_changed,
            )
        if "CurrentPhase" in self.channel_dict:
            self.connect(
                self.channel_dict["CurrentPhase"],
                "update",
                self.update_phase,
            )
        if "HeadType" in self.channel_dict:
            self.connect(
                self.channel_dict["HeadType"], "update", self.head_type_changed
            )
        if "State" in self.channel_dict:
            self.connect(self.channel_dict["State"], "update", self.state_changed)
        if "CoaxCamScaleX" in self.channel_dict:
            self.connect(
                self.channel_dict["CoaxCamScaleX"],
                "update",
                self._update_pixels_per_mm_x,
            )
        if "CoaxCamScaleY" in self.channel_dict:
            self.connect(
                self.channel_dict["CoaxCamScaleY"],
                "update",
                self._update_pixels_per_mm_y,
            )

        self.sample_is_loaded = self.channel_dict["SampleIsLoaded"]
        with contextlib.suppress(Exception):
            self.connect(
                self.channel_dict["SampleIsLoaded"],
                "update",
                self.sample_is_loaded_changed,
            )

        # TODO(piogor, #378): refactor and move  # noqa: FIX002
        # FastShutterIsOpen to
        # configuration and load as the other channels above
        self.fast_shutter_channel = None
        try:
            self.fast_shutter_channel = self.add_channel(
                {"type": "exporter", "name": "FastShutterIsOpen"}, "FastShutterIsOpen"
            )
        except:
            self.log.exception("Cannot initialize diffractometer Fast Shutter")

        # Gathering exporter commands
        self.used_commands_list = self.get_property("used_commands", [])
        if isinstance(self.used_commands_list, str):
            self.used_commands_list = ast.literal_eval(self.used_commands_list)

        for command_name in self.used_commands_list:
            self.command_dict[command_name] = self.get_command_object(command_name)

        # to make it comaptible
        self.wait_device_ready = self.wait_ready
        self.wait_status_ready = self.wait_ready

    # Handling of pixels-per-millimeter
    def get_pixels_per_mm(self):
        """
        Get current pixels-per-millimeter values.

        :returns: list with two floats
        """
        return self.pixels_per_mm_x, self.pixels_per_mm_y

    def _emit_pixels_per_mm_changed(self):
        self.emit("pixelsPerMmChanged", (self.pixels_per_mm_x, self.pixels_per_mm_y))

    def _update_pixels_per_mm_x(self, coax_cam_scale_x: float, **_):
        """Update pixels-per-millimeter in X axis factor."""
        self.pixels_per_mm_x = 1.0 / coax_cam_scale_x
        self._emit_pixels_per_mm_changed()

    def _update_pixels_per_mm_y(self, coax_cam_scale_y: float, **_):
        """Update pixels-per-millimeter in Y axis factor."""
        self.pixels_per_mm_y = 1.0 / coax_cam_scale_y
        self._emit_pixels_per_mm_changed()

    ## ------------------------------- ##
    ##     GENERIC DIFFRACTOMETER      ##
    ## ------------------------------- ##

    def emit_diffractometer_moved(self, *args):
        self.emit("diffractometerMoved", ())

    def emit_progress_message(self, msg=None):
        self.emit("progressMessage", (msg,))

    # Head type management
    def sample_is_loaded_changed(self, sample_is_loaded):
        """
        Descript. :
        """
        self.sample_is_loaded = sample_is_loaded

    def head_type_changed(self, head_type):
        """
        Descript. :
        """
        self.head_type = head_type
        self.emit("minidiffHeadTypeChanged", (head_type,))

        if "SampleIsLoaded" not in str(self.used_channels_list):
            return
        with contextlib.suppress(Exception):
            self.disconnect(
                self.channel_dict["SampleIsLoaded"],
                "update",
                self.sample_is_loaded_changed,
            )

        if (
            head_type == DiffractometerHead.MINI_KAPPA
            or head_type == DiffractometerHead.SMART_MAGNET
        ):
            self.connect(
                self.channel_dict["SampleIsLoaded"],
                "update",
                self.sample_is_loaded_changed,
            )
        else:
            self.log.info(
                "Diffractometer: SmartMagnet "
                "is not available, only works for Minikappa and SmartMagnet head"
            )

    def is_head(self, head_type) -> bool:
        return self.head_type == head_type

    def is_head_minikappa(self) -> bool:
        return self.head_type == DiffractometerHead.MINI_KAPPA

    def is_head_plate(self) -> bool:
        return self.head_type == DiffractometerHead.PLATE

    ## ------------------------------- ##
    ##      TASK ID MANAGEMENT         ##
    ## ------------------------------- ##

    def wait_task_result(self, task_id=-1, timeout=DEFAULT_TASK_TIMEOUT):
        self.log.info("Waiting task result, task_id %s", task_id)
        if task_id < 0:
            self.wait_device_ready(timeout)
            info = self.get_last_task_info()
            exception = info[5]
            if (exception != "") and (exception != "null"):
                raise exception
            return info[4]
        else:
            with gevent.Timeout(
                timeout, Exception("Timeout waiting for task to finish")
            ):
                while self.is_task_running(task_id):
                    gevent.sleep(MONITORING_INTERVAL)
            return self.get_task_info(task_id)

    def wait_task_running(self, task_id=-1, timeout=DEFAULT_TASK_RUNNING_TIMEOUT):
        self.log.info("Waiting task is runnning, task_id %s", task_id)
        # removed the none task_id code
        with gevent.Timeout(timeout, Exception("Timeout waiting for task to start")):
            while not self.is_task_running(task_id):
                # make sure task is not launched due to exception
                task_info = self.get_task_info(task_id)
                task_exception, task_result = task_info[5:7]
                if (
                    task_result != "null" and int(task_result) < 0
                ):  # failed with exception
                    raise RuntimeError(
                        "MD3 Oscillation failed: exception: %s |result: %s"
                        % (task_exception, task_result)
                    )
                gevent.sleep(MONITORING_INTERVAL)
        task_info = self.get_task_info(task_id)

        self.log.info("Task is runnning, task_id, %s", task_info)
        return task_info

    def is_task_running(self, task_id):
        return self.command_dict["isTaskRunning"](task_id)

    def get_task_result(self, task_id):
        # Positive = success, Negative = failure, 0 = aborted
        result = self.command_dict["checkTaskResult"](task_id)
        return int(result)

    def get_task_info(self, task_id):
        """
        Returns an array of string containing task information
        """
        return self.command_dict["getTaskInfo"](task_id)

    def get_last_task_info(self):
        """
        Returns an array of string containing task information
        corresponding to the last task
        """
        # ['Set Transfer Phase',
        # '8',
        # '2021-05-03 14:22:23.061',
        # '2021-05-03 14:22:24.533',
        # 'true',
        # 'null',
        # '1']
        return self.channel_dict["LastTaskInfo"].get_value()

    ## ------------------------------- ##
    ##      OPERATION                  ##
    ## ------------------------------- ##

    def get_transfer_mode(self):
        """
        Returns the MD3 TRANSFER MODE config
        """
        try:
            mode = self.channel_dict["TransferMode"].get_value()
        except Exception as ex:
            self.log.exception("Cannot get MD3 transfer mode")
            raise Exception("Cannot get MD3 transfer mode %s " % ex)
        return mode

    def is_fast_shutter_open(self):
        return self.fast_shutter_channel.get_value()

    def open_fast_shutter(self, timeout=2):
        self.log.info("Opening fast shutter")
        self.fast_shutter_channel.set_value(1)
        with gevent.Timeout(
            timeout, RuntimeError("Timeout waiting for safety shutter to open")
        ):
            while not self.is_fast_shutter_open():
                gevent.sleep(0.2)

    def close_fast_shutter(self, timeout: float = 2.0) -> None:
        """Closes the fast shutter of the MD3 diffractometer.

        Args:
            timeout: Timeout for the operation, in seconds.
        """
        self.log.info("Closing fast shutter")
        self.fast_shutter_channel.set_value(0)
        with gevent.Timeout(
            timeout, RuntimeError("Timeout waiting for safety shutter to close")
        ):
            while self.is_fast_shutter_open():
                gevent.sleep(0.2)

    def set_scintillator_pos(self, value):
        """
        Set scintillator position
        """
        try:
            self.channel_dict["ScintillatorPosition"].set_value(value)
            self.wait_device_ready(30)
        except Exception:
            self.log.exception("Cannot set MD3 scintillator to %s ", value)

    def get_capillary_vertical_pos(self):
        """
        get capillary vertical position
        """
        try:
            return self.channel_dict["CapillaryVerticalPosition"].get_value()
        except Exception:
            self.log.exception("Cannot get MD3 capillary vertcial")

    def get_sample_holder_length(self):
        """
        get sample holder length
        """
        try:
            return self.channel_dict["SampleHolderLength"].get_value()
        except Exception:
            self.log.exception("Cannot get SampleHolderLength")

    def set_sample_holder_length(self, value):
        """
        set sample holder length
        """
        try:
            return self.channel_dict["SampleHolderLength"].set_value(value)
        except Exception:
            self.log.exception("Cannot set SampleHolderLength to %s", value)

    # Scans ---------------------------------------------------

    def set_scan_number_of_passes(self, value):
        self.wait_device_ready(5)
        self.channel_dict["ScanNumberOfPasses"].set_value(value)
        self.wait_device_ready(5)

    def set_scan_number_of_frames(self, value):
        self.wait_device_ready(5)
        self.channel_dict["ScanNumberOfFrames"].set_value(value)
        self.wait_device_ready(5)

    def do_oscillation_scan(self, start, end, exptime, wait=False):
        self.set_scan_number_of_frames(1)
        scan_params = "1\t%0.3f\t%0.3f\t%0.4f\t1" % (start, (end - start), exptime)
        scan = self.command_dict["startScanEx"]
        self.log.info(
            "MD3 oscillation requested, waiting device ready..., params %s", scan_params
        )
        self.wait_ready(200)
        self.log.info("MD3 oscillation requested, device ready.")

        try:
            task_id = scan(scan_params)
        except Exception:
            self.log.exception("MD3 oscillation excetion")

        self.log.info("MD3 oscillation launched, task id: %s", task_id)

        if wait:
            task_info = self.wait_task_result(
                task_id, timeout=DEFAULT_TASK_TIMEOUT + exptime
            )
            task_output, task_exception, task_result = task_info[4:7]

            if int(task_result) <= 0:  # either failed or aborted
                raise MD3TaskFailed(
                    MD3TaskFailed.OSCILLATION_SCAN,
                    task_output,
                    task_exception,
                    task_result,
                )
        else:
            # we only wait until task actually started
            self.wait_task_running(task_id, timeout=DEFAULT_TASK_RUNNING_TIMEOUT)
            return

        self.log.info("MD3 oscillation finished, task result %s.", task_info)

    def osc_scan_4d(self, start, end, exptime, helical_pos, wait=False):
        scan_params = "%0.3f\t%0.3f\t%0.4f\t" % (start, (end - start), exptime)
        scan_params += "%0.3f\t" % helical_pos["1"]["phiy"]
        scan_params += "%0.3f\t" % helical_pos["1"]["phiz"]
        scan_params += "%0.3f\t" % helical_pos["1"]["sampx"]
        scan_params += "%0.3f\t" % helical_pos["1"]["sampy"]
        scan_params += "%0.3f\t" % helical_pos["2"]["phiy"]
        scan_params += "%0.3f\t" % helical_pos["2"]["phiz"]
        scan_params += "%0.3f\t" % helical_pos["2"]["sampx"]
        scan_params += "%0.3f\t" % helical_pos["2"]["sampy"]

        self.log.info(
            "MD3 helical oscillation requested, waiting device ready..., params %s",
            scan_params,
        )
        scan = self.command_dict["startScan4DEx"]
        time.sleep(0.1)
        self.log.info("MD3 helical oscillation requested, device ready.")

        try:
            task_id = scan(scan_params)
        except Exception:
            self.log.exception("MD3 oscillation excetion")

        self.log.info("MD3 Helical oscillation launched.")

        if wait:
            task_info = self.wait_task_result(
                task_id, timeout=DEFAULT_TASK_TIMEOUT + exptime
            )
            self.log.info("MD3 helical task info %s", task_info)
            task_output, task_exception, task_result = task_info[4:7]
            if int(task_result) <= 0:  # either failed or aborted
                raise MD3TaskFailed(
                    MD3TaskFailed.HELICAL_SCAN, task_output, task_exception, task_result
                )
        else:
            # we only wait until task actually started
            self.wait_task_running(task_id, timeout=DEFAULT_TASK_RUNNING_TIMEOUT)
            return

        self.log.info("MD3 helical oscillation finished, task result %s.", task_info)

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
    ):
        """Perform a raster scan.

        raster_scan: snake scan by default
        start, end, exptime are the parameters per line

        Note: vertical_range and horizontal_range unit is mm,
        a test value could be 0.1, 0.1 for example

          ``raster_scan(20, 22, 5, 0.1, 0.1, 10, 10)``
        """
        self.log.info("MD3 raster oscillation requested")
        msg = "MD3 raster scan params:"
        msg += " start: %s, end: %s, exptime: %s, range: %s, nframes: %s" % (
            start,
            end,
            exptime,
            end - start,
            nframes,
        )
        self.log.info(msg)

        self.channel_dict["ScanStartAngle"].set_value(start)
        self.channel_dict["ScanExposureTime"].set_value(exptime)
        self.channel_dict["ScanRange"].set_value(end - start)
        self.channel_dict["ScanNumberOfFrames"].set_value(nframes)

        if HWR.beamline.tango_keystore.is_enabled("ssx_mode"):
            self.log.warning("setting scan range to 0.0 for ssx_mode mesh scan")
            self.channel_dict["ScanRange"].set_value(0.0)

        raster_params = "%0.5f\t%0.5f\t%i\t%i\t%i" % (
            vertical_range,
            horizontal_range,
            nlines,
            nframes,
            invert_direction,
        )

        raster = self.command_dict["startRasterScan"]
        self.log.info("MD3 raster oscillation requested, params: %s", raster_params)
        self.log.info("MD3 raster oscillation requested, waiting device ready")

        self.wait_device_ready(200)
        self.log.info("MD3 raster oscillation requested, device ready.")

        try:
            task_id = raster(raster_params)
        except Exception:
            self.log.exception("MD3 oscillation excetion")

        self.log.info("MD3 raster oscillation launched.")

        if wait:
            task_info = self.wait_task_result(
                task_id, timeout=DEFAULT_TASK_TIMEOUT + exptime * nlines
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

    # Table position management

    def get_table_position(self) -> AlignmentTablePosition:
        """Get the current MD3 AlignmentTablePosition."""
        try:
            return AlignmentTablePosition(
                self.channel_dict["AlignmentTablePosition"].get_value()
            )
        except Exception:
            self.log.exception("Cannot get MD3 table position")

    def set_table_position(self, position: AlignmentTablePosition):
        """Set the MD3 AlignmentTablePosition."""
        try:
            self.channel_dict["AlignmentTablePosition"].set_value(position.value)
            self.wait_device_ready(10)
        except Exception:
            self.log.exception("Cannot set MD3 table position to %s ", position)

    def is_table_position_in(self, position: AlignmentTablePosition) -> bool:
        """Check if the MD3 AlignmentTablePosition is in the specified position."""
        return self.get_table_position() == position

    # Phase management
    def _set_phase(self, phase: DiffractometerPhase, timeout=None):
        try:
            self.check_omega_limit()
            self.check_phiy_limit()
            # However AbstractDiffractometer sets the HardwareObjectState
            # to be "busy", it is safe to call the wait_ready() as it check
            # the state against the real MD3 hardware.
            self.wait_ready(10)
        except Exception:
            self.log.exception(
                "Cannot change phase to %s, timeout waiting for MD3 ready", phase
            )
            self.user_log.error("TIMEOUT waiting for MD3 ready")
            return

        is_clear_scintillator = self.is_table_position_in(
            AlignmentTablePosition.CLEAR_SCINTILLATOR
        )

        if HWR.beamline.is_hve_sample_delivery() or (
            not is_clear_scintillator
            and self.is_head_minikappa()
            and self.is_in_data_collection()
        ):
            self.log.info("MD3: Saving centered position")
            self.save_centring_positions()

        task_id = self.command_dict["startSetPhase"](phase.value)

        task_info = self.wait_task_result(task_id)
        task_output, task_exception, task_result = task_info[4:7]
        if int(task_result) <= 0:  # either failed or aborted
            raise MD3TaskFailed(
                MD3TaskFailed.SET_PHASE, task_output, task_exception, task_result
            )

        if self.is_head_minikappa() and phase == DiffractometerPhase.TRANSFER:
            self.log.info('save centered position after reaching "Transfer"')
            self.save_centring_positions()

        if self.is_ready():
            self.update_state(self.STATES.READY)

    def set_phase_transfer(self, timeout=None):
        self.set_phase(DiffractometerPhase.TRANSFER, timeout=timeout)

    def set_phase_centring(self, timeout=None):
        self.set_phase(DiffractometerPhase.CENTRE, timeout=timeout)

    def set_phase_data_collection(self, timeout=None):
        self.set_phase(DiffractometerPhase.COLLECT, timeout=timeout)

    def set_phase_beam_location(self, timeout=None):
        self.set_phase(DiffractometerPhase.SEE_BEAM, timeout=timeout)

    def is_in_transfer(self) -> bool:
        return self.current_phase == DiffractometerPhase.TRANSFER

    def is_in_centring(self) -> bool:
        return self.current_phase == DiffractometerPhase.CENTRE

    def is_in_data_collection(self) -> bool:
        return self.current_phase == DiffractometerPhase.COLLECT

    def is_in_beam_location(self) -> bool:
        return self.current_phase == DiffractometerPhase.SEE_BEAM

    # motors management
    def move_to_motors_positions(self, motor_positions, wait=False):
        motor_positions.pop("zoom", None)
        motor_positions.pop("focus", None)

        if not self.is_head_minikappa():
            motor_positions.pop("kappa", None)
            motor_positions.pop("kappa_phi", None)

        self.emit_progress_message("Moving to motors positions...")
        self.move_to_motors_positions_procedure = gevent.spawn(
            self.set_value_motors, motor_positions
        )
        self.move_to_motors_positions_procedure.link(self.move_motors_done)
        if wait:
            self.wait_ready(10)

    def move_motors_done(self, move_motors_procedure):
        """
        Callback method called when the move to motors positions procedure is done.

        :param move_motors_procedure: The gevent Greenlet of the move procedure.
        """
        self.move_to_motors_positions_procedure = None
        self.emit_progress_message("")

    def set_value_motors(
        self,
        motor_positions_dict: dict[str | ExporterMotor, float],
        simultaneous: bool = True,  # noqa: FBT001, to satisfy
        # AbstractDiffractometer interface
        timeout: float = 15.0,
    ):
        """Moves diffractometer motors to specified positions.

        Re-uses the `move_sync_motors` method to perform the actual move operation.
        This is caused, because the `move_motors` method is already used in the
        public part of the codebase for this purpose.

        Args:
            motor_positions_dict: dictionary mapping motors to their target positions.
                Keys can be either motor names (str) or ExporterMotor objects.
                Used motor names are the 'short' names, like 'phiy', 'phiz', etc.
                instead of exporter names like `AlignmentY`.
            timeout: timeout before the move operation is considered failed.
                Given in seconds.
        Raises:
            Timeout: if the move operation does not finish within the timeout.
            TimeoutError: if the MD3 command does not finish
                          within it's internal timeout.
        """
        # TODO(piogor, #378): check if can remove different # noqa: FIX002
        # motors movement implementation and use only Abstract one
        self.move_sync_motors(motor_positions_dict, wait=True, timeout=timeout)

    def move_sync_motors(
        self,
        motor_positions: dict[str | ExporterMotor, float],
        *,  # makes the `wait` and `timeout` arguments keyword-only
        wait: bool = True,
        timeout: float = 30.0,
    ):
        """Moves the specified motors to their target positions.

        Args:
            motor_positions: dictionary mapping motors to their target positions.
                Keys can be either motor names (str) or ExporterMotor objects.
                Used motor names are the 'short' names, like 'phiy', 'phiz'
                etc. instead of exporter names like `AlignmentY`.
            wait: If True, waits for the move to finish before returning.
            timeout: Timeout in seconds to wait for the move to finish.

        Raises:
            Timeout: if the move operation does not finish within the timeout.
            TimeoutError: if the MD3 command does not finish
                          within its internal timeout.
        """
        motor_positions.pop("zoom", None)
        motor_positions.pop("focus", None)

        if not self.is_head_minikappa():
            motor_positions.pop("kappa", None)
            motor_positions.pop("kappa_phi", None)

        argin = ""
        self.log.debug("move_sync_motors, wait: %s, motors: %s", wait, motor_positions)
        for motor, position in motor_positions.items():
            if isinstance(motor, str):
                name = self.MOTOR_TO_EXPORTER_NAME[motor]
            else:
                name = motor.actuator_name

            # GPHL workflow may set some motors to None
            # until they sort this out we need this fix
            if position is None:
                self.log.warning("Motor %s position is None", name)
                continue

            argin += "%s=%0.3f;" % (name, position)
        if not argin:
            return
        self.wait_ready(2000)
        task_id = self.command_dict["startSimultaneousMoveMotors"](argin)
        if wait:
            self.log.debug("move_sync_motors, waiting for task %s", task_id)
            self.wait_task_result(task_id, timeout=timeout)

    def check_motor_limit_range(self, motor_name, range_limit):
        limits = self.command_dict["getMotorLimits"](motor_name)
        if abs(limits[1] - limits[0]) > range_limit:
            msg = (
                f"The current limits of Motor {motor_name} is beyond {range_limit},"
                " please check motor setting in MD3"
            )
            self.user_log.error(msg)
            raise Exception(msg)

    def check_motor_limits(self, motor_name, min_value, max_value):
        limits = self.command_dict["getMotorLimits"](motor_name)
        if limits[0] < min_value or limits[1] > max_value:
            msg = (
                f"The current limits of Motor {motor_name} is {limits}, "
                f"beyond [{min_value}, {max_value}],"
                " please check motor setting in MD3"
            )
            self.user_log.error(msg)
            raise Exception(msg)

    def check_omega_limit(self):
        omega_limit = HWR.beamline.tango_keystore.get("md3_omega_limit")
        if omega_limit["max"] >= omega_limit["min"]:
            self.check_motor_limits("Omega", omega_limit["min"], omega_limit["max"])

    def check_phiy_limit(self):
        phiy_limit = HWR.beamline.tango_keystore.get("md3_alignmenty_limit")
        if phiy_limit["max"] >= phiy_limit["min"]:
            self.check_motor_limits("AlignmentY", phiy_limit["min"], phiy_limit["max"])
        else:
            # FIXME: # noqa: TD001,TD002,TD003,FIX001
            #        make the behaviour the same when checking md3_omega_limit.
            #        we should have a proper way of disabling the limits.
            #        the omega check assumes min > max to be a disabling the check
            #        this seems too hackish
            self.log.warning(
                "MD3 AlignmentY limits are not set correctly, "
                "please check md3_alignmenty_limit in tango keystore"
            )

    def set_omega_limit(self):
        omega_limit = HWR.beamline.tango_keystore.get("md3_omega_limit")
        if omega_limit["max"] >= omega_limit["min"]:
            start_pos = self.omega_motor_hwobj.get_value()
            self.command_dict["setOmegaLimits"](
                "%0.3f\t%0.3f" % (omega_limit["min"], omega_limit["max"])
            )
            self.user_log.info(f"setting MD3 Omega Limits to {omega_limit}")
            # critical, otherwise the first movement may cause collision
            self.home_motor("Omega")
            self.wait_device_ready(300)
            # set to the middle value
            self.user_log.info(
                f"Setting Omega back to the starting position {start_pos}"
            )
            self.omega_motor_hwobj.set_value(start_pos)
            self.wait_device_ready(100)
        else:
            self.log.warning(
                "MD3 Omega limits are not set correctly, "
                "please check md3_omega_limit in tango keystore"
            )

    def home_motor(self, motor_name):
        self.user_log.info(f"Homing Motor {motor_name}")
        self.command_dict["startHomingMotor"](motor_name)

    def save_centring_positions(self):
        """
        save the current position as centered position in MD3
        """
        self.wait_ready(10)
        self.command_dict["saveCentringPositions"]()
        self.last_centered_position = HWR.beamline.sample_view.get_positions()
        self.log.debug("MD3: save_centring_positions %s", self.last_centered_position)

    def state_changed(self, state):
        self.log.debug("State changed %s", state)
        self.current_state = state
        self.emit("stateChanged", (self.current_state))

    def motor_state_changed(self, state):
        self.emit("stateChanged", (state,))

    # Flux measurement utilities

    def set_calculate_flux_phase(self):
        self.log.warning(
            "Setting MD3 to calculate flux phase: DataCollection, "
            "Clear_Scintillator, beamstop_Z to 90 mm"
        )
        if not self.is_head_minikappa():
            motors = ["omega", "phix", "phiy", "phiz", "sampx", "sampy"]
        else:
            motors = [
                "omega",
                "phix",
                "phiy",
                "phiz",
                "sampx",
                "sampy",
                "kappa",
                "kappa_phi",
            ]
        ori_motors = {}

        for motor in motors:
            try:
                ori_motors[motor] = self.motors_hwobj_dict[motor].get_value()
            except:
                pass
        ori_phase = self.current_phase
        if self.current_phase != DiffractometerPhase.COLLECT:
            self.set_phase(DiffractometerPhase.COLLECT, timeout=200)

        self.log.warning("setAlignmentTable to CLEAR_SCINTILLATOR")
        self.channel_dict["AlignmentTablePosition"].set_value("CLEAR_SCINTILLATOR")
        self.wait_ready(10)

        self.log.warning("set beamstop Z to 90 mm")
        self.beamstop_z._set_value(90)
        self.wait_ready(10)

        return ori_motors, ori_phase

    def finish_calculate_flux(self, ori_motors, ori_phase=DiffractometerPhase.COLLECT):
        self.set_phase(ori_phase, timeout=200)
        self.wait_ready(10)
        if ori_phase == DiffractometerPhase.COLLECT:
            self.channel_dict["BeamstopPosition"].set_value("BEAM")
        self.wait_ready(10)
        if ori_motors is not None:
            self.move_sync_motors(ori_motors)
            self.wait_ready(10)

    # Cryo

    def is_inside_cryo_beam(self, pos: dict) -> bool:
        """Returns true if pos is guaranteed to keep the sample
        safely within the cryo beam"""
        return -4.0 < pos["phiy"] < 4.0

    def park_cryo_cooler(self, value=False, wait=True):
        """
        Set cryo cooler to park position if True, otherwise it's in
        """
        self.channel_dict["CryoIsOut"].set_value(value)
        if wait:
            self.wait_ready(2)

    def move_rex_out(self, wait=True, timeout=3):
        self.log.info("Moving REX out")
        self.wait_ready(3)
        self.rex.actuatorIn(wait=wait, timeout=timeout)

    def move_rex_in(self, wait=True, timeout=3):
        self.log.info("Moving REX in")
        self.wait_ready(3)
        self.rex.actuatorOut(wait=wait, timeout=timeout)

    # MD3 device management

    def transfer_mode_changed(self, transfer_mode):
        """
        Descript. :
        """
        self.log.info(f"current_transfer_mode is set to {transfer_mode}")
        self.transfer_mode = transfer_mode
        if transfer_mode != "SAMPLE_CHANGER":
            self.use_sc = False
        self.emit("minidiffTransferModeChanged", (transfer_mode,))

    def set_unmount_sample_phase(self, wait=True):
        """
        without changing the current MD3 phase, park beamstop, capillary, scintillator
        and set aperture to off position
        """
        self.wait_ready(3)
        self.command_dict["startMoveOrganDevices"]("OFF\tPARK\tPARK\tPARK")
        if wait:
            self.wait_ready(30)

    def abort(self, wait=True):
        """Abort all the pending tasks.

        Stops all the motors and closes all theirs control loops.
        """
        self.log.warning("aborting tasks")
        self.command_dict["abort"]()

        #
        # Wait for a while after sending 'abort' command,
        # before doing anything else.
        #
        # This way we work around some kind of MD3 bugs,
        # where interacting with MD3 too quickly after an abort
        # crashes its control software.
        #
        # Note using self.wait_device_ready() did not work here for some reason.
        #
        if wait:
            time.sleep(WAIT_AFTER_ABORT)

        self.log.warning("all tasks aborted")

    def is_ready(self):
        """
        Detects if device is ready
        """
        if "State" not in self.channel_dict:
            self.log.warning("MD3: State channel not available")
            return False
        return self.channel_dict["State"].get_value() == MD3State.tostring(
            MD3State.Ready
        )

    def wait_ready(self, timeout=30):
        """Waits when diffractometer status is ready:

        :param timeout: timeout in second
        :type timeout: int
        """
        with gevent.Timeout(timeout, Exception("Timeout waiting for device ready")):
            while not self.is_ready():
                time.sleep(0.01)

    def restart_md3(self, cold_restart=False):
        self.user_log.info("Restarting MD3 application")
        if cold_restart:
            self.command_dict["restart"]("1")
            time.sleep(140)
            # TODO@JieNan: more actions need to be added # noqa: TD003,FIX002
        else:
            self.command_dict["restart"]("0")

        self.wait_device_ready(360)

        self.set_omega_limit()

        if cold_restart:
            self.wait_device_ready(300)
            self.save_centring_positions()
            self.wait_device_ready(30)
            self.home_motor("AlignmentX")
            self.wait_device_ready(300)
            self.set_phase(DiffractometerPhase.CENTRE, timeout=300)

    # Auxilary methos
    def value_to_enum(self, value, which_enum):
        """Tranform a value to Enum

        Args:
           value(str, int, float, tuple, list): value
           which_enum (Enum): The enum to be checked.

        Returns:
            (Enum): Enum member, corresponding to the value or UNKNOWN.
        """
        try:
            return which_enum[value.upper()]
        except KeyError:
            for evar in which_enum:
                if (
                    isinstance(evar.value, (tuple, list)) and (value in evar.value)
                ) or (
                    isinstance(evar.value, (str, int, float))
                    and (str(value).upper() == str(evar.value).upper())
                ):
                    return evar
        return which_enum.UNKNOWN
