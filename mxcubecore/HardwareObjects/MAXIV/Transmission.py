import logging
import time

import gevent

from mxcubecore.HardwareObjects.abstract.AbstractTransmission import (
    AbstractTransmission,
)


class Transmission(AbstractTransmission):
    def __init__(self, name: str) -> None:
        super().__init__(self, name)

    def init(self):
        super().init()
        self.ready_event = gevent.event.Event()
        self.transmission_motor = None
        self.moving = None
        self.limits = [0, 100]
        self.threshold = 5

        try:
            self.transmission_motor = self.get_object_by_role("transmission_motor")
        except KeyError:
            logging.getLogger("HWR").warning("Error initializing transmission motor")
        if self.transmission_motor is not None:
            self.transmission_motor.connect(
                "valueChanged", self.transmission_position_changed
            )

    def is_ready(self) -> bool:
        return True

    def get_value(self) -> float:
        val = "%.3f" % self.transmission_motor.get_value()
        return float(val)

    def get_att_factor(self) -> str:
        return "%.3f" % self.transmission_motor.get_value()

    def get_att_state(self) -> int:
        return 1

    def get_limits(self) -> list[int, int]:
        return self.limits

    def setpoint_reached(self, setpoint: int | float) -> float:
        curr_pos = self.get_value()
        return abs(curr_pos - setpoint) < (0.05 * setpoint)  # within %5 of reach

    def set_value(self, value: int | float, wait=False):
        if not (self.limits[0] <= value and value <= self.limits[1]):
            err_msg = f"Expected transmission in {self.limits}, got {value}"
            raise ValueError(err_msg)

        with gevent.Timeout(10, Exception("Timeout waiting for device to be stopped")):
            while self.transmission_motor.is_moving():
                gevent.sleep(0.1)

        self.transmission_motor.set_value(value)  # self.transmission_motor.move(value)
        time.sleep(0.25)  # motor does not switch to moving inmediately
        if wait:
            with gevent.Timeout(30, Exception("Timeout waiting for device ready")):
                # while not self.setpoint_reached(value):
                while self.transmission_motor.is_moving():
                    gevent.sleep(0.1)

        self._update()

    def _update(self):
        self.emit("attStateChanged", self.get_att_state())

    def transmission_position_changed(self, *args):
        pos = self.get_value()
        self.emit("valueChanged", (pos,))

    def stop(self):
        self.transmission_motor.stop()
