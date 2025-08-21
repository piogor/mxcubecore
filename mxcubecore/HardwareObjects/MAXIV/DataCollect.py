"""
Contains code shared between BioMAX and MicroMAX for implementing
a data collection hardware object.
"""

#
# Temporary disabling 'Invalid module name' check.
# We should make this module name ruff in the future.
#
# ruff: noqa: N999
#

import json
import socket
from typing import (
    Any,
    Callable,
    Optional,
)

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.HardwareObjects import TangoShutter
from mxcubecore.HardwareObjects.abstract.AbstractCollect import AbstractCollect
from mxcubecore.HardwareObjects.MAXIV import space_groups

# max time we wait for safety shutter to open, in seconds
SAFETY_SHUTTER_TIMEOUT = 5.0
# max time we wait for detector cover to open or close, in seconds
DETECTOR_COVER_TIMEOUT = 10.0


def _poll_until(condition: Callable, timeout: float, timeout_error_messge: str):
    """
    poll until condition() returns True, give up after timeout seconds
    """
    with gevent.Timeout(timeout, Exception(timeout_error_messge)):
        while not condition():
            gevent.sleep(0.01)


def open_tango_shutter(shutter: TangoShutter, timeout: float, name: str):
    def wait_until_open():
        _poll_until(
            lambda: shutter.is_open,
            timeout,
            f"could not open the {name}",
        )

    # timeout as 0 to not wait
    shutter.open(timeout=0)
    wait_until_open()


def close_tango_shutter(shutter: TangoShutter, timeout: float, name: str):
    def wait_until_closed():
        _poll_until(
            lambda: shutter.is_closed,
            timeout,
            f"could not close the {name}",
        )

    shutter.close(timeout=0)
    wait_until_closed()


def parse_unit_cell_params(params: str) -> list[Optional[float]]:
    """
    Parse the comma separated unit cell parameters string of following format:

        '<cell_a>,<cell_b>,<cell_c>,<cell_alpha>,<cell_beta>,<cell_gamma>'

    Returns cell parameters as a list of floats. Any omitted parameter is set to None.
    """

    def parse():
        for param in params.split(","):
            if param == "":
                yield None
            else:
                yield float(param)

    return list(parse())


