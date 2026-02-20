import argparse
from pandablocks.blocking import BlockingClient
from pandablocks.commands import Get, Put, GetState, SetState
import os
import time
import pathlib
#from LoggingTool import *

SCHEMA_PATH = "/data/staff/micromax/software/configs/pandabox_eh1"


class PandaBox():
    def __init__(self, hostname = "172.16.230.66"):
        try:
            self.hostname = hostname
            self.pandabox = BlockingClient(self.hostname)
            self.pandabox.connect()
            #log_tool = LoggingTool()
            #self.logger = log_tool.logger
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
        cmd = f"/opt/conda/envs/mxcube/bin/pandablocks save {self.hostname} {file_name}"
        os.system(cmd)
        print(f"Current schema is saved to {file_name}")

    def load_schema_from_file(self, file_name):
        cmd = f"/opt/conda/envs/mxcube/bin/pandablocks load {self.hostname} {file_name}"
        os.system(cmd)

    def get_attribute(self, block_attr):
        return self.pandabox.send(Get(f"{block_attr}"))


    def set_attribute(self, block_attr, value, check_value = False):
        try:
            value_to_str = f"{value}"
            self.pandabox.send(Put(f"{block_attr}", value_to_str))
        except Exception as ex:
            raise Exception(f"Error while setting pandabox {ex}")
        current_value = self.get_attribute(block_attr)
        if check_value:
            if current_value == value_to_str:
                print(f"{block_attr} is set to {current_value} successfully")
            else:
                raise Exception(f"Failed to set {block_attr} to {value_to_str}, current value is {current_value}")
        else:
            print(f"{block_attr} is set to {current_value}, requested value is {value}")

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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description = "Script to handle micromax EH1 pandabox")
    parser.add_argument('--hostname', help="Host Name", type=str, default="172.16.230.66")

    # create sub-parser
    sub_parsers = parser.add_subparsers(dest='command', help='sub-command help')

    # create the parser for the "load" sub-command
    parser_load = sub_parsers.add_parser('load', help='Load panda schema')
    parser_load.add_argument('-n', '--name', type=str, help='schema name', required=True)

    # create the parser for the "list" sub-command
    parser_load = sub_parsers.add_parser('list', help='list panda schema')

    # create the parser for the "save" sub-command
    parser_load = sub_parsers.add_parser('save', help='Save current panda schema with name')
    parser_load.add_argument('-n', '--name', type=str, help='schema name', required=True)

    # create the parser for the "set" sub-command
    parser_load = sub_parsers.add_parser('get', help='Get attribute value')
    parser_load.add_argument('-a', '--attribute', type=str, help='attribute name', required=True)

    # create the parser for the "set" sub-command
    parser_load = sub_parsers.add_parser('set', help='Set attribute value')
    parser_load.add_argument('-a', '--attribute', type=str, help='attribute name', required=True)
    parser_load.add_argument('-v', '--value', type=str, help='attribute value', required=True)
    args = parser.parse_args()

    pd = PandaBox(args.hostname)
    if args.command == "load":
        schema_file = os.path.join(SCHEMA_PATH, f"{args.name}_schema.txt")
        pd.load_schema_from_file(schema_file)
    elif args.command == "save":
        schema_file = os.path.join(SCHEMA_PATH, f"{args.name}_schema.txt")
        pd.save_current_schema(schema_file)
    elif args.command == "list":
        tmp_list = pathlib.Path(SCHEMA_PATH)
        schema_list = tmp_list.glob("*_schema.txt")
        for schema in schema_list:
            schema_short = os.path.basename(schema).replace("_schema.txt","")
            print(schema_short)
    elif args.command == "get":
        attr = pd.get_attribute(args.attribute.upper())
        print(f"Attribute {args.attribute} value is {attr}")
    elif args.command == "set":
        pd.set_attribute(args.attribute.upper(), args.value)


