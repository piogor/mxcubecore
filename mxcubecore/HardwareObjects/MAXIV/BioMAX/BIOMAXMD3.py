import os
import time

import cv2
import gevent
import numpy as np
from loopfinder.motion import CentringNavigator

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.MAXIV.MAXIVMD3 import MAXIVMD3


class BIOMAXMD3(MAXIVMD3):
    def __init__(self, name):
        super().__init__(name)

    def init(self):
        super().init()

        self.zoom_centre = eval(self.get_property("zoom_centre"))
        self.plate_row_list = ["A", "B", "C", "D", "E", "F", "G", "H"]
        self.head_type = self.channel_dict["HeadType"].get_value()

    def get_center_pos(self):
        """Returns the current motor positions except for zoom level. Used for loop centering"""
        cpos = self.get_positions()
        cpos.pop("zoom", None)
        return cpos

    def wait_stable_loop(self, wait_time: int) -> None:
        self.user_log.info("Waiting for loop to be stable...")
        img_bef = HWR.beamline.sample_view.get_snapshot(return_as_array=True)
        timer = 0
        wait_int = 2
        while timer < wait_time:
            time.sleep(wait_int)
            img_after = HWR.beamline.sample_view.get_snapshot(return_as_array=True)
            diff = cv2.absdiff(img_bef, img_after)
            if diff.max() < 100:
                self.user_log.info("No obvious drift, loop is relatively stable")
                return
            img_bef = img_after
            timer += wait_int
        self.user_log.info(
            "Loop is still drifting, have waited {}s, give up and continue with collection".format(
                wait_time
            )
        )
        self.update_zoom_calibration()

    def current_phase_changed(self, current_phase):
        """
        Descript. :
        """
        self.current_phase = current_phase
        self.log.info("MD3 phase changed to %s", current_phase)
        self.emit("phaseChanged", (current_phase,))

    def is_fast_shutter_open(self):
        return self.fast_shutter_channel.get_value()

    def state_changed(self, state):
        self.log.debug("State changed %s", state)
        self.current_state = state
        self.emit("minidiffStateChanged", (self.current_state))

    def motor_state_changed(self, state):
        """
        Descript. :
        """
        self.emit("minidiffStateChanged", (state,))

    def open_fast_shutter(self):
        self.log.info("Openning fast shutter")
        self.fast_shutter_channel.set_value(True)

    def close_fast_shutter(self):
        self.log.info("Closing fast shutter")
        self.fast_shutter_channel.set_value(False)

    def move_fluo_in(self, wait=True):
        self.log.info("Moving Fluo detector in")
        self.wait_device_ready(3)
        self.fluodet.actuatorIn()
        time.sleep(3)  # MD3 reports long before fluo is in position
        # the next lines are irrelevant, leaving there for future use
        if wait:
            with gevent.Timeout(10, Exception("Timeout waiting for fluo detector In")):
                while self.fluodet.get_actuator_state(read=True) != "in":
                    gevent.sleep(0.1)

    def move_fluo_out(self, wait=True):
        self.log.info("Moving Fluo detector out")
        self.wait_device_ready(3)
        self.fluodet.actuatorOut()
        if wait:
            with gevent.Timeout(10, Exception("Timeout waiting for fluo detector Out")):
                while self.fluodet.get_actuator_state(read=True) != "out":
                    gevent.sleep(0.1)

    def start_3_click_centring(self):
        self.start_centring_method(self.CENTRING_METHOD_MANUAL)

    def start_auto_centring(self):
        self.start_centring_method(self.CENTRING_METHOD_AUTO)

    def get_pixels_per_mm(self):
        """
        Get the values from coaxCamScaleX and coaxCamScaleY channels diretly

        :returns: list with two floats
        """
        zoom = HWR.beamline.sample_view.camera.get_image_zoom()
        return (
            zoom / self.channel_dict["CoaxCamScaleX"].get_value(),
            1 / self.channel_dict["CoaxCamScaleY"].get_value(),
        )

    def update_zoom_calibration(self):
        zoom = HWR.beamline.sample_view.camera.get_image_zoom()
        if zoom is not None:
            self.zoom_centre["x"] = self.zoom_centre["x"] * zoom
            self.zoom_centre["y"] = self.zoom_centre["y"] * zoom
        self.beam_position = [self.zoom_centre["x"], self.zoom_centre["y"]]
        self.beam_info_hwobj.beam_position = self.beam_position
        self.pixels_per_mm_x = zoom / self.channel_dict["CoaxCamScaleX"].get_value()
        self.pixels_per_mm_y = zoom / self.channel_dict["CoaxCamScaleY"].get_value()
        self.emit("pixelsPerMmChanged", ((self.pixels_per_mm_x, self.pixels_per_mm_y)))

    def blinded_by_the_lights(self, img: np.ndarray, threshold=1000) -> bool:
        """
        returns True if img is overexposed, which happens right after the backlight comes on.
        Default threshold is callibrated based on backlight level 1.
        tested on 12 normally exposed images, and 13 overexposed images.
        maximum white_count for normally exposed images was 111
        minimum for overexposed was 718495
        """
        # I said ooooo
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        white_count = (gray == 255).sum()
        return white_count > threshold

    def wait_for_backlight(self, poll_period=0.1) -> None:
        """
        Sleeps until the camera is no longer blinded by the backlight.
        """
        self.log.info("waiting for backlight to settle down")
        while self.blinded_by_the_lights(
            HWR.beamline.sample_view.get_snapshot(return_as_array=True)
        ):
            time.sleep(poll_period)
            # until I feel your touch
        self.log.info("backlight seems to have settled")

    def center_loop(self, patience: int = 100, tolerance_mm: float = 0.05) -> bool:
        """
        Parameters:
            patience: how many steps it will take before giving up
            tolerance_mm: acceptable distance from center.
                higher => faster centering, lower precision
        Returns:
            True on success, False if it ran out of patience.
        """
        zoom = HWR.beamline.sample_view.camera.get_image_zoom()
        self.pixels_per_mm_x = zoom / self.channel_dict["CoaxCamScaleX"].get_value()
        self.pixels_per_mm_y = zoom / self.channel_dict["CoaxCamScaleY"].get_value()
        nav = CentringNavigator(
            target_coordinates=tuple(self.beam_position),
            tolerance=tolerance_mm * self.pixels_per_mm_x,
        )
        for i in range(patience):
            img = HWR.beamline.sample_view.get_snapshot(return_as_array=True)
            step = nav.next_step(img)
            self.log.debug("step %s/%s - %s", i, patience, step)
            if step.finished():
                return True
            if step.rotate:
                self.phi_motor_hwobj.set_value_relative(step.rotate)
                self.wait_device_ready(10)
            if step.x_to_center or step.y_to_center:
                self.move_to_beam(step.x_to_center, step.y_to_center)
                self.wait_device_ready(10)
            gevent.sleep(0.2)
        self.log.debug(
            "center_loop ran out of patience (%s) with tolerance %s mm",
            patience,
            tolerance_mm,
        )
        return False

    def automatic_centring(self):
        self.wait_device_ready(10)

        # move MD3 to Centring phase if it's not
        if self.get_current_phase() != "Centring":
            self.user_log.info(
                "Moving Diffractometer to Centring for automatic_centring"
            )
            self.set_phase("Centring", wait=True, timeout=200)

        # This loop centring algorithm expects specific conditions.
        # In particular, it expects specific lighting conditions.
        # Back light should be on with factor 1, front light should be off.
        # Zoom level should be 1.

        # Switch off front light:
        self.front_light_switch.set_value(self.front_light_switch.VALUES.OUT)

        # Switch on back light with factor 1:
        self.back_light_switch.set_value(self.back_light_switch.VALUES.IN)
        self.back_light.set_value(1)

        # Set zoom level 1:
        self.zoom_motor_hwobj.set_value(self.zoom_motor_hwobj.VALUES.LEVEL1)
        self.wait_device_ready(20)

        self.omega_reference_motor.set_value(self.omega_reference_par["position"])

        self.wait_for_backlight()
        self.wait_device_ready(20)

        success = self.center_loop()
        if not success:
            self.user_log.error("Automatic loop centering failed!")

        self.wait_stable_loop(60)
        centred_pos = self.get_center_pos()
        return centred_pos

    def take_snapshots_loop(self, suffix):
        dir_name = "/data/staff/ispybstorage/staff/jienan"
        timestr = time.strftime("%Y%m%d-%H%M%S")
        file_name = os.path.join(dir_name, "{}_{}.jpeg".format(timestr, suffix))
        self.user_log.info(
            "Taking snapshot {} {} pre-aligning loop".format(file_name, suffix)
        )
        self.camera_hwobj.save_snapshot(file_name)
