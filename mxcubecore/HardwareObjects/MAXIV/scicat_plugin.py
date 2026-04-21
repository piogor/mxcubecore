"""
A plugin to connect to SciCat.
"""

# ruff: noqa: C901, PLR0912
import logging
import math
import time
from datetime import UTC, datetime
from pathlib import Path

from scifish import SciFish

_FILE_WAIT_TIMEOUT = 30.0
_FILE_WAIT_INTERVAL = 0.5


SKIP_VALUES = [
    "fileinfo",
    "auto_dir",
    "EDNA_files_dir",
    "xds_dir",
    "actualCenteringPosition",
    "actualCentringPosition",
]


class SciCatPlugin:
    """
    SciCat Plugin.
    """

    def __init__(self):
        self.scifish = SciFish()
        self.files = []
        self.log = logging.getLogger(__name__)

    def start_scan(self, proposalId, parameters):
        self.log.info("Preparing scicat information ")
        directory = parameters["fileinfo"]["directory"]
        filename = parameters["fileinfo"]["template"]
        num_files = math.ceil(
            parameters["oscillation_sequence"][0]["number_of_images"] / 1000,
        )
        sample_id = parameters["blSampleId"]

        self.scifish.start_scan(datasetName=filename)
        self.scifish.scicat_data.proposalId = proposalId
        self.scifish.scicat_data.sourceFolder = directory
        self.files = []
        base = Path(directory)
        self.files.append(str(base / filename))
        for i in range(1, num_files + 1):
            formatted_filename = filename.replace("master", f"data_{i:06d}")
            self.files.append(str(base / formatted_filename))
        self.scifish.sampleId = sample_id

    def end_scan(self, parameters):
        for item in parameters:
            try:
                if item in SKIP_VALUES:
                    continue
                if type(parameters[item]) is dict or type(parameters[item]) is list:
                    self.scifish.scicat_data.scientificMetadata.update({item: {}})
                    for subitem in parameters[item]:
                        if type(subitem) is dict:
                            for subsubitem in subitem:
                                smd = self._scientific_metadata_writer(
                                    subsubitem,
                                    subitem[subsubitem],
                                )
                                self.scifish.scicat_data.scientificMetadata[
                                    item
                                ].update(smd)
                        else:
                            smd = self._scientific_metadata_writer(
                                subitem,
                                parameters[item][subitem],
                            )
                            self.scifish.scicat_data.scientificMetadata[item].update(
                                smd,
                            )
                else:
                    smd = self._scientific_metadata_writer(item, parameters[item])
                    self.scifish.scicat_data.scientificMetadata.update(smd)
            except Exception:
                self.log.exception(
                    "[HWR] Error creating scientificMetadata for %s",
                    item,
                )

        files_list = {str(f) for f in self.files}
        for file in files_list:
            path = Path(file)
            deadline = time.monotonic() + _FILE_WAIT_TIMEOUT

            self.log.warning("waiting for '%s'", file)

            while not path.exists():
                if time.monotonic() >= deadline:
                    self.log.error("Timed out waiting for file '%s' to appear", file)
                    break
                time.sleep(_FILE_WAIT_INTERVAL)
            else:
                try:
                    stat = path.stat()
                except OSError:
                    self.log.exception("Could not add file '%s'", file)
                file_size = stat.st_size
                file_time = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
                self.scifish.scicat_data.files.append(
                    {"path": file, "time": file_time, "size": file_size},
                )

        self.scifish.end_scan()
        self.log.info("scicat upload complete")

    def _scientific_metadata_writer(self, label, value):
        units = {
            "energy": "keV",
            "sampx": "mm",
            "sampy": "mm",
            "focus": "mm",
            "phi": "deg",
            "kappa": "deg",
            "kappa_phi": "deg",
            "phiz": "deg",
            "phiy": "deg",
            "wavelength": "angstrom",
            "slitGapHorizontal": "mm",
            "detectorDistance": "mm",
            "undulatorGap1": "mm",
            "beamSizeAtSampleX": "mm",
            "beamSizeAtSampleY": "mm",
            "resolution": "angstrom",
            "photon flux": "s^-1",
        }

        if label == "flux":
            label = "photon flux"

        if label in units:
            smd = {label: {"value": value, "unit": units[label]}}
        else:
            smd = {label: value}

        return smd
