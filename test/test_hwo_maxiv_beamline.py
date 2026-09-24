from unittest.mock import Mock, PropertyMock

from mxcubecore.HardwareObjects.MAXIV.beamline import Beamline


def _setup_beamline_obj(mocker, config: dict):
    tango_keystore_mock = Mock()
    tango_keystore_mock.is_enabled = Mock(
        side_effect=lambda key: config.get(key, False)
    )

    hwr_beamline = Beamline("dummy")
    mocker.patch.object(
        Beamline,
        "tango_keystore",
        new_callable=PropertyMock,
        return_value=tango_keystore_mock,
    )
    return hwr_beamline


def test_emulate_default(mocker):
    """Test the `emulate()` method when the keystore reports no enabled features."""
    beamline = _setup_beamline_obj(mocker, {})

    assert not beamline.emulate("feature1")
    assert not beamline.emulate("feature2")


def test_emulate_enabled(mocker):
    """Test the `emulate()` method when
    some feature have been configured to be emulated.
    """

    beamline = _setup_beamline_obj(
        mocker,
        {
            "emulate_feature1": True,
            "emulate_feature2": False,
        },
    )

    assert beamline.emulate("feature1")
    assert not beamline.emulate("feature2")
    # The mock keystore reports unconfigured features as disabled.
    assert not beamline.emulate("feature3")
