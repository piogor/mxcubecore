import argparse
import tango
from rich.table import Table


SCHEMA_PATH = "/data/staff/micromax/software/configs/pandabox_eh1"


class PandaBox():
    def __init__(self, device_name="b312a-eh1/tim/pandabox-01"):
        try:
            self.pandabox = tango.DeviceProxy(device_name)
            self.pandabox.schemas_directory = SCHEMA_PATH
        except Exception as ex:
            msg = f"Connection to Pandabox failed with error: {ex}"
            raise Exception(msg)

    def parse_schema_file(self, schema_file):
        with open(schema_file) as schema:
            return self.schema_to_dict(schema)

    def schema_to_dict(self, schema):
        schema_dict = {}
        for line in schema:
            try:
                val1, val2 = line.rstrip("\n").split("=")
                if (
                    val2.isupper()
                    and val2.replace(".", "").isalnum()
                    and val2 not in ["ZERO", "ONE"]
                ):
                    schema_dict[val1] = val2
            except ValueError:
                pass
        return schema_dict

    def save_current_schema(self, file_name):
        self.pandabox.command_inout("save_schema", file_name)

    def load_schema_from_file(self, file_name):
        self.pandabox.command_inout("load_schema", file_name)

    def get_attribute(self, block_attr):
        block_value = self.pandabox.command_inout("get_attribute", block_attr)
        return block_value

    def set_attribute(self, block_attr, value):
        try:
            self.pandabox.command_inout("set_attribute", [block_attr, value])
        except Exception as e:
            print("Failed to set attribute value:")

    def enable_current_schema(self, block_attr_list):
        """
        use BITS block to enable schema
        """
        for block_attr in block_attr_list:
            self.set_attribute(block_attr, 1)

    def disable_current_schema(self, block_attr_list):
        """
        use BITS block to disable schema
        """
        for block_attr in block_attr_list:
            self.set_attribute(block_attr, 0)

    def get_schemas_list(self):
        """
        Get list of schemas in the directory and print it in nice table.
        """
        schemas_list = pd.pandabox.command_inout("list_schemas")

        table = Table()
        table.add_column("Schema name")

        for schema in schemas_list:
            table.add_row(schema)

