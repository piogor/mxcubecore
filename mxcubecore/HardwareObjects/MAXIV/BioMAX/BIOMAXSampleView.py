import time

import cv2
import numpy as np
from loopfinder.motion import CentringNavigator
from loopfinder.vision import canny_masker, mini

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.MAXIV.MAXIVSampleView import MAXIVSampleView


class BIOMAXSampleView(MAXIVSampleView):
    def __init__(self, name):
        super().__init__(name=name)

    def init(self):
        super().init()

    def centring_navigator(self, tolerance_mm: float) -> CentringNavigator:
        """
        This returns a custom navigator for loop centering on biomax.
        """

        def foreground_segmentor(img: np.ndarray):
            return mini(lambda mini_img: canny_masker(mini_img))(img)

        pixels_per_mm_x, _pixels_per_mm_y = (
            HWR.beamline.diffractometer.get_pixels_per_mm()
        )
        beam_position = HWR.beamline.beam.get_beam_position_on_screen()
        return CentringNavigator(
            target_coordinates=tuple(beam_position),
            tolerance=tolerance_mm * pixels_per_mm_x,
            segmentor=foreground_segmentor,
        )

    def automatic_centring(self) -> dict:
        super().automatic_centring()
        self.wait_stable_loop()
        return self.get_center_pos()

    def wait_stable_loop(self, wait_time: int = 10) -> None:
        self.user_log.info("Waiting for loop to be stable...")
        img_bef = self.get_snapshot(return_as_array=True)
        timer = 0
        wait_int = 2
        while timer < wait_time:
            time.sleep(wait_int)
            img_after = self.get_snapshot(return_as_array=True)
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
        HWR.beamline.diffractometer.update_zoom_calibration()
