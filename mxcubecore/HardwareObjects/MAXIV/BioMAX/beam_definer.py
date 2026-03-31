"""
Beam definer implementation for BioMAX beamline.

.. code-block:: yaml

class: MAXIV.BioMAX.beam_definer.BeamDefiner
configuration:
    values:
        focus: (20, 5)
        um_20: (20, 20)
        um_50: (50, 50)
        um_100: (100, 100)
objects:
    beam_size_hor: beam_size_hor.yaml
    beam_size_ver: beam_size_ver.yaml
"""

from ast import literal_eval
from enum import Enum
from typing import TYPE_CHECKING

from mxcubecore.BaseHardwareObjects import HardwareObjectState
from mxcubecore.HardwareObjects.abstract.AbstractNState import (
    AbstractNState,
    BaseValueEnum,
)

if TYPE_CHECKING:
    from mxcubecore.HardwareObjects.SardanaMotor import SardanaMotor


class BeamDefiner(AbstractNState):
    """
    Class for the beam definer state of the BioMAX beamline.

    Acts as `definer` object for AbstractBeam.
    Is responsible for defining the beam focus,
    using two motors (beam_size_hor, beam_size_ver) for that purpose.
    """

    def __init__(self, name: str) -> None:
        """Initializer, sets up some internal variables."""
        super().__init__(name)
        # The beam focus is given in microns.
        self._beam_focus_horizontal: int | None = None
        self._beam_focus_vertical: int | None = None
        self._beam_size_ver: SardanaMotor | None = None
        self._beam_size_hor: SardanaMotor | None = None

    def init(self) -> None:
        """Initializes object; populates BeamDefiner.VALUES and connects the motors."""
        super().init()
        self._beam_size_ver = self.get_object_by_role("beam_size_ver")
        self._beam_size_hor = self.get_object_by_role("beam_size_hor")

        if self._beam_size_ver is None or self._beam_size_hor is None:
            err_msg = "BeamDefiner: Missing beam size motor(s)"
            raise RuntimeError(err_msg)

        self.connect(self._beam_size_hor, "stateChanged", self._on_motor_state_changed)
        self.connect(self._beam_size_ver, "stateChanged", self._on_motor_state_changed)
        self.update_state(self.get_state())

    def get_state(self) -> HardwareObjectState:
        """Returns the combined state of both beam size motors.

        BUSY if either motor is moving, FAULT if either has a fault,
        READY if both are ready, UNKNOWN otherwise.
        """
        if self._beam_size_hor is None or self._beam_size_ver is None:
            return HardwareObjectState.UNKNOWN

        states = {
            self._beam_size_hor.get_state(),
            self._beam_size_ver.get_state(),
        }

        if HardwareObjectState.BUSY in states:
            return HardwareObjectState.BUSY
        if HardwareObjectState.FAULT in states:
            return HardwareObjectState.FAULT
        if states == {HardwareObjectState.READY}:
            return HardwareObjectState.READY
        return HardwareObjectState.UNKNOWN

    def _on_motor_state_changed(self, _state: HardwareObjectState) -> None:
        """Callback for motor state changes; updates the BeamDefiner state.

            Called wheneer state of any of the beam size motors changes,
            to update the overall state of the BeamDefiner.

        Args:
            _state: The new state of the motor that triggered the callback (ignored).
        """
        self.update_state(self.get_state())

    def _set_value(self, value: BaseValueEnum) -> None:
        """Sets the beam focus to the given value.

        Args:
            value: The beam focus to set, derived from VALUES.
        """
        try:
            horizontal, vertical = value.value
        except ValueError as ex:
            err_msg = f"Invalid beam focus value: {value}"
            raise ValueError(err_msg) from ex
        self._beam_size_hor.set_value(horizontal)
        self._beam_size_ver.set_value(vertical)

    def get_value(self) -> BaseValueEnum:
        """Returns the current beam focus as a tuple (horizontal, vertical)."""

        if self._beam_size_hor is None or self._beam_size_ver is None:
            return BaseValueEnum.UNKNOWN

        horizontal = self._beam_size_hor.get_value()
        vertical = self._beam_size_ver.get_value()
        return self.value_to_enum((horizontal, vertical))

    def initialise_values(self) -> None:
        """Initialises self.VALUES with values from config

        Derived from AbstractNState, as it has troubles with parsing the
        tuple values from the config file.
        """
        values = self.get_property("values", {})
        values_dict = {name: literal_eval(focus) for name, focus in values.items()}
        base_values = {item.name: item.value for item in self.VALUES}
        self.VALUES = Enum("ValueEnum", base_values | values_dict)
