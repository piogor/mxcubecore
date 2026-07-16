"""
Contains code shared between BioMAX and MicroMAX for implementing
a data collection hardware object.
"""

import dataclasses
import json
import pathlib
import socket
import subprocess
from typing import (
    Any,
    Callable,
    Optional,
)

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.HardwareObjects.abstract.AbstractCollect import AbstractCollect
from mxcubecore.HardwareObjects.MAXIV import space_groups
from mxcubecore.HardwareObjects.TangoShutter import TangoShutter

# max time we wait for safety shutter to open, in seconds
SAFETY_SHUTTER_TIMEOUT = 5.0
# max time we wait for detector cover to open or close, in seconds
DETECTOR_COVER_TIMEOUT = 10.0
# max time to wait for MD3 to reach ready state
MD3_READY_TIMEOUT = 10


@dataclasses.dataclass
class _FilesInfo:
    """Names and paths for files and images.

    These are the shorthands used in the following descriptions:

    * ``{Line}`` stands for the name of the beamline
    * ``{Prop}`` stands for the proposal
    * ``{Sess}`` stands for the session
    * ``{Prot}`` stands for the protein acronym
    * ``{Samp}`` stands for the sample name
    * ``{Run}`` stands for the run number
    * ``{Frame}`` stands for the frame number (padded with zeroes up to 6 digits)

    Attributes:
        archive_directory_path:
            Full path to archive directory:
            ``/data/staff/.../{Line}/{Prop}/{Sess}/raw/{Prot}/{Prot}-{Samp}/``
        h5_name:
            File name of the raw H5 file:
            ``{Prot}-{Samp}_{Run}_{Frame}_master.h5``
        jpeg_path:
            Full path to JPEG image:
            ``{archive_directory_path}/{Prot}-{Samp}_{Run}_{Frame}.jpeg``
        raw_directory_path:
            Full path to directory containing raw H5 file:
            ``/data/visitors/{Line}/{Prop}/{Sess}/raw/{Prot}/{Prot}-{Samp}/``
        thumbnail_path:
            Full path to thumbnail JPEG image:
            ``{archive_directory_path}/{Prot}-{Samp}_{Run}_{Frame}.thumb.jpeg``
    """

    archive_directory_path: str
    h5_name: str
    jpeg_path: str
    raw_directory_path: str
    thumbnail_path: str


