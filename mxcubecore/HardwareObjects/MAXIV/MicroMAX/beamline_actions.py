import logging
import math
import time
from dataclasses import dataclass

from tango import DeviceProxy

# Temporary until tango_keystore package is updated to version
# with tag support
from tango_keystore import TangoKeystore

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractDiffractometer import (
    DiffractometerPhase,
)
from mxcubecore.HardwareObjects.BeamlineActions import AnnotatedCommand
from mxcubecore.HardwareObjects.MAXIV.MicroMAX.CelerotonChopper import CelerotonChopper
from mxcubecore.utils.units import kev_to_ev

user_log = logging.getLogger("user_level_log")
hwr_log = logging.getLogger("HWR")


def send_email(
    receivers: str, subject: str, content: str, attachments: list[str] | None = None
):
    """Send an email to the specified receivers.

     Args:
        receivers: A comma-separated string of email addresses to send the email to.
        subject: The subject of the email.
        content: The body content of the email.
        attachments: A list of file paths to attach to the email (optional).

    Raises:
        RuntimeError: If the email sender hardware object is not configured.
    """
    email_sender = HWR.beamline.email_sender
    try:
        email_sender.send_email(
            receivers=receivers,
            subject=subject,
            content=content,
            attachments=attachments,
        )
    except AttributeError as exc:
        msg = "Email sender hardware object is not configured"
        raise RuntimeError(msg) from exc
    except Exception:  # noqa: BLE001
        user_log.exception("Error while sending notification")


def send_notification(title: str, message: str):
    """Send a notification to the user.

     Args:
        title: The title of the notification.
        message: The message content of the notification.

    Raises:
        RuntimeError: If the notification sender hardware object is not configured.
    """
    notification_sender = HWR.beamline.notification_sender
    try:
        notification_sender.send_notification(title, message)
    except AttributeError as exc:
        msg = "Notification sender hardware object is not configured"
        raise RuntimeError(msg) from exc
    except Exception:  # noqa: BLE001
        user_log.exception("Error while sending notification")


