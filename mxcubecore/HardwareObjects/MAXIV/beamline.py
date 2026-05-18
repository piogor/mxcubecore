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
from mxcubecore.HardwareObjects.MAXIV.EmailSender import EmailSender
from mxcubecore.HardwareObjects.MAXIV.NotificationSender import NotificationSender
from mxcubecore.HardwareObjects.MAXIV.TangoKeystore import TangoKeystore


class Beamline(mxcubecore.HardwareObjects.Beamline.Beamline):
    def emulate(self, feature: str) -> bool:
        """Check if some feature should be emulated."""
        emulate = self.get_property("emulate", {})
        return emulate.get(feature, False)

    @property
    def tango_keystore(self) -> TangoKeystore | None:
        return self.get_object_by_role("tango_keystore")

    @property
    def email_sender(self) -> EmailSender | None:
        return self.get_object_by_role("email_sender")

    @property
    def notification_sender(self) -> NotificationSender | None:
        return self.get_object_by_role("notification_sender")
