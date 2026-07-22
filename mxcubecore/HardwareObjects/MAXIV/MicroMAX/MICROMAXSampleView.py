import numpy as np
from loopfinder.motion import CentringNavigatorUp
from loopfinder.vision import canny_masker, mini, tunnel_vision

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.MAXIV.MAXIVSampleView import MAXIVSampleView


class MICROMAXSampleView(MAXIVSampleView):
    def __init__(self, name):
        super().__init__(name=name)

    def init(self):
        super().init()

    def center_loop(
        self,
        patience: int = 100,
        tolerance_mm: float = 0.05,  # noqa: ARG002
    ) -> bool:
        patience = HWR.beamline.tango_keystore.get_integer("loopfinder_max_tries")
        super().center_loop(patience=patience)

    def centring_navigator(self, tolerance_mm: float) -> CentringNavigatorUp:
        """
        This returns a custom navigator for loop centering on MicroMAX.
        The navigator for micromax uses the subclass CentringNavigatorUp for use
        with the upwards-facing MD3. It also has tunnel-vision to avoid the sharp
        edge of the micromax backlight.
        """

        def foreground_segmentor(img: np.ndarray):
            return mini(
                lambda mini_img: tunnel_vision(canny_masker(mini_img, min_sharpness=25))
            )(img)

        pixels_per_mm_x, _pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        beam_position = HWR.beamline.beam.get_beam_position_on_screen()
        return CentringNavigatorUp(
            target_coordinates=tuple(beam_position),
            tolerance=tolerance_mm * pixels_per_mm_x,
            segmentor=foreground_segmentor,
        )

    def get_centred_point_from_coord(self, x, y, return_by_names=None):
        pixels_per_mm_x, pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        beam_position = HWR.beamline.beam.get_beam_position_on_screen()

        if not HWR.beamline.tango_keystore.is_enabled("ssx_mode"):
            self.centring_hwobj.initCentringProcedure()
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

            if "zoom" in pos:
                pos["zoom"] = pos["zoom"].value

        else:
            zoom_centre = HWR.beamline.diffractometer.zoom_centre
            dx = (x - zoom_centre["x"]) / float(pixels_per_mm_x)
            dy = (y - zoom_centre["y"]) / float(pixels_per_mm_y)

            pos = self.get_positions()
            pos["phiy"] += dy
            pos["phiz"] -= dx

        try:
            pos.pop("kappa")
            pos.pop("kappa_phi")
        except KeyError:
            pass

        return pos

    def move_to_beam(self, x, y, omega=None):  # noqa: ARG002
        # Temporary solution to use either alignment or
        # sample table motors for 'move to beam' movements,
        # depending if we run in SSX or normal mode.
        # Once the more permanent 'SSX fixed target' mode
        # is implemented, this method should be revised
        # and removed or updated accordingly.
        #
        ssx_mode = HWR.beamline.tango_keystore.is_enabled("ssx_mode")
        self.log.info(f"move_to_beam({x:.4f} {y:.4f}) {ssx_mode=}")
        pixels_per_mm_x, pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )

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
            y_move_rel = (y - beam_yc) / float(pixels_per_mm_y)
            x_move_abs = horizontal_axis.get_value() - (x - beam_xc) / float(
                pixels_per_mm_x
            )
            self.emit_progress_message("")

            vertical_axis.set_value_relative(y_move_rel)
            horizontal_axis.set_value(x_move_abs)
            HWR.beamline.diffractometer.wait_ready(5)
        except Exception:
            self.log.exception("could not move to beam.")
