import logging

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.BeamlineActions import AnnotatedCommand

DET_SAFE_POSITION = 900  # mm

#### TODO
# - If not in PLATE mode do not display plate related actions


class TestMacro:
    def __call__(self, *args, **kw):
        try:
            cmd = self.getCommandObject("testMacro")
            cmd(wait=True)
        except Exception:
            logging.getLogger("HWR").error("Cannot testMacro")


class BeamtimeEnd:
    def __call__(self, *args, **kw):
        """
        TBD
        """
        try:
            prepare_open_hutch = PrepareOpenHutch()
            prepare_open_hutch()
            cmd = self.getCommandObject("beamtime_end")
            cmd(wait=True)
        except Exception as ex:
            logging.getLogger("HWR").exception(
                "Cannot end beamtime. Error was {}".format(ex)
            )


class BeamtimeStart:
    def __call__(self, *args, **kw):
        """
        TBD: sardana macro not yet available in MicroMAX
        """
        try:
            cmd = self.getCommandObject("beamtime_start")
            cmd(wait=True)
        except Exception as ex:
            logging.getLogger("HWR").error(
                "Cannot start beamtime. Error was {}".format(ex)
            )


class OpenBeamlineShutters:
    def __call__(self, *args, **kw):
        """
        TBD: sardana macro not yet available in MicroMAX
        """
        try:
            cmd = self.getCommandObject("open_beamline_shutters")
            cmd(wait=True)
        except Exception as ex:
            logging.getLogger("HWR").error(
                "Cannot start beamtime. Error was {}".format(ex)
            )


class PrepareOpenHutch:
    """
    Prepare beamline for opening the hutch door

    Close safety shutter, close detector cover and move detector to a safe area
    """

    def __call__(self, *args, **kw):
        try:
            logging.getLogger("HWR").info(
                "Preparing experimental hutch for door openning."
            )
            if (
                HWR.beamline.safety_shutter is not None
                and HWR.beamline.safety_shutter.getShutterState() == "opened"
            ):
                logging.getLogger("HWR").info("Closing safety shutter...")
                HWR.beamline.safety_shutter.closeShutter()
                while HWR.beamline.safety_shutter.getShutterState() == "opened":
                    gevent.sleep(0.1)

            logging.getLogger("HWR").info("Closing detector cover...")
            HWR.beamline.collect.close_detector_cover()

            if HWR.beamline.detector is not None:
                logging.getLogger("HWR").info("Moving detector to safe area...")
                try:
                    HWR.beamline.detector.distance.set_value(DET_SAFE_POSITION)
                except Exception:
                    logging.getLogger("HWR").warning(
                        "Could not move detector to safe position"
                    )
        except Exception as ex:
            logging.getLogger("HWR").exception(
                "Could not PrepareOpenHutch. Error was {}".format(ex)
            )

        if HWR.beamline.sample_changer.is_powered():
            # if unmount_sample and HWR.beamline.sample_changer.get_loaded_sample() is not None:
            if HWR.beamline.sample_changer.get_loaded_sample() is not None:
                logging.getLogger("HWR").info("Unloading mounted sample.")
                HWR.beamline.sample_changer.unload(None, wait=True)

            if HWR.beamline.sample_changer.get_channel_value("PositionName") == "SOAK":
                logging.getLogger("HWR").info(
                    "Sample Changer was in SOAK, going to DRY"
                )
                HWR.beamline.sample_changer_maintenance.send_command("dry")

            gevent.sleep(1)
            HWR.beamline.sample_changer._wait_device_ready(300)
            if HWR.beamline.sample_changer.isPowered():
                logging.getLogger("HWR").info("Sample Changer to HOME")
                HWR.beamline.sample_changer_maintenance.send_command("home")
                gevent.sleep(1)
                HWR.beamline.sample_changer._wait_device_ready(30)

                logging.getLogger("HWR").info("Sample Changer CLOSING LID")
                HWR.beamline.sample_changer_maintenance.send_command("closelid1")
                gevent.sleep(1)
                HWR.beamline.sample_changer._wait_device_ready(10)

                logging.getLogger("HWR").info("Sample Changer POWER OFF")
                HWR.beamline.sample_changer_maintenance.send_command("powerOff")
        else:
            logging.getLogger("HWR").warning(
                "Cannot prepare Hutch openning, Isara is powered off"
            )


