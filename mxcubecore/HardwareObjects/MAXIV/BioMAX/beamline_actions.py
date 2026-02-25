import logging

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.BeamlineActions import AnnotatedCommand

DET_SAFE_POSITION = 900  # mm

#### TODO
# - If not in PLATE mode do not display plate related actions

hwr_log = logging.getLogger("HWR")
user_log = logging.getLogger("user_level_log")


class TestMacro:
    def __call__(self, *args, **kw):
        try:
            cmd = HWR.beamline.beamline_actions.get_command_object("testMacro")
            cmd(wait=True)
        except Exception:
            hwr_log.exception("Cannot testMacro")


class BeamtimeEnd:
    def __call__(self, *args, **kw):
        """
        TBD
        """
        try:
            PrepareOpenHutch().__call__()
            cmd = HWR.beamline.beamline_actions.get_command_object("beamtime_end")
            cmd(wait=True)
        except Exception:
            hwr_log.exception("Cannot end beamtime.")


class BeamtimeStart:
    def __call__(self, *args, **kw):
        """
        TBD: sardana macro not yet available in MicroMAX
        """
        try:
            cmd = HWR.beamline.beamline_actions.get_command_object("beamtime_start")
            cmd(wait=True)
        except Exception:
            hwr_log.exception("Cannot start beamtime.")


class OpenBeamlineShutters:
    def __call__(self, *args, **kw):
        """
        TBD: sardana macro not yet available in MicroMAX
        """
        try:
            cmd = HWR.beamline.beamline_actions.get_command_object(
                "open_beamline_shutters"
            )
            cmd(wait=True)
        except Exception:
            hwr_log.exception("Cannot open beamline shutters.")


class CloseSafetyShutter:
    def __call__(self, *args, **kw):
        """
        Close safety shutter
        """
        try:
            hwr_log.info("Closing safety shutter")
            if HWR.beamline.safety_shutter.is_open:
                HWR.beamline.safety_shutter.close()
        except Exception:
            hwr_log.exception("Could not close safety shutter")


class OpenSafetyShutter:
    def __call__(self, *args, **kw):
        """
        Open safety shutter
        """
        try:
            hwr_log.info("Opening safety shutter")
            if HWR.beamline.safety_shutter.is_closed:
                HWR.beamline.safety_shutter.open()
        except Exception:
            hwr_log.exception("Could not open safety shutter")


class CloseDetectorCover:
    def __call__(self, *args, **kw):
        """
        Close detector cover
        """
        try:
            hwr_log.info("Closing the detector cover")
            HWR.beamline.detector.cover.close()
        except Exception:
            hwr_log.exception("Could not close the detector cover.")


class OpenDetectorCover:
    def __call__(self, *args, **kw):
        """
        Open detector cover
        """
        try:
            hwr_log.info("Opening the detector cover")
            HWR.beamline.detector.cover.open()
        except Exception:
            hwr_log.exception("Could not open the detector cover.")


class PrepareOpenHutch:
    """
    Prepare beamline for opening the hutch door

    Close safety shutter, close detector cover and move detector to a safe area
    """

    def __call__(self, *args, **kw):
        try:
            hwr_log.info("Preparing experimental hutch for door openning.")
            if HWR.beamline.safety_shutter.is_open:
                hwr_log.info("Closing safety shutter...")
                HWR.beamline.safety_shutter.close()
                while HWR.beamline.safety_shutter.is_open:
                    gevent.sleep(0.1)

            hwr_log.info("Closing detector cover...")
            close_det_cover = CloseDetectorCover().__call__()

            hwr_log.info(f"Moving detector to safe distance {DET_SAFE_POSITION} ...")
            try:
                HWR.beamline.detector.detector_distance.set_value(DET_SAFE_POSITION)
            except Exception:
                hwr_log.warning("Could not move detector to safe position")
        except Exception as ex:
            hwr_log.exception("Could not PrepareOpenHutch.")
            user_log.critical("Failed to run PrepareOpenHutch")

        if HWR.beamline.sample_changer.is_powered():
            # if unmount_sample and HWR.beamline.sample_changer.get_loaded_sample() is not None:
            if HWR.beamline.sample_changer.get_loaded_sample() is not None:
                hwr_log.info("Unloading mounted sample.")
                HWR.beamline.sample_changer.unload(None, wait=True)

            if HWR.beamline.sample_changer.get_channel_value("PositionName") == "SOAK":
                hwr_log.info("Sample Changer was in SOAK, going to DRY")
                HWR.beamline.sample_changer_maintenance.send_command("dry")

            gevent.sleep(1)
            HWR.beamline.sample_changer._wait_device_ready(300)
            if HWR.beamline.sample_changer.is_powered():
                hwr_log.info("Sample Changer to HOME")
                HWR.beamline.sample_changer_maintenance.send_command("home")
                gevent.sleep(1)
                HWR.beamline.sample_changer._wait_device_ready(30)

                hwr_log.info("Sample Changer CLOSING LID")
                HWR.beamline.sample_changer_maintenance.send_command("closeLid")
                gevent.sleep(1)
                HWR.beamline.sample_changer._wait_device_ready(10)
        else:
            hwr_log.warning("Cannot prepare Hutch openning, Isara is powered off")


class SaveCentredPosition:
    """Save the current centered position of the beamline."""

    def __call__(self, *args, **kw):
        hwr_log.info("Saving centered position...")
        HWR.beamline.diffractometer.save_centered_position()


