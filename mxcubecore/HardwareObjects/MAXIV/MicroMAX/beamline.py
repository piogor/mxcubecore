"""Custom MicroMAX Beamline object.

Adds support for `sample_delivery` configurable, which
specifies the sample delivery mode for MXCuBE.

Following sample delivery modes are supported:

* osc - Oscillation sample delivery
* hve - HVE (injector) sample delivery

Example of `sample_delivery` configuration::

  configuration:
    sample_delivery: osc
"""

import mxcubecore.HardwareObjects.MAXIV.beamline
from mxcubecore import HardwareRepository as HWR


class Beamline(mxcubecore.HardwareObjects.MAXIV.beamline.Beamline):
    def __init__(self, name):
        super().__init__(name)

    @property
    def sample_delivery(self) -> str:
        HWR.beamline.tango_keystore.get("sample_delivery")

    def is_hve_sample_delivery(self) -> bool:
        """True when HVE sample delivery mode is configured."""
        sample_delivery = HWR.beamline.tango_keystore.get("sample_delivery")
        return sample_delivery.lower() == "hve"


    def is_fixed_target_sample_delivery(self) -> bool:
        """True when Fixed-target sample delivery mode is configured."""
        sample_delivery = HWR.beamline.tango_keystore.get("sample_delivery")
        return sample_delivery.lower() == "fixed-target"
