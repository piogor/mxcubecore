# Temporary chopper helper used by beamline_actions/StartChopper.
# This is intentionally not a full MXCuBE hardware object: external_sync logic
# is planned to move to a Tango device server, after which this file can be
# removed together with the beamline action refactor.

import logging
import time

from tango import DeviceProxy

TANGO_DEVICE = "b312-e/bcu/chopper"
PARKING_ANGLE = 22  # [deg] this value aligns the cutouts with the passing hole

log = logging.getLogger("HWR")


class CelerotonChopper:
    def __init__(self, name: str = TANGO_DEVICE):
        """Initialize the Celeroton chopper.

        :Args:
            name: Tango name of the device
        """
        self.chopper = DeviceProxy(name)

    def name(self) -> str:
        """Returns the name that identifies a device."""
        return self.chopper.name()

    def stop(self) -> bool:
        """Stops the chopper."""
        if not self.chopper.MotorRunning:
            return True
        try:
            self.chopper.Stop()
            while self.chopper.MotorRunning:
                time.sleep(0.1)
        except Exception:
            log.exception("Failed to stop Celeroton chopper")
            return False
        return True

    def start(self) -> bool:
        """Starts the chopper - conditions need to be valid."""
        try:
            self.chopper.Start()
            # TODO@piogor: insert a timeout loop for starting  # noqa: TD003 FIX002
            # when confirmation is needed
            # while not self.chopper.MotorRunning:
            #    time.sleep(0.1) noqa:ERA001
        except Exception:
            log.exception("Failed to start Celeroton chopper")
            return False
        return True

    def drop(self) -> bool:
        """Drops the chopper."""
        if self.chopper.Levitating == 1:
            try:
                self.chopper.TouchDown()
            except Exception:
                log.exception("Failed to drop Celeroton chopper")
                return False
            time.sleep(1)
        return True

    def park(self) -> None:
        """
        Parks the Celeroton chopper in a position (parking angle = 22) that is least
        probable to interfere with the beam.

        Consider in the future to use the FastShutterOpen Position and
        FastShutterClosedPosition.
        """
        self.stop()
        # disable external control - ignore sync signal
        if self.chopper.ExternalPositionCtrl:
            self.chopper.DisableExternalCtrlMode()
        self.drop()
        # set angle control mode - so that we can park at certain angle
        if self.chopper.MotorControlMode == "speed":
            self.chopper.SetAngleMode()
        self.chopper.Levitate()
        time.sleep(1)
        if self.start():
            self.chopper.AngularPositionReference = PARKING_ANGLE
            time.sleep(1)
        log.info(
            "Chopper parked with reference angle: %.2f",
            self.chopper.ActualAngularPosition,
        )

    def external_sync(self) -> None:
        """Sets up chopper to sync with the external trigger."""
        if self.chopper.MotorRunning:
            self.chopper.EnableExternalCtrlMode()
            self.chopper.SetSpeedMode()
        else:
            # set external control mode
            if not self.chopper.ExternalPositionCtrl:
                self.chopper.EnableExternalCtrlMode()
            # set speed mode
            if self.chopper.MotorControlMode == "angle":
                self.chopper.SetSpeedMode()
            self.drop()
            self.chopper.Levitate()
            time.sleep(2)
            self.start()

    def acknowledge_errors(self) -> bool:
        """Acknowledges all errors."""
        try:
            self.chopper.AckAllErrors()
        except Exception:
            log.exception("Failed to acknowledge Celeroton chopper errors")
            return False
        return True
