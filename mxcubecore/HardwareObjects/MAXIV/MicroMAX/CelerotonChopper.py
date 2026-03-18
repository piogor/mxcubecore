import logging
import time

from tango import DeviceProxy

CELEROTON_CHOPPER = "b312-e/bcu/chopper"
PIEZO_MOTOR = "b312a-e07/ctl/pzcu-01"
PARKING_ANGLE = 22  # 22 is the value that aligns the cutouts with the passing hole

log = logging.getLogger("HWR")


class Celeroton:
    def __init__(self, name=CELEROTON_CHOPPER):
        """
        Initialize the Celeroton chopper

        :param name: Tango name of the device
        """
        self.chopper = DeviceProxy(name)

    def id(self):
        """
        Identifies a device

        :return: device name
        """
        return self.chopper.name()

    def stop(self):
        """
        Method stops the chopper
        """
        try:
            self.chopper.Stop()
            while self.chopper.MotorRunning:
                time.sleep(0.1)
        except Exception:
            log.exception("Failed to stop Celeroton chopper")
            return False

        return True

    def start(self):
        """
        Method starts the chopper - conditions need to be valid
        """
        try:
            self.chopper.Start()
            # to-do need to insert a timeout loop for starting
            # when confirmation is needed
            # while not self.chopper.MotorRunning:
            #    time.sleep(0.1) noqa:ERA001
        except Exception:
            log.exception("Failed to start Celeroton chopper")
            return False

        return True

    def park(self):
        """
        Method for parking the Celeroton chopper in a position that is least
        probable to interfere with the beam.

        Consider in the future to use the FastShutterOpen Position and
        FastShutterClosedPosition.
        """

        # stopping the motor
        if self.chopper.MotorRunning:
            self.stop()

        # disable external control - ignore sync signal
        if self.chopper.ExternalPositionCtrl:
            self.chopper.DisableExternalCtrlMode()

        if self.chopper.Levitating == 1:
            self.chopper.TouchDown()
            time.sleep(1)

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

    def external_sync(self):
        """
        Method to set up chopper to sync with the external trigger.
        """

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
            # drop and levitate chopper
            if self.chopper.Levitating == 1:
                self.chopper.TouchDown()
                time.sleep(1)

            self.chopper.Levitate()
            time.sleep(2)
            self.chopper.start()

    def acknowledge_errors(self):
        """
        Method acknowledges all errors
        """
        try:
            self.chopper.AckAllErrors()
        except Exception:
            log.exception("Failed to acknowledge Celeroton chopper errors")
            return False

        return True


class PiezoMotor:
    def __init__(self, name=PIEZO_MOTOR):
        """
        Initialize the piezo motor that moves chopper between slots

        :param name: Tango name of the device
        """
        self.piezomotor = DeviceProxy(name)
        self.slot = {
            1: 681000,
            2: 662000,
            3: 642000,
            4: 627000,
            5: 607000,
            6: 577000,
            7: 547000,
        }

    def move_to_slot(self, slot_num):
        """
        Moves the chopper to the appropriate slot.

        Slot 1 is the innermost, slot 6 is the outermost, and slot 7 is
        chopper out of the beam.
        """

        enc = self.slot[slot_num]  # retrieve the value from the dictionary

        # stopping the motor
        if self.chopper.MotorRunning:
            self.stop()

        # moving to requested slot
        if (
            abs(self.piezomotor.channel00_encoder - enc) < 500
        ):  # compare with the current position
            log.info("Already at desired slot")
        elif str(self.piezomotor.State()) == "ON":  # motor must be ready to move
            log.info("Moving to encoder count: %s", enc)
            self.piezomotor.channel00_position = enc

            while abs(self.piezomotor.channel00_encoder - enc) > 100:
                log.info(
                    "state: %s, position: %d",
                    self.piezomotor.channel00_state,
                    int(self.piezomotor.channel00_encoder),
                )
                time.sleep(1)
            log.info(
                "state: %s, position: %s",
                self.piezomotor.channel00_state,
                self.piezomotor.channel00_encoder,
            )
        else:
            log.info("Motor is off")
