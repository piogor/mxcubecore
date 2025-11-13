from pathlib import Path

import cv2
import numpy as np

from mxcubecore import HardwareRepository as HWR
from mxcubecore.TaskUtils import task

BEAM_CENTER_SIZE = 10
BEAM_CENTER_COLOR = (255, 255, 0)
BEAM_CENTER_THICKNESS = 2


def _load_image():
    # get image as numpy array
    data, width, height = HWR.beamline.sample_view.camera.get_last_image()
    img = np.frombuffer(data, dtype=np.uint8)
    img = img.reshape((height, width, 3))

    # openCV needs images in BGR color
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def _add_overlay(img):
    """Poor man's overlay implementation.

    Hard-coded routines to add image center crosshair and
    beam-size circle to an image.
    """
    diffractometer = HWR.beamline.diffractometer

    #
    # draw beam center crosshair
    #

    x = int(diffractometer.zoom_centre["x"])
    y = int(diffractometer.zoom_centre["y"])

    # draw vertical line
    cv2.line(
        img,
        (x, y - BEAM_CENTER_SIZE),
        (x, y + BEAM_CENTER_SIZE),
        BEAM_CENTER_COLOR,
        BEAM_CENTER_THICKNESS,
    )

    # draw horizontal line
    cv2.line(
        img,
        (x - BEAM_CENTER_SIZE, y),
        (x + BEAM_CENTER_SIZE, y),
        BEAM_CENTER_COLOR,
        BEAM_CENTER_THICKNESS,
    )

    #
    # draw beam size 'circle'
    #
    px, py = diffractometer.get_pixels_per_mm()
    beam_size_x, beam_size_y = HWR.beamline.beam.get_beam_size()
    radius = int(beam_size_x * px / 2.0)
    cv2.circle(img, (x, y), radius, (255, 0, 255), 2)


def _write_snapshot_jpegs(
    image, snapshot_dirs: list[Path], file_prefix, run_number, snapshot_index
):
    """Write snapshot image as jpeg files to disk.

    Write provided `image` as jpeg file into all specified `snapshot_dirs`.
    """
    filename = f"{file_prefix}_{run_number}_{snapshot_index}.snapshot.jpeg"

    for snapshot_dir in snapshot_dirs:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(Path(snapshot_dir, filename), image)


@task
def take_crystal_snapshot(
    snapshot_dirs: list[Path], file_prefix, run_number, snapshot_index
):
    """Take crystal snapshot and write it to disk.

    Supports writing same crystal snapshot into multiple directories.

    Args:
        snapshot_dirs: directories where to write snapshot jpegs
        file_prefix: jpeg filename prefix
        run_number: data-collection run number
    """
    img = _load_image()
    _add_overlay(img)
    _write_snapshot_jpegs(img, snapshot_dirs, file_prefix, run_number, snapshot_index)
