import time

import cv2
import gevent
import numpy as np
from loopfinder.motion import CentringNavigator
from loopfinder.vision import canny_masker, mini

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.MAXIV.MAXIVMD3 import MAXIVMD3


class BIOMAXMD3(MAXIVMD3):
    def init(self):
        super().init()

        self.fluodet = self.get_object_by_role("fluodet")

        self.zoom_centre = eval(self.get_property("zoom_centre"))
        self.plate_row_list = ["A", "B", "C", "D", "E", "F", "G", "H"]
        self.head_type = self.channel_dict["HeadType"].get_value()

    def wait_stable_loop(self, wait_time: int = 10) -> None:
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
            "Loop is still drifting, have waited %ss, "
            "give up and continue with collection",
            wait_time,
        )
        self.update_zoom_calibration()

    def automatic_centring(self) -> dict:
        super().automatic_centring()
        self.wait_stable_loop()
        return self.get_center_pos()

    def state_changed(self, state):
        self.log.debug("State changed %s", state)
        self.current_state = state
        self.emit("minidiffStateChanged", (self.current_state))

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

    def centring_navigator(self, tolerance_mm: float) -> CentringNavigator:
        """
        This returns a custom navigator for loop centering on biomax.
        """

        def foreground_segmentor(img: np.ndarray):
            return mini(lambda mini_img: canny_masker(mini_img))(img)

        return CentringNavigator(
            target_coordinates=tuple(self.beam_position),
            tolerance=tolerance_mm * self.pixels_per_mm_x,
            segmentor=foreground_segmentor,
        )
