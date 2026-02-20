import logging
import math
from dataclasses import dataclass

from tango import DeviceProxy

from tango import DeviceProxy

from mxcubecore import HardwareRepository as HWR
from mxcubecore.utils.units import kev_to_ev

log = logging.getLogger("user_level_log")


class PrepareOpenHutch:
    """
    Prepare beamline for opening the hutch door.

    - close safety shutter
    - close detector cover
    - close fast shutter
    - move detector to a safe position
    - put MD3 into 'Transfer' phase in case of OSC delivery mode
    - move MD3's `BeamstopPosition` and `CapillaryPosition` to `PARK` in case of HVE
    - if jungfrau is used, take pedestal
    """

    def __call__(self):
        try:
            # Ensure laser is stopped before opening the hutch
            laser = HWR.beamline.get_object_by_role("laser")
            laser.disarm()

            collect = HWR.beamline.collect
            diffractometer = HWR.beamline.diffractometer
            detector = HWR.beamline.detector

            log.info("Preparing experimental hutch for door opening.")

            collect.close_fast_shutter()
            collect.close_safety_shutter()
            collect.close_detector_cover()

            diffractometer.wait_device_ready()
            if HWR.beamline.is_hve_sample_delivery():
                # This is 'equivalent' of Transfer phase for HVE experiments
                log.info("Setting diffractometer to 'equivalent' of Transfer phase.")
                diffractometer.channel_dict["BeamstopPosition"].set_value("PARK")
                diffractometer.channel_dict["CapillaryPosition"].set_value("PARK")
            else:
                log.info("Setting diffractometer to Transfer phase.")
                diffractometer.set_phase("Transfer")

            log.info("Moving detector to safe position.")
            collect.move_detector_to_safe_position()

            if detector.get_property("model") == "JUNGFRAU":
                log.info("Collecting Jungfrau pedestal.")
                detector.pedestal()

        except Exception as ex:
            # Explicitly add raised exception into the log message,
            # so that it is shown to the user in the beamline action UI log.
            log.exception("Error preparing to open hutch.\nError was: '%s'", str(ex))  # noqa: TRY401


class CheckBeam:
    def __call__(self):
        """
        Check beam stability
        """
        xbpms = {
            "DM3": DeviceProxy("b312a-o06/dia/xbpm-01"),
            "DM4": DeviceProxy("b312a-e01/dia/xbpm-01"),
            "BCU XBPM1": DeviceProxy("b312a-e04/dia/xbpm-01"),
            "BCU XBPM2": DeviceProxy("b312a-e04/dia/xbpm-02"),
        }
        energy = kev_to_ev(HWR.beamline.energy.get_value())
        transmission = HWR.beamline.transmission.get_value()
        for name, xbpm in xbpms.items():
            total_current = xbpm.S
            flux = total_current * (
                -0.534515 * energy**4
                - 43197.6 * energy**3
                + 5.13449e09 * energy**2
                - 4.39169e13 * energy
                + 1.14591e17
            )
            log.info(
                f"XBPM: {name}, total current: {total_current * 1e6:.2f} uA, "
                f"estimated flux at sample position: {flux:.2e} ph/s"
            )

            if "BCU" in name:
                full_flux = flux * 100.0 / transmission
                log.info(
                    f"Current transmission: {transmission:.2f}%, "
                    f"estimated full flux at BCU: {full_flux:.2e} ph/s"
                )


class MeasureFlux:
    def __call__(self):
        """
        calculate flux at sample position
        """
        flux_at_sample = HWR.beamline.collect.get_instant_flux()
        log.info("Flux at sample position is %.2e ph/s", flux_at_sample)


class SaveMD3Position:
    def __call__(self):
        HWR.beamline.diffractometer.save_centered_position()


class MoveToMD3SavedPosition:
    def __call__(self):
        HWR.beamline.diffractometer.goto_centered_position()


class EmptyMount:
    def __call__(self):
        isara = HWR.beamline.sample_changer

        log.info("Performing empty mount recovery sequence.")

        isara.execute_command("Reset")

        log.info("Recovery sequence completed.")


#
# Chip alignment beamline actions.
#
# Allows to align a chip orthogonal to the beam,
# by visually adjusting focus for each side of
# the chip.
#


@dataclass
class _ChipMotorPosition:
    """MD3 motor position used for chip alignment."""

    hor: float
    focus: float


def _get_chip_motor_pos():
    """Read motor position relevant for chip alignment."""

    diff = HWR.beamline.diffractometer

    if HWR.beamline.tango_keystore.is_enabled("ssx_mode"):
        log.info("Chip positions from alignment table")
        focus = diff.phix_motor_hwobj.get_value()
        hor = diff.phiz_motor_hwobj.get_value()
    else:
        log.info("Chip positions from centring table")
        focus = diff.focus_motor_hwobj.get_value()
        hor = diff.cent_vertical_pseudo_motor.get_value()

    return _ChipMotorPosition(hor, focus)


def _calc_omega_diff(start: _ChipMotorPosition, finish: _ChipMotorPosition) -> float:
    log.info(f"{start.focus=} - {finish.focus=}, {start.hor=} - {finish.hor=}")
    return math.atan((start.focus - finish.focus) / (start.hor - finish.hor)) * (
        180.0 / math.pi
    )


class StartChipAlignment:
    """Start the Chip alignment procedure."""

    Position = None

    def __call__(self):
        # save current motor positions
        StartChipAlignment.Position = _get_chip_motor_pos()
        log.info("Chip alignment start position recorded.")


class FinishChipAlignment:
    """Finish the Chip alignment procedure.

    This beamline action requires that 'start alignment' action have been run.
    """

    def __call__(self):
        if StartChipAlignment.Position is None:
            log.warning("No alignment start position available.")
            return

        diff = HWR.beamline.diffractometer

        # calculate how much omega angle need change, to align the chip
        omega_diff = _calc_omega_diff(
            StartChipAlignment.Position, _get_chip_motor_pos()
        )

        # rotate the chip along the omega axis
        curr_omega = diff.phi_motor_hwobj.get_value()
        diff.phi_motor_hwobj.set_value(curr_omega - omega_diff)

        log.info("Adjusted Omega angle with %d degrees.", omega_diff)

        # reset 'start' position, so it's not re-used by mistake
        StartChipAlignment.Position = None
