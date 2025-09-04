"""
MAXIV Beamline hardware object.

"""

# ruff: noqa: N999

from mxcubecore.HardwareObjects.Beamline import Beamline


class MAXIVBeamline(Beamline):
    def __init__(self, name):
        super(MAXIVBeamline, self).__init__(name)

    def init(self):
        super(MAXIVBeamline, self).init()

    def emulate(self, feature: str) -> bool:
        """Check if some feature should be emulated."""
        emulate = self.get_property("emulate", {})
        return emulate.get(feature, False)