class DataCollect(AbstractCollect, HardwareObject):
    DEFAULT_DETECTOR_SAFE_DISTANCE = 800

    def init(self):
        self.detector_cover = HWR.beamline.detector.cover
        self.detector_safe_possion = self.get_property(
            "detector_safe_distance",
            self.DEFAULT_DETECTOR_SAFE_DISTANCE,
        )
        self.flux = HWR.beamline.flux

    def get_flux(self):
        try:
            flux = self.flux.get_value()
        except Exception:
            self.log.exception("[HWR] Cannot retrieve flux value.")
            flux = -1
        return flux

    def get_measured_intensity(self):
        return float(self.get_flux())

    def move_detector_to_safe_position(self):
        """Move detector to a safe position.

        This is used to move the detector out of the way when changing samples.
        """
        self.log.info(
            "Collection: Moving detector to the safe position: %s",
            self.detector_safe_possion,
        )
        self.move_detector(self.detector_safe_possion)

    def open_safety_shutter(self):
        """
        send 'open' request to safety shutter and wait until it's open
        """
        if HWR.beamline.emulate("safety_shutter"):
            self.log.info("FAKE Opening the safety shutter.")
            return

        self.log.info("Opening the safety shutter.")
        open_tango_shutter(
            self.safety_shutter_hwobj,
            SAFETY_SHUTTER_TIMEOUT,
            "safety shutter",
        )

    def close_safety_shutter(self):
        """
        send 'close' request to safety shutter and wait until it's closed
        """
        self.log.info("Closing the safety shutter.")
        close_tango_shutter(
            self.safety_shutter_hwobj,
            SAFETY_SHUTTER_TIMEOUT,
            "safety shutter",
        )

    def open_detector_cover(self):
        """
        send 'open' request to the detector cover and wait until it's open
        """
        if HWR.beamline.emulate("detector_cover"):
            self.log.info("FAKE Opening detector cover.")
            return

        try:
            self.log.info("Opening the detector cover.")
            open_tango_shutter(
                self.detector_cover,
                DETECTOR_COVER_TIMEOUT,
                "detector cover",
            )
        except Exception as ex:
            self.log.exception("Could not open the detector cover")
            raise RuntimeError("[COLLECT] Could not open the detector cover.") from ex

    def close_detector_cover(self):
        """
        send 'close' request to the detector cover and wait until it's closed
        """
        try:
            self.log.info("Closing the detector cover")
            close_tango_shutter(
                self.detector_cover,
                DETECTOR_COVER_TIMEOUT,
                "detector cover",
            )
        except Exception:
            self.log.exception("Could not close the detector cover")

    def open_fast_shutter(self):
        """
        Descript. : important to make sure it's passed, as we
                    don't open the fast shutter in MXCuBE
        """
        try:
            self.diffractometer_hwobj.open_fast_shutter()
        except Exception:
            self.user_log.exception("Error opening fast shutter.")
            raise

    def close_fast_shutter(self):
        self.diffractometer_hwobj.close_fast_shutter()

    def get_mxcube_server_ip(self):
        """
        get the ip address of the mxcube server
        """
        hostname = socket.gethostname()
        return socket.gethostbyname(hostname)

    def get_header_appendix_sample_reference_dict(
        self,
        sample_reference_params: dict,
    ) -> dict | None:
        """
        build the 'sample_reference' dictionary for the header appendix

        returns the dictionary or None if no sample reference parameters specified
        """

        def filter_empty_vals(**key_vals) -> dict | None:
            """
            build dictionary with specified key-values,
            don't include key-value pairs where value is None or ""

            if the result is an empty dictionary, returns None
            """
            res = {k: v for k, v in key_vals.items() if v}
            if len(res) == 0:
                return None

            return res

        #
        # deal with space group parameters
        #
        space_group = sample_reference_params.get("spacegroup", "")
        if space_group != "":
            # convert to PDB style of space group names
            space_group = space_groups.get_full_name(space_group)

        #
        # deal with unit cell parameters
        #
        a, b, c, alpha, beta, gamma = parse_unit_cell_params(
            sample_reference_params.get("cell", ",,,,,"),
        )

        unit_cell = filter_empty_vals(
            a=a,
            b=b,
            c=c,
            alpha=alpha,
            beta=beta,
            gamma=gamma,
        )

        return filter_empty_vals(space_group=space_group, unit_cell=unit_cell)

    def _create_header_appendix(
        self,
        shape_id: str,
        dozor_dict: dict[str, Any] | None,
        row: int = 0,
        col: int = 0,
    ) -> dict[str, Any]:
        """Create collection metadata for the header appendix.

        It is meant to be later applied using ``setup_header_appendix`` method.
        It returns a dictionary with a shared portion of the parameters.
        Additional parameters may be added by the child classes.

        Returns:
            A dictionary of collection metadata (as strings)
            to be included into the Header Appendix section of the data files.
        """

        header_appendix = {
            "collect_dict": {
                "experiment_type": self.current_dc_parameters["experiment_type"],
                "row": row,
                "col": col,
                # assigning collection ID is not implemented (yet) for SSX tasks,
                # set 'col_id' to None if collection ID is not available
                "col_id": self.current_dc_parameters.get("collection_id"),
                "process_dir": self.current_dc_parameters["auto_dir"],
                "shape_id": shape_id,
                "mxcube_server": self.get_mxcube_server_ip(),
            },
        }

        #
        # dozor part
        #
        if dozor_dict:
            header_appendix["dozor_dict"] = dozor_dict

        #
        # add sample 'space group' and 'unit cell' parameters to header appendix,
        # if the user have specified them
        #
        sample_reference_dict = self.get_header_appendix_sample_reference_dict(
            self.current_dc_parameters["sample_reference"],
        )
        if sample_reference_dict:
            # user specified some sample reference params, add them to header appendix
            header_appendix["sample_reference"] = sample_reference_dict

        return header_appendix

    def setup_header_appendix(
        self,
        shape_id: str,
        dozor_dict: dict[str, Any] | None = None,
        row: int = 0,
        col: int = 0,
    ):
        """Set up the Header Appendix to be included into collection's data files.

        Creates json string, which contains meta-data for this data collection.
        Sends this string to detector hardware object, to be included into
        Header Appendix section of the data files for the next collection.

        Some of the meta-data is used by varius analysis pipelines.
        """

        header_appendix = self._create_header_appendix(
            shape_id,
            dozor_dict,
            row,
            col,
        )

        self.detector_hwobj.set_header_appendix(json.dumps(header_appendix))
