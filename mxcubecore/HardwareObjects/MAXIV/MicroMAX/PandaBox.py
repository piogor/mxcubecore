import logging
from pathlib import Path

import tango
from rich.table import Table

SCHEMA_PATH = "/data/staff/micromax/software/configs/pandabox_eh1"
PANDABOX_DEVICE = "b312a-eh1/tim/pandabox-01"
logger = logging.getLogger(__name__)


class PandaBox:
    """Control PandaBox schemas and attributes through Tango."""

    def __init__(self, device_name: str = PANDABOX_DEVICE):
        """Connect to the PandaBox Tango device.

        Args:
            device_name: Tango device name for the PandaBox.

        Raises:
            ConnectionError: If the Tango device connection fails.
        """
        try:
            self.pandabox = tango.DeviceProxy(device_name)
        except tango.DevFailed as ex:
            msg = "Connection to Pandabox failed with error."
            raise ConnectionError(msg) from ex

        self.pandabox.schemas_directory = SCHEMA_PATH

    def parse_schema_file(self, schema_file):
        """Parse a PandaBox schema file.

        Args:
            schema_file: Path to the schema file.

        Returns:
            Dictionary mapping schema keys to PandaBox block attributes.
        """
        with Path(schema_file).open() as schema:
            return self.schema_to_dict(schema)

    def schema_to_dict(self, schema):
        """Convert schema lines to a dictionary of PandaBox block attributes.

        Args:
            schema: Iterable of schema file lines.

        Returns:
            Dictionary mapping schema keys to valid PandaBox block attributes.
        """
        schema_dict = {}
        for line in schema:
            try:
                val1, val2 = line.rstrip("\n").split("=")
            except ValueError:  # noqa: PERF203
                pass
            else:
                if (
                    val2.isupper()
                    and val2.replace(".", "").isalnum()
                    and val2 not in ["ZERO", "ONE"]
                ):
                    schema_dict[val1] = val2

        return schema_dict

    def save_current_schema(self, file_name):
        """Save the currently active PandaBox schema.

        Args:
            file_name: Target schema file name.
        """
        self.pandabox.command_inout("save_schema", file_name)

    def load_schema_from_file(self, file_name):
        """Load a PandaBox schema from a file.

        Args:
            file_name: Source schema file name.
        """
        self.pandabox.command_inout("load_schema", file_name)

    def get_attribute(self, block_attr):
        """Get a PandaBox block attribute value.

        Args:
            block_attr: PandaBox block attribute name.

        Returns:
            Current value returned by the PandaBox device.
        """
        return self.pandabox.command_inout("get_attribute", block_attr)

    def set_attribute(self, block_attr, value):
        """Set a PandaBox block attribute value.

        Args:
            block_attr: PandaBox block attribute name.
            value: Value to assign to the attribute.
        """
        try:
            self.pandabox.command_inout("set_attribute", [block_attr, value])
        except Exception:
            logger.exception("Failed to set attribute value")

    def enable_current_schema(self, block_attr_list):
        """Enable schema blocks using the BITS block.

        Args:
            block_attr_list: PandaBox block attributes to enable.
        """
        for block_attr in block_attr_list:
            self.set_attribute(block_attr, 1)

    def disable_current_schema(self, block_attr_list):
        """Disable schema blocks using the BITS block.

        Args:
            block_attr_list: PandaBox block attributes to disable.
        """
        for block_attr in block_attr_list:
            self.set_attribute(block_attr, 0)

    def get_schemas_list(self):
        """Fetch available schemas and populate a Rich table."""
        schemas_list = self.pandabox.command_inout("list_schemas")

        table = Table()
        table.add_column("Schema name")

        for schema in schemas_list:
            table.add_row(schema)
