import logging
from enum import (
    Enum,
    unique,
)
from typing import TYPE_CHECKING

from mxcubecore.HardwareObjects import BeamInfo

if TYPE_CHECKING:
    from mxcubecore.HardwareObjects.MAXIV.BioMAX.beam_definer import BeamDefiner
from mxcubecore.HardwareObjects.abstract import AbstractBeam
from mxcubecore.utils.units import um_to_mm


@unique
class BeamShape(Enum):
    """Beam shape definitions"""

    UNKNOWN = "unknown"
    RECTANGULAR = "rectangular"
    ELIPTICAL = "ellipse"


@unique
class HardwareObjectState(Enum):
    """Enumeration of common states, shared between all HardwareObjects"""

    UNKNOWN = 0
    WARNING = 1
    BUSY = 2
    READY = 3
    FAULT = 4
    OFF = 5


class BIOMAXBeamInfo(BeamInfo.BeamInfo, AbstractBeam.AbstractBeam):
    """Beam information"""

    def __init__(self, name):
        BeamInfo.BeamInfo.__init__(self, name)
        self.beam_position = (0, 0)
        self._beam_width = None
        self._beam_height = None
        self._beam_shape = None
        self._beam_label = None
        self._beam_divergence = (None, None)
        self._beam_position_on_screen = [None, None]  # TODO move to sample_view
        self._beam_size_dict = {}
        self._beam_info_dict = {}
        self._beam_definer: BeamDefiner | None = None

    def init(self):
        BeamInfo.BeamInfo.init(self)
        self._beam_size_dict["aperture"] = [9999, 9999]
        self._beam_size_dict["slits"] = [9999, 9999]
        self._beam_position_on_screen = (687, 519)
        self._beam_divergence = (0, 0)
        self.beam_position = (0, 0)

        self.aperture_hwobj = self.get_object_by_role("aperture")

        if self.aperture_hwobj is not None:
            self.connect(
                self.aperture_hwobj,
                "value_changed",
                self.aperture_pos_changed,
            )
            ad = um_to_mm(self.aperture_hwobj.get_diameter_size())
            self._beam_size_dict["aperture"] = [ad, ad]
            self._beam_info_dict["label"] = self.aperture_hwobj.get_diameter_size()
        else:
            logging.getLogger("HWR").warning("BeamInfo: Aperture hwobj not defined")

        self.evaluate_beam_info()
        self.re_emit_values()
        self.emit("beamPosChanged", (self._beam_position_on_screen,))

    def evaluate_beam_info(self, *args):
        self.beam_info_dict["shape"] = "ellipse"
        current_aperture = float(self.aperture_hwobj.get_value())
        self._beam_width = um_to_mm(current_aperture)
        self.beam_info_dict["size_x"] = self._beam_width
        self._beam_height = um_to_mm(current_aperture)
        self.beam_info_dict["size_y"] = self._beam_height
        return self.beam_info_dict

    def get_beam_info_dict(self):
        """getting beam information

        Returns:
            dict: copy of beam_info_dict
        """
        self.evaluate_beam_info()
        self._beam_info_dict["label"] = self.aperture_hwobj.get_diameter_size()
        self.get_beam_shape()
        return self._beam_info_dict.copy()

    def get_slits_gap(self):
        """
        Returns: tuple with beam size in microns
        """
        self.evaluate_beam_info()
        return self._beam_size_dict["slits"]

    def get_value(self):
        """getting beam information, used by frontend

        Returns:
            list out of {size_x:0.1, size_y:0.1, shape:"rectangular"}
        """
        # return list(self.get_beam_info_dict().values())
        current_aperture = self.aperture_hwobj.get_diameter_size()

        return (
            um_to_mm(float(current_aperture)),
            um_to_mm(float(current_aperture)),
            BeamShape.ELIPTICAL,
            current_aperture,
        )

    def get_available_size(self):
        """getting the list of available diameter sizes for aperture.

        Args:
            None

        Returns:
            enum: diameter sizes of aperture
        """
        aperture_list = self.aperture_hwobj.get_diameter_size_list()
        return {"type": "enum", "values": aperture_list}

    def get_aperture_pos_name(self):
        """getting the position of aperture.

        Returns:
            str: current position as str
        """
        if self.aperture_hwobj:
            return self.aperture_hwobj.get_position_name()

    def get_beam_position(self):
        """getting beam position

        Args:
            None

        Returns:
            Tuple: beam position
        """

        return self.beam_position

    def set_value(self, value):
        """Setting new size for aperture diameter.

        Args:
            diameter_size (str): new size for aperture.

        Returns:
            None
        """
        self.aperture_hwobj.set_diameter_size(value)

    def get_beam_size(self):
        """getting beam size in millimeters

        Returns:
            list with two integers
        """
        self.evaluate_beam_info()
        _ap = um_to_mm(self.aperture_hwobj.get_diameter_size())
        return _ap, _ap

    def set_beam_position_on_screen(self, beam_x, beam_y):
        """Setting beam mark position on screen

        Args:
            beam_x (int): horizontal position in pixels
            beam_y (int): vertical position in pixels
        """
        self._beam_position_on_screen = (beam_x, beam_y)
        self.emit("beamPosChanged", (self._beam_position_on_screen,))

    def get_state(self) -> HardwareObjectState:
        return HardwareObjectState.READY
