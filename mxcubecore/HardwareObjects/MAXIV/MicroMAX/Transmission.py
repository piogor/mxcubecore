import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mxcubecore.Command.Tango import TangoChannel
from mxcubecore.HardwareObjects.abstract.AbstractTransmission import (
    AbstractTransmission,
)

log = logging.getLogger("HWR")
user_log = logging.getLogger("user_level_log")


class Transmission(AbstractTransmission):
    def __init__(self, name: str) -> None:
        """Hardware object for transmission.

        It uses a Thorlabs Filter Wheel device to get transmission values.
        The transmission values are read from a property called "transmission_list",
        which correspond to the filter wheel positions.

        This is an example YAML configuration
        .. code-block:: yaml
            class: MAXIV.MicroMAX.MICROMAXTransmission
            configuration:
              read_only: true
              transmission_list:
                  - 51.1
                  - 26.1
                  - 6.82
                  - 0.465
                  - 0.0022
                  - 100.0
                  - 100.0
                  - 100.0
                  - 100.0
                  - 100.0
                  - 81.0
                  - 100.0

        With that config filter wheel position 1 will correspond to 51.1% transmission,
        position 2 to 26.1%, and so on.

        Args:
            name: Name of the hardware object, used by the base class.
        """
        super().__init__(name)
        self._position_channel: TangoChannel | None = None
        self._transmission_list: list[float] | None = None

    def init(self):
        super().init()
        self._position_channel = self.get_channel_object("Position")

        if self._position_channel is None or self._position_channel.device is None:
            _msg = "Position channel is not initialized. Check the configuration."
            log.error(_msg)
            raise ValueError(_msg)

        self._position_channel.connect_signal("update", self._update_transmission)
        self._nominal_limits = (0, 100)  # used by super().set_value
        self._transmission_list = self.get_property("transmission_list")

    def _update_transmission(self, position: int) -> None:
        """Update the transmission value based on the position.

        Args:
            position: Position of the filter wheel.
        """
        if self._position_channel is None:
            _msg = "Position channel is not initialized."
            raise ValueError(_msg)

        if not (1 <= position <= len(self._transmission_list)):
            _msg = f"""
            Position {position} is out of bounds.
            Must be between 1 and {len(self._transmission_list)}.
            """.strip()
            raise ValueError(_msg)
        # Checks if the value changed, if so emits `valueChanged`,
        # which is used to inform the frontend about the change.
        self.update_value(self._transmission_list[position - 1])

    def validate_value(self, value: float) -> bool:
        """Check if the value is within limits.

        Overrides the base class method.
        Called in super().set_value.

        Args:
            value: transmission value to validate.

        Returns:
            true if value is within limits, false otherwise.
        """
        if self._nominal_limits[0] <= value <= self._nominal_limits[1]:
            return True
        user_log.critical(
            "Transmission value %s is out of limits %s",
            value,
            self._nominal_limits,
        )
        return False

    def get_value(self) -> float | None:
        """Reads transmission value for current filter wheel position.
        Overrides the base class method.

        Returns:
            float: Transmission value corresponding to the current position.
            None: If the position channel is not initialized.
        """
        position = int(self._position_channel.get_value())
        return self._transmission_list[position - 1]

    def _set_value(self, value: float) -> None:
        """Sets new value for the transmission.
        In reality it sets the filter wheel position to one that is the closest
        to the desired transmission value.
        Overrides the base class method.

        Args:
            value: Target transmission value.
        """
        # We will want to set the position channel to the index of the transmission list
        # which corresponds to the value.
        # We will measure "closeness" to each of it's values and set the position
        closest_position = min(
            range(1, len(self._transmission_list) + 1),
            key=lambda position: abs(self._transmission_list[position - 1] - value),
        )

        if self._position_channel is None:
            _msg = "Position channel is not initialized."
            raise ValueError(_msg)
        new_transmission = self._transmission_list[closest_position - 1]
        user_log.info(
            "Setting transmission to closest available value: %s",
            new_transmission,
        )
        self._position_channel.set_value(closest_position)