def _poll_until(condition: Callable, timeout: float, timeout_error_messge: str):
    """Poll until condition() returns True, give up after timeout seconds"""
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
    """Parse the comma separated unit cell parameters string of following format:

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
    """Data collection for MAX IV."""

    _GENERATE_DIFFRACTION_IMAGES_SCRIPT = (
        "/mxn/groups/sw/mxsw/mxcube_scripts/generate_thumbnail"
    )

    _HPC_FE_HOST = "clu0-fe-2"

    DEFAULT_DETECTOR_SAFE_DISTANCE = 800

    def init(self):
        super().init()

        self.detector_cover = HWR.beamline.detector.cover
        self.detector_safe_position = self.get_property(
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
            self.detector_safe_position,
        )
        self.move_detector(self.detector_safe_position)

    def open_safety_shutter(self):
        """Send 'open' request to safety shutter and wait until it's open"""
        if HWR.beamline.tango_keystore.is_true("emulate_safety_shutter"):
            self.log.info("FAKE Opening the safety shutter.")
            return

        self.log.info("Opening the safety shutter.")
        open_tango_shutter(
            self.safety_shutter_hwobj,
            SAFETY_SHUTTER_TIMEOUT,
            "safety shutter",
        )

    def close_safety_shutter(self):
        """Send 'close' request to safety shutter and wait until it's closed"""
        if HWR.beamline.tango_keystore.is_true("emulate_safety_shutter"):
            self.log.info("FAKE closing the safety shutter.")
            return

        self.log.info("Closing the safety shutter.")
        close_tango_shutter(
            self.safety_shutter_hwobj,
            SAFETY_SHUTTER_TIMEOUT,
            "safety shutter",
        )

    def open_detector_cover(self):
        """Send 'open' request to the detector cover and wait until it's open"""
        if HWR.beamline.tango_keystore.is_true("emulate_detector_cover"):
            self.log.info("FAKE Opening the detector cover.")
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
        """Send 'close' request to the detector cover and wait until it's closed"""
        if HWR.beamline.tango_keystore.is_true("emulate_detector_cover"):
            self.log.info("FAKE closing the detector cover.")
            return
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
        try:
            self.diffractometer_hwobj.open_fast_shutter()
        except Exception:
            self.user_log.exception("Error opening fast shutter.")
            raise

    def close_fast_shutter(self):
        self.diffractometer_hwobj.close_fast_shutter()

    def get_mxcube_server_ip(self):
        hostname = socket.gethostname()
        return socket.gethostbyname(hostname)

    def get_header_appendix_sample_reference_dict(
        self,
        sample_reference_params: dict,
    ) -> dict | None:
        """Build the 'sample_reference' dictionary for the header appendix

        Returns
            Dictionary, None if no sample reference parameters specified
        """

        def filter_empty_vals(**key_vals) -> dict | None:
            """Build dictionary with specified key-values,
            don't include key-value pairs where value is None or ""

            Returns:
                Dictionary without empty values
                None if the result is an empty dictionary
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

    def store_image_in_lims(
        self,
        frame_number: int,
        motor_position_id: int | None = None,
    ) -> None:
        # This is an override of ``AbstractCollect``.
        # This is not clear why this method is part of the abstract API,
        # since it does not seem to be used anywhere from outside the instances.
        # Anyway, here we give it a (reasonable?) implementation.

        collection = self.current_dc_parameters
        if collection:
            files_info = self._compute_files_info(collection, frame_number)

            self._store_image_in_lims(
                collection,
                files_info,
                frame_number,
                motor_position_id,
            )

    def _store_image_in_lims_by_frame_num(self, frame):
        # Dont save mesh first and last images
        # Mesh images (best positions) are stored after data analysis
        # MAYBE TODO: fix store_image_in_lims_by_frame_num method for nimages>1"
        pass

    def _post_collection_store_image(self, collection: dict | None = None) -> None:
        """Generate and store diffraction images and store them in the LIMS system.

        This method processes the first image of a data collection, stores it in
        jpeg format with its thumbnail (reduced size image). Provide the location
        of images to the Laboratory Information Management System (LIMS).If no
        collection is provided, it defaults to using the current data collection
        parameters.

        Args:
            collection:
                A dictionary containing data collection parameters.
                If not provided, the method uses ``self.current_dc_parameters``.
        """

        if collection is None:
            collection = self.current_dc_parameters

        self._store_diffraction_images(collection, 1)

    def _store_diffraction_images(
        self,
        collection: dict,
        frame_number: int,
    ) -> None:
        """Generate diffraction images and store them in LIMS.

        Create diffraction images for the specified frame, as JPEGs.
        Both a full-size and a thumbnail images are created.
        Upload created images to LIMS, connecting them to specified data collection ID.
        """

        files_info = self._compute_files_info(collection, frame_number)
        self.log.debug("Computed info for file names and paths: %s", files_info)

        self.log.debug("Storing image in LIMS for frame #%d", frame_number)
        try:
            self._store_image_in_lims(collection, files_info, frame_number)
        except Exception:
            self.log.exception(
                "Could not store image in LIMS for frame #%d, collection: %s",
                frame_number,
                collection,
            )

        self.log.debug("Generating diffraction images for frame #%d", frame_number)
        file_name = collection["fileinfo"]["filename"]
        try:
            self._generate_diffraction_images(file_name, files_info, frame_number)
        except Exception:
            self.log.exception(
                "Could not generate diffraction images for frame #%d, collection: %s",
                frame_number,
                collection,
            )

    def _compute_files_info(
        self,
        collection: dict,
        frame_number: int,
    ) -> _FilesInfo:
        """Compute files info (names and paths) based on collection information.

        Args:
            collection: Collection dictionary containing file information.
            frame_number: Frame number to update the filenames for.
        """

        file_info = collection["fileinfo"]

        raw_directory_path = file_info["directory"]

        file_template = file_info["template"]
        h5_name = file_template.replace("_master", f"_{frame_number:06d}_master")

        archive_directory_path = file_info["archive_directory"]
        if archive_directory_path:
            jpeg_name = h5_name.replace("_master.h5", ".jpeg")
            jpeg_path = str(pathlib.Path(archive_directory_path, jpeg_name))

            thumbnail_name = h5_name.replace("_master.h5", ".thumb.jpeg")
            thumbnail_path = str(pathlib.Path(archive_directory_path, thumbnail_name))

        return _FilesInfo(
            archive_directory_path=archive_directory_path,
            h5_name=h5_name,
            jpeg_path=jpeg_path,
            raw_directory_path=raw_directory_path,
            thumbnail_path=thumbnail_path,
        )

    def _store_image_in_lims(
        self,
        collection: dict,
        files_info: _FilesInfo,
        frame_number: int,
        motor_position_id: int | None = None,
    ) -> None:
        lims = HWR.beamline.lims
        if lims.is_connected():
            lims_image = {
                "dataCollectionId": collection["collection_id"],
                "fileLocation": files_info.raw_directory_path,
                "fileName": files_info.h5_name,
                "imageNumber": frame_number,
                "machineMessage": self.get_machine_message(),
                "measuredIntensity": self.get_measured_intensity(),
                "synchrotronCurrent": self.get_machine_current(),
                "temperature": self.get_cryo_temperature(),
            }

            if files_info.archive_directory_path:
                lims_image["jpegFileFullPath"] = files_info.jpeg_path
                lims_image["jpegThumbnailFileFullPath"] = files_info.thumbnail_path

            if motor_position_id:
                lims_image["motorPositionId"] = motor_position_id

            self.log.debug(
                "Storing LIMS image for frame #%d: %s",
                frame_number,
                lims_image,
            )

            try:
                lims.store_image(lims_image)
            except Exception:
                self.log.exception(
                    "Could not store image in LIMS for frame #%d: %s",
                    frame_number,
                    lims_image,
                )

        # Temporary fix for permission issues with ISPyB
        if files_info.archive_directory_path:
            session_dir = pathlib.Path(files_info.archive_directory_path).parents[2]
            try:
                session_dir.chmod(0o777)
            except Exception:
                self.log.exception(
                    "Could not change permissions on storage for ISPyB: %s",
                    session_dir,
                )

    def _generate_diffraction_images(
        self,
        data_path: str,
        files_info: _FilesInfo,
        frame_number: int,
    ) -> None:
        """Build command to run diffraction images generation script on HPC cluster.

        Args:
            data_path: Path to the data file - collection .h5 master file.
            image_paths: Paths to images to be created.
            frame_number: Frame number to generate the diffraction images for.
        """
        command: list[str] = [
            self._GENERATE_DIFFRACTION_IMAGES_SCRIPT,
            data_path,
            str(frame_number),
            files_info.jpeg_path,
            files_info.thumbnail_path,
        ]
        self.log.debug(
            "Generating diffraction images on HPC cluster with command: %s",
            command,
        )
        self._run_ssh_command(self._HPC_FE_HOST, command)

    def _run_ssh_command(self, host: str, command: list[str]) -> None:
        ssh_command = [
            "ssh",
            "-oPasswordAuthentication=no",  # Do not try to use password authentication.
            "-oStrictHostKeyChecking=no",  # In case the host keys changed. Unsafe?
            host,
            *command,
        ]
        self.log.debug("Running SSH command: %s", ssh_command)
        try:
            subprocess.run(  # noqa: S603
                ssh_command,
                check=True,
                stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            self.log.exception(
                "Could not run SSH command: %s -- stderr: %s",
                ssh_command,
                exc.stdout,
            )
            raise

    def move_to_centered_position(self) -> None:
        """Extends move-to-centered operation with required MD3 waits"""

        # wait until MD3 is ready for new commands
        self.diffractometer_hwobj.wait_ready(MD3_READY_TIMEOUT)

        super().move_to_centered_position()

        # wait until MD3 is done with move commands
        self.diffractometer_hwobj.wait_ready(MD3_READY_TIMEOUT)

    def display_image(
        self, image_filename: str, image_num: int = 1, client_addr: str | None = None
    ):
        """
        Site specific call to a diffraction viewer, opens pumpkin

        Args:
           image_filename: full path to image file
           image_num: image number within image file to open (if it contains
                      multiple images i.e HDF5)
           client_addr: incoming request client address for triggering local running
                         viewer application
        """
        message = f"{json.dumps({'file': image_filename, 'frame': image_num})}\n"
        try:
            with socket.create_connection((client_addr, 8100)) as sock:
                sock.sendall(message.encode("utf-8"))
        except socket.timeout:
            self.log.warning(
                "[PUMPKIN]: Timeout while connecting/sending for image '%s'",
                image_filename,
            )
        except OSError:
            self.log.exception("[PUMPKIN]: Failed to load image '%s'", image_filename)
