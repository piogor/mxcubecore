import contextlib
import math
import sys
import time
from collections import deque
from typing import Iterable

import gevent
import numpy as np
import PyTango
from gevent import Timeout

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects import Energy
from mxcubecore.HardwareObjects.abstract.AbstractEnergy import AbstractEnergy
from mxcubecore.TaskUtils import *
from mxcubecore.utils.units import ev_to_kev


def _ev_vals_to_kev(ev_vals: Iterable[float]) -> tuple[float]:
    """
    convert all values from eV to KeV
    """
    return tuple(ev_to_kev(ev) for ev in ev_vals)


class Energy(AbstractEnergy):
    def __init__(self, *args, **kwargs):
        AbstractEnergy.__init__(self, *args, **kwargs)

    def init(self):
        try:
            super().init()
            self.moving = None
            self.default_en = None
            # To check beam stability
            self.total_counts = 0.0
            # This is the minimum number of counts on the beam detector. If below, there is no beam
            self.min_total_counts = None
            with contextlib.suppress(Exception):
                self.min_total_counts = HWR.beamline.tango_keystore.get_float(
                    "xbpm1_minimum_current"
                )
            # How many measurements of the beam position to average (to decrease the effect of noise)
            self.N = 4
            self.counts_now = deque(maxlen=self.N)
            # This is how much we allow the beam position to deviate (in microns)

        ks = HWR.beamline.tango_keystore
        if not ks.is_true("emulate_energy"):
            try:
                self.energy_motor = self.get_object_by_role("energy")
            except KeyError:
                self.log.warning("Energy: error initializing energy motor")

            if self.energy_motor is not None:
                self.energy_motor.connect("valueChanged", self.energy_position_changed)
                self.energy_motor.connect("stateChanged", self.energy_state_changed)
            self.get_energy_limits()
        else:
            self.energy_motor = None
            self._nominal_limits = ks.get("emulate_energy_limits")

    def energy_position_changed(self, pos):
        wl = 12.3984 / pos
        if wl:
            self.emit("energyChanged", (pos / 1000, wl * 1000))
            self.emit("valueChanged", (pos / 1000,))

    def energy_state_changed(self, state):
        self.emit("stateChanged", (state))

    def get_value(self):
        ks = HWR.beamline.tango_keystore
        if ks.is_true("emulate_energy"):
            return ks.get_float("emulate_energy_value")
        return ev_to_kev(self.energy_motor.get_value())

    def get_current_energy(self):
        ks = HWR.beamline.tango_keystore
        if ks.is_true("emulate_energy"):
            return ks.get_float("emulate_energy_value")
        if self.energy_motor is not None:
            try:
                return self.get_value()
            except:
                self.log.exception("EnergyHO: could not read current energy")
                return None
        return self.default_en

    def get_current_wavelength(self):
        current_en = self.get_current_energy()
        if current_en:
            curr_wave = 12.3984 / current_en
            return curr_wave
        return None

    def get_energy_limits(self):
        if self.energy_motor is not None:
            try:
                self._nominal_limits = _ev_vals_to_kev(self.energy_motor.get_limits())
            except:
                self.log.exception("EnergyHO: could not read energy motor limits")

    def start_move_energy(self, value, wait=True, check_beam=True):
        try:
            value = float(value)
        except (TypeError, ValueError):
            self.user_log.error(f"Energy: invalid energy {value}")
            return False

        current_en = self.get_current_energy()
        if current_en:
            if math.fabs(value - current_en) < 0.001:
                self.moving = False
                self.emit("moveEnergyFinished", ())
                self.log.debug(f"Energy: already at {current_en:.4f}, not moving")
                return
        if self.check_limits(value) is False:
            return False

        self.moving = True
        self.emit("moveEnergyStarted", ())

        def change_egy():
            try:
                self.move_energy(value, wait=True, check_beam_end=check_beam)
            except:
                sys.excepthook(*sys.exc_info())
                self.moving = False
                self.emit("moveEnergyFailed", ())
            else:
                self.moving = False
                self.emit("moveEnergyFinished", ())

        if wait:
            change_egy()
        else:
            gevent.spawn(change_egy)

    def check_limits(self, value):
        ks = HWR.beamline.tango_keystore
        if ks.is_true("emulate_energy"):
            min_e, max_e = ks.get("emulate_energy_limits")
        else:
            min_e, max_e = self.get_limits()

        within_limits = min_e <= value <= max_e
        if within_limits:
            return True
        self.user_log.info(
            f"Requested energy is out of limits: {min_e} <= {value:.4f} <= {max_e}"
        )
        return False

    def _set_value(self, value):
        self.move_energy(value)

    def move_energy(self, energy, wait=True, check_beam_end=True):
        current_en = self.get_current_energy()
        pos = math.fabs(current_en - energy)
        if pos < 0.001:
            self.log.info(f"Energy: already at {energy:.4f} keV, not moving")
            return

        ks = HWR.beamline.tango_keystore
        if ks.is_true("emulate_energy"):
            ks.put("emulate_energy_value", energy)
            return

        self.log.info(f"Energy: moving energy to {energy:.4f} keV")
        self.energy_motor.set_value(energy * 1000)
        self.energy_motor.wait_end_of_move(800)
        if check_beam_end:
            try:
                self.check_beam()
            except RuntimeError as ex:
                self.user_log.error("Check beam error")
                self.log.exception("Check beam error")
            except Exception as ex:
                self.user_log.error("Check beam exception")
                self.log.exception("Check beam exception")

    def _deprecate_sync_move(self, position, timeout=None):
        """
        Deprecated method - corresponds to move until move finished.
        """
        self.energy_motor.set_value(position)
        try:
            with Timeout(timeout):
                time.sleep(0.1)
                while self.is_moving():
                    time.sleep(0.1)
        except:
            raise Timeout

    def cancel_move_energy(self):
        self.user_log.info("Cancel Energy move")
        self.log.info("Cancel Energy move")

        if HWR.beamline.tango_keystore.is_true("emulate_energy"):
            return

        self.energy_motor.stop()

    def check_beam(self):
        # check if mirror piezo feedback is running
        pidx = PyTango.DeviceProxy("b311a/ctl/pid-01")
        pidy = PyTango.DeviceProxy("b311a/ctl/pid-02")

        if (
            pidx.State() != PyTango.DevState.MOVING
            and pidy.State() != PyTango.DevState.MOVING
        ):
            # If the PID loop is not running the beam alignment should be done by hand
            raise Exception("Mirror piezo PID loop not running.")

        # check presence of beam in the hutch
        xbpm = PyTango.DeviceProxy("b311a/xbpm/02")
        self.total_counts = xbpm.S
        # self.output(self.total_counts)
        # Value decreased by 3 orders of magnitude since firmware upgrade of aems
        if self.min_total_counts is not None:
            if self.total_counts < self.min_total_counts:
                # wait a little and check again
                time.sleep(5)
                self.log.info("Checking XBPM counts again!")
                self.total_counts = xbpm.S
                if self.total_counts < self.min_total_counts:
                    raise Exception(
                        "There is no beam in the BCU. Check the front end shutters, the undulator gap and the NanoBPM regulation."
                    )

        # How long we check for stable beam
        timeout = 120
        waittime = 0
        countsv = xbpm.Y
        countsh = xbpm.X
        self.counts_now.clear()

        with gevent.Timeout(120, RuntimeError("The beam is not stable.")):
            while (
                self.is_good_beam(self.N, countsv) == False
                or self.is_good_beam(self.N, countsh) == False
            ):
                countsv = xbpm.Y
                countsh = xbpm.X

                gevent.sleep(1)
        self.user_log.info("Beam is stable.")
        return True

    def is_good_beam(self, N, counts):
        if self.min_total_counts is None:
            return
        self.counts_now.append(counts)
        if len(self.counts_now) < N:
            return False

        avg_now = np.sum(self.counts_now) / len(self.counts_now)

        if abs(avg_now) > 1.0:
            return False

        elif self.total_counts < self.min_total_counts:
            # No beam
            return False
        else:
            return True