class PrepareForNewSample:
    """Prepare beamline for a new sample.

    Close safety shutter, close detector cover and move detector to a safe area
    """

    def __call__(self, *args, **kw):
        logging.getLogger("HWR").info("Preparing beamline for a new sample.")

        HWR.beamline.collect.close_detector_cover()
        logging.getLogger("HWR").info("Setting diffractometer in Transfer phase...")
        HWR.beamline.diffractometer.set_phase("Transfer", wait=False)

        if (
            HWR.beamline.safety_shutter is not None
            and self.safety_shutter.getShutterState() == "opened"
        ):
            logging.getLogger("HWR").info("Closing safety shutter...")
            HWR.beamline.safety_shutter.closeShutter()
            while HWR.beamline.safety_shutter.getShutterState() == "opened":
                gevent.sleep(0.1)

        if HWR.beamline.detector.distance is not None:
            logging.getLogger("HWR").info("Moving detector to safe area...")
            HWR.beamline.detector.distance.set_value(DET_SAFE_POSITION)


class CalculateFlux:
    """Calculate Flux."""

    def __call__(self, *args, **kw):
        logging.getLogger("HWR").info("Calculating Flux!")
        HWR.beamline.flux.calculate_flux()


class CheckBeam:
    def __call__(self, *args, **kw):
        """
        Check beam stability
        """
        try:
            cmd = self.getCommandObject("checkbeam")
            cmd(wait=True)
        except Exception as ex:
            logging.getLogger("HWR").error("Cannot check beam. Error was {}".format(ex))


class FocusBeam20:
    def __call__(self, *args, **kw):
        """
        Focus beam to 20x20
        """
        try:
            cmd = self.getCommandObject("focus_beam")
            cmd("20", wait=True)
        except Exception as ex:
            logging.getLogger("HWR").error("Cannot focus beam. Error was {}".format(ex))


class FocusBeam50:
    def __call__(self, *args, **kw):
        """
        Focus beam to 50x50
        """
        try:
            cmd = self.getCommandObject("focus_beam")
            cmd("50", wait=True)
        except Exception as ex:
            logging.getLogger("HWR").error("Cannot focus beam. Error was {}".format(ex))


class FocusBeam100:
    def __call__(self, *args, **kw):
        """
        Focus beam to 100x100
        """
        try:
            cmd = self.getCommandObject("focus_beam")
            cmd("100", wait=True)
        except Exception as ex:
            logging.getLogger("HWR").error("Cannot focus beam. Error was {}".format(ex))


class AbortMD3:
    def __call__(self, *args, **kw):
        """
        Abort MD3 activity
        """
        try:
            HWR.beamline.diffractometer.abort()
            omega = HWR.beamline.diffractometer.phi_motor_hwobj
            current_state = omega.get_state()
            logging.getLogger("HWR").info(
                "Current MD3 omega state is %s" % current_state
            )
            omega.updateMotorState(current_state)
        except Exception as ex:
            logging.getLogger("HWR").error("Cannot focus beam. Error was {}".format(ex))


class Anneal(AnnotatedCommand):
    def __init__(self, *args):
        super().__init__(*args)

    def anneal(self, data: float) -> None:
        logging.getLogger("user_level_log").info(
            f"Annealing for {data.exp_time} seconds"
        )
        try:
            HWR.beamline.diffractometer.wait_ready(10)
            if data.exp_time < 1:
                raise Exception("Time is too short for annealing, set 1s at least.")
            HWR.beamline.diffractometer.move_rex_out(wait=False)
            if data.exp_time >= 1:
                gevent.sleep(data.exp_time - 0.8)
            HWR.beamline.diffractometer.move_rex_in(wait=True)
            logging.getLogger("HWR").info("Annealing is done!")
        except Exception as ex:
            logging.getLogger("HWR").error(
                "Cannot anneal the sample. Error was {}".format(ex)
            )


