from unittest.mock import Mock, call, patch

from mxcubecore.HardwareObjects.MAXIV.MAXIVMD3 import NoPositionBookmarkedError
from mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions import (
    MeasureFlux,
    MoveToMD3SavedPosition,
    PrepareOpenHutch,
    SaveMD3Position,
)


def _assert_open_hutch_calls(hwr, log):
    """Checks that expected standard calls for 'prepare open hutch' where made."""

    # check calls on collect hardware object
    collect = hwr.beamline.collect
    collect.close_safety_shutter.assert_called_once()
    collect.close_detector_cover.assert_called_once()
    collect.move_detector_to_safe_position.assert_called_once()

    # check calls on diffractometer hardware object
    diffractometer = hwr.beamline.diffractometer
    diffractometer.wait_device_ready.assert_called_once()
    diffractometer.set_phase.assert_called_once_with("Transfer")

    # check logging calls
    log.info.assert_has_calls(
        [
            call("Preparing experimental hutch for door opening."),
            call("Setting diffractometer to transfer phase."),
            call("Moving detector to safe position."),
        ],
    )


def test_prepare_open_hutch_eiger():
    """Test PrepareOpenHutch beamline action with Eiger detector."""

    hwr = Mock()
    hwr.beamline.detector.get_property.return_value = "Eiger"

    log = Mock()

    with (
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.HWR", hwr),
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.log", log),
    ):
        bl_action = PrepareOpenHutch()
        bl_action()

    _assert_open_hutch_calls(hwr, log)
    # take pedestal should not be called for Eiger
    hwr.beamline.detector.pedestal.assert_not_called()


def test_prepare_open_hutch_jungfrau():
    """Test PrepareOpenHutch beamline action with Jungfrau detector."""

    hwr = Mock()
    hwr.beamline.detector.get_property.return_value = "JUNGFRAU"

    log = Mock()

    with (
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.HWR", hwr),
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.log", log),
    ):
        bl_action = PrepareOpenHutch()
        bl_action()

    _assert_open_hutch_calls(hwr, log)

    # check take pedestal operation was invoked
    hwr.beamline.detector.pedestal.assert_called_once()


def test_prepare_open_hutch_error():
    """Test a case where PrepareOpenHutch beamline action fails."""

    hwr = Mock()
    hwr.beamline.collect.close_safety_shutter.side_effect = Exception("dummy")

    log = Mock()

    with (
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.HWR", hwr),
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.log", log),
    ):
        bl_action = PrepareOpenHutch()
        bl_action()

    log.exception.assert_called_with(
        "Error preparing to open hutch.\nError was: '%s'",
        "dummy",
    )


def test_measure_flux():
    """Test MeasureFlux beamline action."""

    hwr = Mock()
    hwr.beamline.collect.get_instant_flux.return_value = 0.42

    log = Mock()

    with (
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.HWR", hwr),
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.log", log),
    ):
        bl_action = MeasureFlux()
        bl_action()
    log.info.assert_called_once_with("Flux at sample position is %.2e ph/s", 0.42)


def test_save_md3_position():
    """Test SaveMD3Position beamline action."""

    hwr = Mock()
    with patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.HWR", hwr):
        bl_action = SaveMD3Position()
        bl_action()

    hwr.beamline.diffractometer.bookmark_position.assert_called_once()


def test_move_to_md3_saved_position_ok():
    """Test the successful run of MoveToMD3SavedPosition beamline action."""
    hwr = Mock()

    with patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.HWR", hwr):
        bl_action = MoveToMD3SavedPosition()
        bl_action()

    hwr.beamline.diffractometer.goto_bookmarked_position.assert_called_once()


def test_move_to_md3_saved_position_no_bookmark():
    """Test running MoveToMD3SavedPosition when no bookmark exist."""

    hwr = Mock()
    hwr.beamline.diffractometer.goto_bookmarked_position.side_effect = (
        NoPositionBookmarkedError
    )

    log = Mock()

    with (
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.HWR", hwr),
        patch("mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline_actions.log", log),
    ):
        bl_action = MoveToMD3SavedPosition()
        bl_action()

    hwr.beamline.diffractometer.goto_bookmarked_position.assert_called_once()
    log.warning.assert_called_once_with("No MD3 position saved.")
