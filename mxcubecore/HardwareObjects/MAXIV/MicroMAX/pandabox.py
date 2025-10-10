import logging
from enum import Enum
from pathlib import Path

from pandablocks.blocking import BlockingClient
from pandablocks.commands import SetState

PANDA_HOST = "b312a-a101232-cab01-ctl-panda-01"
SCHEMA_DIRECTORY = "/data/staff/micromax/software/configs/pandabox_eh1/"


log = logging.getLogger("HWR")


class Detectors(Enum):
    """Supported detectors"""

    Eiger = 0
    Jungfrau = 1


# OSC schema per supported detector
OSC_SCHEMA_FILE_NAMES = {
    Detectors.Eiger: "osc_eiger_schema.txt",
    Detectors.Jungfrau: "osc_jungfrau_schema.txt",
}


def _read_schema_file(schema_file: Path) -> list[str]:
    return schema_file.read_text().splitlines()


def _upload_schema(schema_file: Path):
    """Upload schema from the specified file"""

    log.info(
        "[PandABox] Loading schema from %s (%s)",
        schema_file.absolute(),
        # in case symlink is used, log the actual file as well
        schema_file.resolve(),
    )
    schema_data = _read_schema_file(schema_file)
    with BlockingClient(PANDA_HOST) as client:
        client.send(SetState(schema_data))


def _get_osc_schema_file_path(detector: Detectors) -> Path:
    return Path(SCHEMA_DIRECTORY, OSC_SCHEMA_FILE_NAMES[detector])


def load_osc_schema(detector: Detectors):
    """Load schema for OSC data collections

    Load schema used for OSC data collection into PandAbox.
    Loads different schemas, depending on specified detector.

    Args:
        detector: detector to use
    """
    log.info("[PandABox] Configuring 'osc' schema, using detector: %s", detector.name)
    schema_path = _get_osc_schema_file_path(detector)
    _upload_schema(schema_path)
