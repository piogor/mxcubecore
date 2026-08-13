import ast
import time

import gevent
import numpy as np
from loopfinder.motion import CentringNavigator

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractDiffractometer import (
    DiffractometerPhase,
)
from mxcubecore.HardwareObjects.SampleView import SampleView


class MAXIVSampleView(SampleView):
    """SampleView class"""

    def __init__(self, name):
        super().__init__(name=name)
        self._centring = None

        # Channels and commands -----------------------------------------------
        self.channel_dict = {}
        self.used_channels_list = []
        self.command_dict = {}
        self.used_commands_list = []

        # centring
        self.waiting_for_click = None  # None = legacy/no-wait mode,
        # True = waiting,
        # False = manual centring in progress
        self.click_lock = gevent.lock.Semaphore()
        self.user_clicked_event = None
        self.use_sample_centring = None

    def init(self):  # noqa: C901
        super().init()

        self.omega_motor_hwobj = self.centring_motors["omega"].motor
        self.phix_motor_hwobj = self.centring_motors["phix"].motor
        self.phiy_motor_hwobj = self.centring_motors["phiy"].motor
        self.phiz_motor_hwobj = self.centring_motors["phiz"].motor
        self.sample_x_motor_hwobj = self.centring_motors["sampx"].motor
        self.sample_y_motor_hwobj = self.centring_motors["sampy"].motor
        try:
            self.kappa_motor_hwobj = self.centring_motors["kappa"].motor
        except (KeyError, AttributeError):
            self.kappa_motor_hwobj = None
        try:
            self.kappa_phi_motor_hwobj = self.centring_motors["kappa_phi"].motor
        except (KeyError, AttributeError):
            self.kappa_phi_motor_hwobj = None

        # Gather omega reference motor and focus motor,
        # and connect to omega reference motor value_changed signal
        try:
            self.omega_reference_par = self.get_property("omega_reference")
            self.omega_reference_motor = self.centring_motors[
                self.omega_reference_par["motor_name"]
            ].motor
            if self.omega_reference_motor is not None:
                self.connect(
                    self.omega_reference_motor,
                    "value_changed",
                    self.omega_reference_motor_moved,
                )
            self.omega_reference_focus = self.centring_motors[
                self.omega_reference_par["focus_ref"]
            ].motor
        except Exception:
            self.log.exception("Omega axis is not defined.")

        # centring properties
        self.use_sample_centring = self.get_property("sample_centring")

        # Gathering and connecting to exporter channels
        self.used_channels_list = self.get_property("used_channels", [])
        if isinstance(self.used_channels_list, str):
            self.used_channels_list = ast.literal_eval(self.used_channels_list)

        for channel_name in self.used_channels_list:
            self.channel_dict[channel_name] = self.get_channel_object(channel_name)

        # TODO(piogor, #378): refactor and move  # noqa: FIX002
        # CentringTableVerticalPositionPosition to
        # configuration and load as the other channels above
        self.cent_vertical_pseudo_motor = None
        try:
            self.cent_vertical_pseudo_motor = self.add_channel(
                {"type": "exporter", "name": "CentringTableVerticalPositionPosition"},
                "CentringTableVerticalPosition",
            )
            if self.cent_vertical_pseudo_motor is not None:
                self.connect(
                    self.cent_vertical_pseudo_motor, "update", self.centring_motor_moved
                )
        except Exception:
            self.log.exception("Cannot initialize CentringTableVerticalPosition")

        # Gathering exporter commands
        self.used_commands_list = self.get_property("used_commands", [])
        if isinstance(self.used_commands_list, str):
            self.used_commands_list = ast.literal_eval(self.used_commands_list)

        for command_name in self.used_commands_list:
            self.command_dict[command_name] = self.get_command_object(command_name)

        # leaving for compatibility
        # TODO(piogor, #378): remove this in the future,   # noqa: FIX002
        # and use self.wait_ready() instead
        self.wait_device_ready = HWR.beamline.diffractometer.wait_ready

    def motor_positions_to_screen(self, centred_positions_dict):
        c = centred_positions_dict
        xy = self.centring_hwobj.centringToScreen(c)
        pixels_per_mm_x, pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        zoom_centre = HWR.beamline.diffractometer.zoom_centre
        x = xy["X"] * pixels_per_mm_x + zoom_centre["x"]
        y = xy["Y"] * pixels_per_mm_y + zoom_centre["y"]
        return x, y

    def emit_progress_message(self, msg=None):
        self.emit("progressMessage", (msg,))

    ## ------------------------------- ##
    ##      SAMPLE CENTRING            ##
    ## ------------------------------- ##
    @property
    def centring_hwobj(self):
        if self._centring is None:
            #
            # Due to circular dependency between CentringMath and MD3 hardware
            # objects, we need to load reference to CentringMath object lazily
            # on first usage.
            #
            # MD3 must be created before CentringMath, as it loads references to
            # its motors, thus CentringMath object does not exist when executing
            # MAXIVMD3.init() method.
            #
            self._centring = HWR.beamline.get_object_by_role("centring")

        return self._centring

    def centring_motor_moved(self, _pos):
        #        if time.time() - self.centring_time > 1.0:
        #            self.invalidate_centring()  # noqa: ERA001
        HWR.beamline.diffractometer.emit_diffractometer_moved()

    def find_loop(self):
        return -1, -1, 0

    def start_3_click_centring(self):
        self.start_manual_centring(nb_click=3)

    def image_clicked(self, x: float, y: float):
        """Handles a user click sent from the frontend during the manual centring.

        This method is called by the backend when the user clicks on the sample
        image in the frontend.

        The attribute `self.waiting_for_click` controls whether the click should
        be accepted or ignored:
            - None: click is accepted (legacy)
            - True: waiting for a click, accept it and mark it as received
            - False: already received a click, ignore further clicks

        Args:
            x: X coordinate of the click.
            y: Y coordinate of the click.

        Raises:
            RuntimeError: If a click is received while a previous
            one is still being processed.
        """
        # if use_sample_centring is True, use centing implemented
        # in SampleView, based on sample_centering module.
        if self.use_sample_centring:
            super().image_clicked(x, y)
            return

        with self.click_lock:
            # "waiting for click" logic is not implememted (legacy)
            # or it is actually waiting for a click
            if self.waiting_for_click is None or self.waiting_for_click:
                if self.waiting_for_click:
                    self.waiting_for_click = False
                self.user_clicked_event.set((x, y))
            # Already received a click, ignore further clicks
            else:
                self.log.warning(
                    "User attempted to click while the previous centring "
                    "step was still in progress. Click ignored"
                )
                err_msg = (
                    "Click ignored: a centring step is still being "
                    "processed. Please wait before clicking again."
                )
                raise RuntimeError(err_msg)

    def start_manual_centring(self, nb_click: int = 3):
        # if use_sample_centring is True, use centing implemented
        # in SampleView, based on sample_centering module.
        if self.use_sample_centring:
            self.log.debug("Using sample_centring for manual centring")
            super().start_manual_centring(nb_click)
            return

        if self.current_centring_procedure is not None:
            self.log.warning("Already centring")
            return
        self.current_centring_method = "Manual"
        self.emit("centringStarted", ("Manual"))
        self.current_centring_procedure = gevent.spawn(
            self.manual_centring, nb_click=nb_click
        )
        self.current_centring_procedure.link(self.manual_centring_done)

    def start_auto_centring(self):
        # if use_sample_centring is True, use centing implemented
        # in SampleView, based on sample_centering module.
        if self.use_sample_centring:
            self.log.debug("Using sample_centring for manual centring")
            super().start_auto_centring()
            return

        if self.current_centring_procedure is not None:
            self.log.warning("Already centring")
            return

        self.current_centring_method = "Automatic"
        self.emit("centringStarted", ("Automatic"))
        self.current_centring_procedure = gevent.spawn(self.automatic_centring)
        self.current_centring_procedure.link(self.auto_centring_done)

    def manual_centring(self, nb_click: int = 3):
        # Do not perform centring for ssx experiments
        if HWR.beamline.tango_keystore.is_enabled("ssx_mode"):
            self.user_log.critical("SSX mode is enabled, cannot do manual centring.")
            return None
        HWR.beamline.diffractometer.check_omega_limit()
        self.move_to_omega_reference_pos()
        # self.wait_device_ready(10)  # noqa: ERA001
        pixels_per_mm_x, pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        self.centring_hwobj.initCentringProcedure()
        beam_position = HWR.beamline.beam.get_beam_position_on_screen()
        for click in range(nb_click):
            self.user_clicked_event = gevent.event.AsyncResult()
            x, y = self.user_clicked_event.get()
            self.centring_hwobj.appendCentringDataPoint(
                {
                    "X": (x - beam_position[0]) / pixels_per_mm_x,
                    "Y": (y - beam_position[1]) / pixels_per_mm_y,
                }
            )
            if HWR.beamline.diffractometer.in_plate_mode:
                dynamic_limits = self.omega_motor_hwobj.get_dynamic_limits()
                if click == 0:
                    self.omega_motor_hwobj.set_value(dynamic_limits[0])
                elif click == 1:
                    self.omega_motor_hwobj.set_value(dynamic_limits[1])
            elif click < 2:
                self.omega_motor_hwobj.set_value_relative(90)
        self.omega_reference_add_constraint()
        return self.centring_hwobj.centeredPosition(return_by_name=False)

    def wait_for_stable_backlight(
        self, interval=0.1, timeout=10, tolerance=1.0
    ) -> bool:
        """
        Wait until probe_signal() returns roughly the same value (within
        tolerance) 3 times in a row with `interval` seconds in between.
        returns false if the timeout ran out before the light could settle.
        """
        streak = []
        time_start = time.time()
        while time.time() < time_start + timeout:
            brightness = np.array(self.take_snapshot()).mean()
            streak.append(brightness)
            self.log.debug("backlight streak: %s", streak)
            if len(streak) > 1 and abs(streak[-1] - streak[-2]) > tolerance:
                streak = []  # broke the streak
            if len(streak) >= 3:
                return True
            time.sleep(interval)
        self.log.warning(
            "waiting for stable light timed out! The streak was %s", streak
        )
        return False

    def centring_navigator(self, tolerance_mm: float) -> CentringNavigator:
        """Returns the approperiate centring navigator for this beamline"""
        message = "needs to be implemented for each beamline"
        raise NotImplementedError(message)

    def center_loop(self, patience: int = 30, tolerance_mm: float = 0.05) -> bool:
        """
        Uses Loopfinder to iteratively find the loop tip.
        Tuned to special lighting conditions. see self.automatic_centring().
        Parameters:
            patience: how many steps it will take before giving up
            tolerance_mm: acceptable distance from center.
                higher => faster centering, lower precision
        Returns:
            True on success, False if it ran out of patience.
        """

        nav = self.centring_navigator(tolerance_mm)
        self.log.info(
            "navigator tolerance: %s, target: %s", nav.tolerance, nav.target_coordinates
        )
        for i in range(patience):
            self.wait_device_ready(20)
            time.sleep(0.2)
            img = np.array(self.take_snapshot())
            step = nav.next_step(img)
            self.log.info(f"step {i}/{patience} - {step}")
            if step.finished():
                self.log.info("center_loop success")
                return True
            if step.rotate:
                self.omega_motor_hwobj.set_value_relative(step.rotate)
                HWR.beamline.diffractometer.set_value_motors(
                    {"omega": self.omega_motor_hwobj.get_value() + step.rotate}
                )
                self.wait_device_ready(20)
            if step.x_to_center and step.y_to_center:
                target_pos = self.get_centred_point_from_coord(
                    step.x_to_center, step.y_to_center, return_by_names=True
                )
                if not HWR.beamline.diffractometer.is_inside_cryo_beam(target_pos):
                    self.log.error("""
                        Hi, The loopfinder navigator wants to move the sample to a
                        position outside the cryo beam, which I guess would not be
                        ideal for your sample. This would only happen if something is
                        very wrong, Like if there is no pin at all, or the pin is
                        freakishly long. Please check if something is physically wrong.
                        If not, the loopfinder might have mistakenly found an edge in
                        the background and thinks it's the loop. Is the zoom level or
                        backlight in an unexpected state? If the environment variable
                        LOOPFINDER_DIAGNOSTICS_PATH is set, you can check if you have a
                        background edge by looking at the latest diagnostic images
                        there. If you have a background edge, find out if the background
                        has changed for some reason, and if that change was intended,
                        either adjust the backlight or whatever is causing the edge,
                        or adjust the min_sharpness threshold on the
                        CentringNavigator's segmentor.
                        Godspeed.

                         / Isak L
                        """)
                    return False
                relevant_motorpos = {
                    k: target_pos[k] for k in ["sampx", "sampy", "phiy"]
                }
                HWR.beamline.diffractometer.set_value_motors(relevant_motorpos)
                self.wait_device_ready(20)
        self.log.warning(
            f"center_loop ran out of patience ({patience}). Maybe increase tolerance?"
        )
        return False

    def get_center_pos(self) -> dict:
        """
        Returns the current motor positions except for zoom level.
        Used for loop centering
        """
        cpos = self.get_positions()
        cpos.pop("zoom", None)
        return cpos

    def automatic_centring(self) -> dict:
        """
        Performs automatic loop centering and sets up all the prerequisites
        for the centering to work. Returns a 3d point on the centered position.
        """
        self.wait_device_ready(20)

        # Don't try centring if a sample is not detected
        if not HWR.beamline.diffractometer.sample_is_loaded:
            self.log.warning(
                "Sample is not detected on the magnet, bailing out of loop centring."
            )
            self.user_log.critical(
                "Sample is not detected on the magnet. "
                "Check camera and run //Empty Mount// beamline action."
            )
            return self.get_center_pos()

        # move MD3 to Centring phase if it's not
        if HWR.beamline.diffractometer.get_phase() != DiffractometerPhase.CENTRE:
            self.user_log.info(
                "Moving Diffractometer to Centring for automatic_centring"
            )
            HWR.beamline.diffractometer.set_phase(
                DiffractometerPhase.CENTRE, timeout=200
            )

        # This loop centring algorithm expects specific conditions.
        # In particular, it expects specific lighting conditions.
        # Back light should be on with factor 1, front light should be off.
        # Zoom level should be 1.

        # Switch off front light:
        HWR.beamline.diffractometer.front_light_switch.set_value(
            HWR.beamline.diffractometer.front_light_switch.VALUES.OUT
        )

        # Switch on back light with factor 1:
        HWR.beamline.diffractometer.back_light_switch.set_value(
            HWR.beamline.diffractometer.back_light_switch.VALUES.IN
        )
        HWR.beamline.diffractometer.back_light.set_value(1)

        # Set zoom level 1:
        HWR.beamline.diffractometer.zoom_motor_hwobj.set_value(HWR.beamline.diffractometer.zoom_motor_hwobj.VALUES.LEVEL1)
        self.wait_device_ready(20)

        self.omega_reference_motor.set_value(self.omega_reference_par["position"])

        self.wait_for_stable_backlight()
        self.wait_device_ready(20)

        success = self.center_loop()
        if not success:
            self.user_log.warning("Automatic loop centering failed!")

        return self.get_center_pos()

    def omega_reference_add_constraint(self):
        beam_position = HWR.beamline.beam.get_beam_position_on_screen()
        if self.omega_reference_par is None or beam_position is None:
            return
        pixels_per_mm_x, pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        zoom_centre = HWR.beamline.diffractometer.zoom_centre
        if self.omega_reference_par["camera_axis"].lower() == "x":
            on_beam = (beam_position[0] - zoom_centre["x"]) * self.omega_reference_par[
                "direction"
            ] / pixels_per_mm_x + self.omega_reference_par["position"]
        else:
            on_beam = (beam_position[1] - zoom_centre["y"]) * self.omega_reference_par[
                "direction"
            ] / pixels_per_mm_y + self.omega_reference_par["position"]
        self.centring_hwobj.appendMotorConstraint(self.omega_reference_motor, on_beam)

    def omega_reference_motor_moved(self, pos):
        pixels_per_mm_x, pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        if self.omega_reference_par["camera_axis"].lower() == "x":
            pos = (
                self.omega_reference_par["direction"]
                * (pos - self.omega_reference_par["position"])
                * pixels_per_mm_x
                + HWR.beamline.diffractometer.zoom_centre["x"]
            )
            self.reference_pos = (pos, -10)
        else:
            pos = (
                self.omega_reference_par["direction"]
                * (pos - self.omega_reference_par["position"])
                * pixels_per_mm_y
                + HWR.beamline.diffractometer.zoom_centre["y"]
            )
            self.reference_pos = (-10, pos)
        self.emit("omegaReferenceChanged", (self.reference_pos,))

    def refresh_omega_reference_position(self):
        if self.omega_reference_motor is not None:
            reference_pos = self.omega_reference_motor.get_value()
            self.omega_reference_motor_moved(reference_pos)

    def move_cent_vertical_relative(self, value=0):
        cent_vertical_to_move = self.cent_vertical_pseudo_motor.get_value() + value
        motor_limits = self.command_dict["getMotorDynamicLimits"](
            "CentringTableVertical"
        )
        if (
            cent_vertical_to_move > motor_limits[1]
            or cent_vertical_to_move < motor_limits[0]
        ):
            msg = "Target position is beyond the centering motor limits"
            self.log.error(msg)
            raise Exception(msg)  # noqa: TRY002
        self.wait_device_ready(5)
        self.cent_vertical_pseudo_motor.set_value(cent_vertical_to_move)
        self.wait_device_ready(5)

    def move_to_omega_reference_pos(self):
        pos = self.omega_reference_par["position"]
        self.omega_reference_motor.set_value(pos)

        omega_reference_focus_pos = self.omega_reference_par["focus_pos"]
        self.omega_reference_focus.set_value(omega_reference_focus_pos)

    def move_to_beam(self, x, y, omega=None):
        """
        Descript. : function to create a centring point based on all motors
                    positions.
        """
        # if use_sample_centring is True, use centing implemented
        # in SampleView, based on sample_centering module.
        if self.use_sample_centring:
            super().move_to_beam(x, y)
            return

        try:
            pos = self.get_centred_point_from_coord(x, y, return_by_names=False)
            if omega is not None:
                pos["phiMotor"] = omega
            HWR.beamline.diffractometer.move_to_motors_positions(pos)
        except Exception:
            self.log.exception("Diffractometer: could not center to beam, aborting")

    def get_centred_point_from_coord(self, x, y, return_by_names=None):
        self.centring_hwobj.initCentringProcedure()
        pixels_per_mm_x, pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        beam_position = HWR.beamline.beam.get_beam_position_on_screen()
        self.centring_hwobj.appendCentringDataPoint(
            {
                "X": (x - beam_position[0]) / pixels_per_mm_x,
                "Y": (y - beam_position[1]) / pixels_per_mm_y,
            }
        )
        self.omega_reference_add_constraint()
        pos = self.centring_hwobj.centeredPosition()
        if return_by_names:
            pos = self.convert_from_obj_to_name(pos)

        #
        # Zoom motor values are enums of integers,
        # they will fail to serialized as JSON when send to front end.
        # Convert them to plain integer to make it work.
        #
        if "zoom" in pos:
            pos["zoom"] = pos["zoom"].value

        return pos

    def convert_from_obj_to_name(self, motor_pos):
        motors = {}
        for motor_role in self.centring_motors:
            motor_obj = self.centring_motors[motor_role].motor
            try:
                motors[motor_role] = motor_pos[motor_obj]
            except KeyError:
                if motor_obj:
                    motors[motor_role] = motor_obj.get_value()

        beam_position = HWR.beamline.beam.get_beam_position_on_screen()
        zoom_centre = HWR.beamline.diffractometer.zoom_centre
        pixels_per_mm_x, pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        motors["beam_x"] = (beam_position[0] - zoom_centre["x"]) / pixels_per_mm_y
        motors["beam_y"] = (beam_position[1] - zoom_centre["y"]) / pixels_per_mm_x
        return motors

    def get_positions(self) -> dict:
        return {
            "omega": float(self.omega_motor_hwobj.get_value()),
            "phix": float(self.phix_motor_hwobj.get_value()),
            "phiy": float(self.phiy_motor_hwobj.get_value()),
            "phiz": float(self.phiz_motor_hwobj.get_value()),
            "sampx": float(self.sample_x_motor_hwobj.get_value()),
            "sampy": float(self.sample_y_motor_hwobj.get_value()),
            "kappa": (
                float(self.kappa_motor_hwobj.get_value())
                if self.kappa_motor_hwobj
                else 0.0
            ),
            "kappa_phi": (
                float(self.kappa_phi_motor_hwobj.get_value())
                if self.kappa_phi_motor_hwobj
                else 0.0
            ),
            # "zoom": float(self.zoom_motor_hwobj.get_value().value),  # noqa: ERA001
        }

    def manual_centring_done(self, centring_procedure):
        # if use_sample_centring is True, use centing implemented
        # in SampleView, based on sample_centering module.
        if self.use_sample_centring:
            super().manual_centring_done(centring_procedure)
            return

        try:
            motor_pos = centring_procedure.get()
            if isinstance(motor_pos, gevent.GreenletExit):
                raise motor_pos  # noqa: TRY301
            HWR.beamline.diffractometer.set_value_motors(motor_pos, timeout=30)
        except Exception:
            self.log.exception("Could not complete manual centring")
            self.centring_failed()
        else:
            self.centring_done()

    # Auxilary methos
    def value_to_enum(self, value, which_enum):
        return HWR.beamline.diffractometer.value_to_enum(value, which_enum)
