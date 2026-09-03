import time

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.MAXIV.MAXIVMD3 import MAXIVMD3


class BIOMAXMD3(MAXIVMD3):
    def init(self):
        try:
            super().init()

            self.fluodet = self.get_object_by_role("fluodet")

            self.plate_row_list = ["A", "B", "C", "D", "E", "F", "G", "H"]
            self.head_type = self.channel_dict["HeadType"].get_value()
        except Exception:
            self.log.exception("Error initializing BIOMAXMD3")
            raise

    def state_changed(self, state):
        self.log.debug("State changed %s", state)
        self.current_state = state
        self.emit("stateChanged", (self.current_state))

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
        pixels_per_mm_x, pixels_per_mm_y = self.get_pixels_per_mm()
        self.emit("pixelsPerMmChanged", ((pixels_per_mm_x, pixels_per_mm_y)))
