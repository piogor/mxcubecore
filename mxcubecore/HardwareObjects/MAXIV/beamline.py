"""Custom MAXIV Beamline object.

Adds support for ``emulate`` configurable, which allows to specify
features to be emulated at the beamline.

Emulation of following features are supported:

* safety_shutter - emulate safety shutter opening
* detector_cover - emulate detector cover opening
* detector_motion - emulate detector distance moves

Example of ``emulate`` configuration::

  configuration:
    emulate:
      safety_shutter: true
      detector_cover: true
      detector_motion: true
"""

import mxcubecore.HardwareObjects.Beamline
from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.MAXIV.EmailSender import EmailSender
from mxcubecore.HardwareObjects.MAXIV.NotificationSender import NotificationSender
from mxcubecore.HardwareObjects.MAXIV.TangoKeystore import TangoKeystore


class Beamline(mxcubecore.HardwareObjects.Beamline.Beamline):
    def emulate(self, feature: str) -> bool:
        """Check if some feature should be emulated."""
        feature = f"emulate_{feature}"
        enabled = self.tango_keystore.is_enabled(feature)
        if enabled:
            self.log.warning(f"emulation enabled for {feature}")
        return enabled

    def is_hve_sample_delivery(self) -> bool:
        """True when HVE sample delivery mode is configured."""
        sample_delivery = HWR.beamline.tango_keystore.get("sample_delivery")
        return sample_delivery.lower() == "hve"

    def is_fixed_target_sample_delivery(self) -> bool:
        """True when Fixed-target sample delivery mode is configured."""
        sample_delivery = HWR.beamline.tango_keystore.get("sample_delivery")
        return sample_delivery.lower() == "fixed-target"

    @property
    def tango_keystore(self) -> TangoKeystore | None:
        return self.get_object_by_role("tango_keystore")

    @property
    def email_sender(self) -> EmailSender | None:
        return self.get_object_by_role("email_sender")

    @property
    def notification_sender(self) -> NotificationSender | None:
        return self.get_object_by_role("notification_sender")
