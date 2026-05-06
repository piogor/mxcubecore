from unittest.mock import Mock, patch

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.MAXIV.MicroMAX.beamline import Beamline


def _setup_beamline_obj(config: dict):
    tango_keystore_mock = Mock()
    tango_keystore_mock.get = Mock(side_effect=lambda key: config[key])

    hwr_beamline = patch.object(HWR, "beamline").start()
    hwr_beamline.tango_keystore = tango_keystore_mock

    return Beamline("dummy")


def test_sample_delivery_osc():
    """test 'OSC' sample delivery mode"""

    beamline = _setup_beamline_obj({"sample_delivery": "osc"})

    assert not beamline.is_hve_sample_delivery()
    assert not beamline.is_fixed_target_sample_delivery()
    assert beamline.sample_delivery == "osc"


def test_sample_delivery_hve():
    """test 'HVE' sample delivery mode"""

    beamline = _setup_beamline_obj({"sample_delivery": "hve"})

    assert beamline.is_hve_sample_delivery()
    assert not beamline.is_fixed_target_sample_delivery()
    assert beamline.sample_delivery == "hve"


def test_sample_delivery_fixed_target():
    """test 'Fixed-target' sample delivery mode"""

    beamline = _setup_beamline_obj({"sample_delivery": "fixed-target"})

    assert not beamline.is_hve_sample_delivery()
    assert beamline.is_fixed_target_sample_delivery()
    assert beamline.sample_delivery == "fixed-target"