class PrepareOpenHutch:
    """Prepare the beamline for opening the hutch door.

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
            collect = HWR.beamline.collect
            diffractometer = HWR.beamline.diffractometer
            detector = HWR.beamline.detector

            user_log.info("Preparing experimental hutch for door opening.")

            collect.close_fast_shutter()
            collect.close_detector_cover()

            if HWR.beamline.tango_keystore.is_enabled("laser_in_operation"):
                try:
                    # Ensure laser is stopped before opening the hutch
                    collect.stop_laser()
                    user_log.info("Switching off laser")
                    collect.move_out_laser()
                    user_log.info("Moving out laser")

                except Exception as ex:  # noqa: BLE001
                    user_log.info(f"Error when switching off laser {ex}")

            diffractometer.wait_device_ready()
            if HWR.beamline.is_hve_sample_delivery():
                # This is 'equivalent' of Transfer phase for HVE experiments
                user_log.info(
                    "Setting diffractometer to 'equivalent' of Transfer phase."
                )
                diffractometer.channel_dict["BeamstopPosition"].set_value("PARK")
                diffractometer.wait_device_ready()
                diffractometer.channel_dict["CapillaryPosition"].set_value("PARK")
            else:
                user_log.info("Setting diffractometer to Transfer phase.")
                diffractometer.set_phase(DiffractometerPhase.TRANSFER)
                if HWR.beamline.tango_keystore.is_enabled("serialx_chip"):
                    diffractometer.wait_ready(10)
                    diffractometer.omega_motor_hwobj.set_value(170)

            try:
                user_log.info("Moving detector to safe position.")
                # TODO@JieNan: we should do this properly # noqa: TD003,FIX002
                # and check if the hutch is searched
                collect.move_detector_to_safe_position()
            except Exception:  # noqa: BLE001
                user_log.warning("Couldn't move detector, maybe hutch is not searched")

            collect.close_safety_shutter()

            if collect.is_jungfrau():
                # make sure safety shutter is closed before pedestal
                time.sleep(1)
                user_log.info("Collecting Jungfrau pedestal.")
                detector.pedestal()

        except Exception as ex:  # noqa: BLE001
            # Explicitly add raised exception into the log message,
            # so that it is shown to the user in the beamline action UI log.
            user_log.exception(
                "Error preparing to open hutch.\nError was: '%s'", str(ex)
            )


class RecoverMD3:
    def __call__(self):
        """Restart MD3 and set the necessary omega limits."""
        diffractometer = HWR.beamline.diffractometer
        diffractometer.restart_md3(cold_restart=False)


class RecoverMD3Hard:
    def __call__(self):
        """Cold restart MD3 and set the necessary omega limits."""
        user_log.info("MD3 Cold restart, this takes 5 minutes; coffee break!")

        diffractometer = HWR.beamline.diffractometer
        diffractometer.restart_md3(cold_restart=True)
        user_log.info("MD3 restart done; coffee break is over!")


class StartChopper:
    def __call__(self):
        """Start the chopper in external sync mode."""
        chopper = CelerotonChopper()
        user_log.info("Starting chopper now")
        chopper.external_sync()


class CheckBeam:
    def __call__(self):
        """Check beam stability."""
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
            user_log.info(
                f"XBPM: {name}, total current: {total_current * 1e6:.2f} uA, "
                f"estimated flux at sample position: {flux:.2e} ph/s"
            )

            if "BCU" in name:
                full_flux = flux * 100.0 / transmission
                user_log.info(
                    f"Current transmission: {transmission:.2f}%, "
                    f"estimated full flux at BCU: {full_flux:.2e} ph/s"
                )


class MeasureFlux:
    def __call__(self):
        """Calculate flux at the sample position."""
        flux_at_sample = HWR.beamline.collect.get_instant_flux()
        user_log.info("Flux at sample position is %.2e ph/s", flux_at_sample)


class SaveMD3Position:
    def __call__(self):
        HWR.beamline.diffractometer.save_centring_positions()


class MoveToMD3SavedPosition:
    def __call__(self):
        HWR.beamline.diffractometer.goto_centered_position()


class EmptyMount:
    def __call__(self):
        isara = HWR.beamline.sample_changer

        user_log.info("Performing empty mount recovery sequence.")

        isara.execute_command("abort")
        isara.execute_command("ClearMemory")
        isara.execute_command("Reset")
        time.sleep(0.5)
        isara.execute_command("PowerOn")

        user_log.info("Recovery sequence completed.")


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
        user_log.info("Chip positions from alignment table")
        focus = diff.phix_motor_hwobj.get_value()
        hor = diff.phiz_motor_hwobj.get_value()
    else:
        user_log.info("Chip positions from centring table")
        focus = diff.focus_motor_hwobj.get_value()
        hor = HWR.beamline.sample_view.cent_vertical_pseudo_motor.get_value()

    return _ChipMotorPosition(hor, focus)


def _calc_omega_diff(start: _ChipMotorPosition, finish: _ChipMotorPosition) -> float:
    user_log.info(f"{start.focus=} - {finish.focus=}, {start.hor=} - {finish.hor=}")
    return math.atan((start.focus - finish.focus) / (start.hor - finish.hor)) * (
        180.0 / math.pi
    )


class StartChipAlignment:
    """Start the chip alignment procedure."""

    Position = None

    def __call__(self):
        # save current motor positions
        StartChipAlignment.Position = _get_chip_motor_pos()
        user_log.info("Chip alignment start position recorded.")


class AbortMD3:
    """Abort MD3."""

    def __call__(self):
        HWR.beamline.diffractometer.abort()
        user_log.info("Abort MD3")


class MoveInLaser:
    def __call__(self):
        HWR.beamline.collect.move_in_laser()
        user_log.info("Moving in laser")


class FinishChipAlignment:
    """Finish the chip alignment procedure.

    This action requires the start alignment action to have been run.
    """

    def __call__(self):
        if StartChipAlignment.Position is None:
            user_log.warning("No alignment start position available.")
            return

        diff = HWR.beamline.diffractometer

        # calculate how much omega angle need change, to align the chip
        omega_diff = _calc_omega_diff(
            StartChipAlignment.Position, _get_chip_motor_pos()
        )

        # rotate the chip along the omega axis
        curr_omega = diff.omega_motor_hwobj.get_value()
        try:
            diff.omega_motor_hwobj.set_value(curr_omega - omega_diff)
        except Exception as ex:  # noqa: BLE001
            msg = "Please adjust the sample manually!"
            user_log.error(msg)
            user_log.error(f"Cannot move to the aligned position {ex}")

        user_log.info(f"Adjusted Omega angle with {omega_diff:.3f} degrees.")

        # reset 'start' position, so it's not re-used by mistake
        StartChipAlignment.Position = None


def get_tag_dict(tag) -> dict:
    key_store = TangoKeystore(namespace=f"TangoKeystore_{tag}")
    all_keys = key_store.get_all()
    return {k: v for k, v in all_keys.items() if not k.startswith("_")}


class EnableSSX:
    def __call__(self):
        HWR.beamline.tango_keystore.put("ssx_mode", value=True)
        user_log.info("Enabling SSX_MODE")


class DisableSSX:
    def __call__(self):
        HWR.beamline.tango_keystore.put("ssx_mode", value=False)
        user_log.info("Disabling SSX_MODE")


class BeamtimeEnd:
    def __call__(self):
        receivers = HWR.beamline.tango_keystore.get("oncall")
        msg = "Beamtime End"
        send_email(receivers, "Beamtime End", msg)
        if HWR.beamline.is_sample_changer_used():
            if HWR.beamline.sample_changer.has_loaded_sample():
                user_log.info("Unmount sample...")
                HWR.beamline.sample_changer.unload()
            else:
                user_log.info("No sample mounted by sample changer, will not unload")
            if HWR.beamline.sample_changer_maintenance.position_name != "home":
                user_log.info("Send gripper to home")
                HWR.beamline.sample_changer_maintenance.send_command("home")
                HWR.beamline.sample_changer.wait_device_ready(30)
            user_log.info("Close lid")
            HWR.beamline.sample_changer_maintenance.send_command("closeLid")
            HWR.beamline.sample_changer.wait_device_ready(30)
            time.sleep(5)
            user_log.info("Power off")
            HWR.beamline.sample_changer_maintenance.send_command("PowerOff")
        else:
            user_log.info("Sample changer is not used")

        # end beamtime
        cmd = HWR.beamline.beamline_actions.get_command_object("beamtime_end")
        cmd(wait=True)


class MovePlate(AnnotatedCommand):
    def __init__(self, *args):
        super().__init__(*args)

    def move_plate(self, row: str, col: int, drop: int) -> None:
        logging.getLogger("user_level_log").info("Move Plate %s %s %s", row, col, drop)
        hwr_log.info(
            "Move Plate to position row: %s, col: %s, drop: %s", row, col, drop
        )
        try:
            row_index = HWR.beamline.diffractometer.plate_row_list.index(row.upper())
        except ValueError as ex:
            hwr_log.error(
                "Cannot move plate: could not find the row value %s in the row_list",
                row,
            )
            raise Exception("Please make sure the Row value is within A-H") from ex

        try:
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
                "Current plate position row: %s, col:%s", current_row, current_col
            )
        except Exception:
            hwr_log.exception("Cannot move plate.")
