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


@task
def take_crystal_snapshot(snapshot_filename: str):
    """Take crystal snapshot and write it to disk.

    Args:
        snapshot_filename: full file path where to write snapshot image
    """
    img = _load_image()
    _add_overlay(img)

    cv2.imwrite(snapshot_filename, img)