class PrepareForNewSample:
    """Prepare beamline for a new sample.

    Close safety shutter, close detector cover and move detector to a safe area
    """

    def __call__(self, *args, **kw):
        hwr_log.info("Preparing beamline for a new sample.")

        CloseDetectorCover().__call__()

        hwr_log.info("Setting diffractometer in Transfer phase...")
        HWR.beamline.diffractometer.set_phase_transfer()

        if HWR.beamline.safety_shutter.is_open:
            hwr_log.info("Closing safety shutter...")
            HWR.beamline.safety_shutter.close()
            while HWR.beamline.safety_shutter.is_open:
                gevent.sleep(0.3)

        hwr_log.info("Moving detector to safe area...")
        HWR.beamline.detector.detector_distance.set_value(DET_SAFE_POSITION)


class CalculateFlux:
    """Calculate Flux."""

    def __call__(self, *args, **kw):
        hwr_log.info("Calculating Flux!")
        HWR.beamline.flux.calculate_flux()


class CheckBeam:
    def __call__(self, *args, **kw):
        """
        Check beam stability
        """
        try:
            cmd = HWR.beamline.beamline_actions.get_command_object("checkbeam")
            cmd(wait=True)
        except Exception as ex:
            hwr_log.exception("Cannot check beam.")


class FocusBeam20:
    def __call__(self, *args, **kw):
        """
        Focus beam to 20x20
        """
        try:
            cmd = HWR.beamline.beamline_actions.get_command_object("focus_beam")
            cmd("20")
        except Exception as ex:
            hwr_log.exception("Cannot focus beam.")


class FocusBeam50:
    def __call__(self, *args, **kw):
        """
        Focus beam to 50x50
        """
        try:
            cmd = HWR.beamline.beamline_actions.get_command_object("focus_beam")
            cmd("50")
        except Exception as ex:
            hwr_log.exception("Cannot focus beam.")


class FocusBeam100:
    def __call__(self, *args, **kw):
        """
        Focus beam to 100x100
        """
        try:
            cmd = HWR.beamline.beamline_actions.get_command_object("focus_beam")
            cmd("100")
        except Exception as ex:
            hwr_log.exception("Cannot focus beam.")


class AbortMD3:
    def __call__(self, *args, **kw):
        """
        Abort MD3 activity
        """
        try:
            HWR.beamline.diffractometer.abort()
            gevent.sleep(0.5)
            omega = HWR.beamline.diffractometer.phi_motor_hwobj
            current_state = omega.get_state()
            hwr_log.info(f"Current MD3 omega state is {current_state}")
            omega.updateMotorState(current_state)
        except Exception as ex:
            hwr_log.exception("Cannot focus beam. Error was {}".format(ex))


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
            hwr_log.info("Annealing is done!")
        except Exception as ex:
            hwr_log.exception("Cannot anneal the sample.")


class AlignBeam:
    def __call__(self, *args, **kw):
        try:
            HWR.beamline.beam_alignment_hwobj.execute_beam_alignment()
        except Exception as ex:
            hwr_log.exception("Cannot align beam.")


class AlignAperture:
    def __call__(self, *args, **kw):
        try:
            HWR.beamline.beam_alignment_hwobj.execute_aperture_alignment()
        except Exception as ex:
            hwr_log.exception("Cannot align aperture.")


class EmptyMount:
    def __call__(self, *args, **kw):
        if HWR.beamline.diffractometer.get_channel_value("SampleIsLoaded"):
            exception = Exception(
                "[SC][Empty mount] Cannot clear sample,"
                " there is a sample detected on the goniometer!"
            )
            hwr_log.error(exception)
            raise exception
        if HWR.beamline.sample_changer.is_powered():
            if HWR.beamline.sample_changer.get_channel_value("PositionName") == "SOAK":
                hwr_log.debug("[SC][Empty mount] Running command 'Abort'...")
                HWR.beamline.sample_changer.execute_command("Abort")
                gevent.sleep(2)
                # We should not wait for the device to be ready here,
                # as it will never be ready,
                # because there is no sample on the diffractometer.
                hwr_log.debug("[SC][Empty mount] Running command 'ClearMemory'...")
                HWR.beamline.sample_changer.execute_command("ClearMemory")
                gevent.sleep(1)
                hwr_log.debug("[SC][Empty mount] Running command 'Reset'...")
                HWR.beamline.sample_changer.execute_command("Reset")
                HWR.beamline.sample_changer._wait_device_ready(10)
                HWR.beamline.diffractometer.last_centered_position = None
            else:
                if HWR.beamline.sample_changer._wait_device_ready(1):
                    hwr_log.error(
                        "[SC][Empty mount] Doesn't look like an empty mount,"
                        " please contact support!"
                    )
                else:
                    hwr_log.error(
                        "[SC][Empty mount] Sample Changer is drying,"
                        " please wait and try later."
                    )
        else:
            hwr_log.error(
                "[SC][Empty mount] Sample Changer power is off, please switch it on."
            )


class MovePlate(AnnotatedCommand):
    def __init__(self, *args):
        super().__init__(*args)

    def move_plate(self, row: str, col: int, drop: int) -> None:
        logging.getLogger("user_level_log").info(f"Move Plate {row} {col} {drop}")
        try:
            hwr_log.info(
                "Move Plate to position row: {}, col:{}, drop {}".format(row, col, drop)
            )
            row_list = ["A", "B", "C", "D", "E", "F", "G", "H"]
            try:
                row_index = HWR.beamline.diffractometer.plate_row_list.index(
                    row.upper()
                )
            except Exception as ex:
                hwr_log.error("could find the row value {} in the row_list".format(row))
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
            hwr_log.info(
                "Current plate position row: {}, col:{}".format(
                    current_row, current_col
                )
            )
        except Exception as ex:
            hwr_log.exception("Cannot move plate.")