class AlignBeam:
    def __call__(self, *args, **kw):
        try:
            HWR.beamline.beam_alignment_hwobj.execute_beam_alignment()
        except Exception as ex:
            logging.getLogger("HWR").error("Cannot align beam. Error was {}".format(ex))


class AlignAperture:
    def __call__(self, *args, **kw):
        try:
            HWR.beamline.beam_alignment_hwobj.execute_aperture_alignment()
        except Exception as ex:
            logging.getLogger("HWR").error(
                "Cannot align aperture. Error was {}".format(ex)
            )


class EmptyMount:
    def __call__(self, *args, **kw):
        if HWR.beamline.diffractometer.get_channel_value("SampleIsLoaded"):
            exception = Exception(
                "[SC][Empty mount] Cannot clear sample,"
                " there is a sample detected on the goniometer!"
            )
            logging.getLogger("HWR").error(exception)
            raise exception
        if HWR.beamline.sample_changer.is_powered():
            if HWR.beamline.sample_changer.get_channel_value("PositionName") == "SOAK":
                logging.getLogger("HWR").debug(
                    "[SC][Empty mount] Running command 'Abort'..."
                )
                HWR.beamline.sample_changer.execute_command("Abort")
                gevent.sleep(2)
                # We should not wait for the device to be ready here,
                # as it will never be ready,
                # because there is no sample on the diffractometer.
                logging.getLogger("HWR").debug(
                    "[SC][Empty mount] Running command 'ClearMemory'..."
                )
                HWR.beamline.sample_changer.execute_command("ClearMemory")
                gevent.sleep(1)
                logging.getLogger("HWR").debug(
                    "[SC][Empty mount] Running command 'Reset'..."
                )
                HWR.beamline.sample_changer.execute_command("Reset")
                HWR.beamline.sample_changer._wait_device_ready(10)
                HWR.beamline.diffractometer.last_centered_position = None
            else:
                if HWR.beamline.sample_changer._wait_device_ready(1):
                    logging.getLogger("HWR").error(
                        "[SC][Empty mount] Doesn't look like an empty mount,"
                        " please contact support!"
                    )
                else:
                    logging.getLogger("HWR").error(
                        "[SC][Empty mount] Sample Changer is drying,"
                        " please wait and try later."
                    )
        else:
            logging.getLogger("HWR").error(
                "[SC][Empty mount] Sample Changer power is off, please switch it on."
            )


class MovePlate(AnnotatedCommand):
    def __init__(self, *args):
        super().__init__(*args)

    def move_plate(self, row: str, col: int, drop: int) -> None:
        logging.getLogger("user_level_log").info(f"Move Plate {row} {col} {drop}")
        try:
            logging.getLogger("HWR").info(
                "Move Plate to position row: {}, col:{}, drop {}".format(row, col, drop)
            )
            row_list = ["A", "B", "C", "D", "E", "F", "G", "H"]
            try:
                row_index = HWR.beamline.diffractometer.plate_row_list.index(
                    row.upper()
                )
            except Exception as ex:
                logging.getLogger("HWR").error(
                    "could find the row value {} in the row_list".format(row)
                )
                raise Exception("please make sure the Row value is within A-H")
            params = "{}\t{}\t{}".format(row_index, int(col) - 1, int(drop) - 1)
            HWR.beamline.diffractometer.command_dict["startMovePlateToShelf"](params)
            HWR.beamline.diffractometer.wait_ready(30)
            current_pos = HWR.beamline.diffractometer.channel_dict[
                "PlateLocation"
            ].get_value()
            current_row = HWR.beamline.diffractometer.plate_row_list[
                int(current_pos[0])
            ]
            current_col = int(current_pos[1]) + 1
            logging.getLogger("HWR").info(
                "Current plate position row: {}, col:{}".format(
                    current_row, current_col
                )
            )
        except Exception as ex:
            logging.getLogger("HWR").error("Cannot move plate. Error was {}".format(ex))
