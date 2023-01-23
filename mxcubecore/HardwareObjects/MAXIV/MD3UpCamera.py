"""Camera hardware object for Arinax MD3 on-axis video microscope."""

import struct
from io import BytesIO
from pathlib import Path
from typing import (
    List,
    Tuple,
)

import tango
from PIL import Image

from mxcubecore.BaseHardwareObjects import HardwareObject

# monochrome, 8-bit per pixel
IMAGE_MODE_L = 0
# rgb, 24-bit per pixel
IMAGE_MODE_RGB = 6

MISSING_FRAME_WIDTH = 1224
MISSING_FRAME_HEIGHT = 1024
MISSING_FRAME_COLOR = "pink"


def _make_frame_missing_image() -> bytes:
    image = Image.new(
        "RGB", (MISSING_FRAME_WIDTH, MISSING_FRAME_HEIGHT), color=MISSING_FRAME_COLOR
    )
    buffer = BytesIO()
    image.save(buffer, "JPEG")

    return buffer.getvalue()


class MD3UpCamera(HardwareObject):
    """Camera hardware object for Arinax MD3 on-axis video microscope.

    HWO Properties:
    * tangoname (str): Required. Name or full URL of the Arinax tango video device.
    """

    def __init__(self, name):
        super().__init__(name)
        self.stream_hash = "md3video"
        self.device = None
        self._frame_missing_image = _make_frame_missing_image()

        # width, height. Property required for MPEG1 format.
        self._current_stream_size = (0, 0)

    def init(self):
        self.tangoname = self.get_property("tangoname")
        self.device = tango.DeviceProxy(self.tangoname)
        self.device.ping()
        self._current_stream_size = (self.get_width(), self.get_height())

    def get_image_zoom(self) -> float:
        # hard-coded to 1.0, for compatibility reasons
        return 1.0

    def get_width(self) -> int:
        return self.device.image_width

    def get_height(self) -> int:
        return self.device.image_height

    def take_snapshot(self, path, grayscale=False) -> None:
        _, _, jpg_data = self._get_jpg_image()
        Path(path).write_bytes(jpg_data)

    def get_last_image(self) -> tuple[bytes, int, int]:
        """Get last image in RGB.

        Returns:
            Tuple containing:
            * image data in RGB as bytes
            * image's width in number of pixels
            * image's height in number of pixels
        """
        pil_mode, width, height, pixels = self._get_frame_data()

        # If image data is in grayscale, convert it to RGB.
        # This is likely wasteful, since caller will likely convert back to PIL object.
        if pil_mode == "L":
            gray_image = Image.frombytes(pil_mode, (width, height), pixels)
            rgb_image = gray_image.convert("RGB")
            pixels = rgb_image.tobytes()

        return pixels, width, height

    def _get_frame(self) -> Tuple[int, int, Image.Image]:
        """Read one frame from Tango device.

        Returns: Frame's width, height, and pixels as a PIL image object.
        """

        pil_mode, width, height, pixels = self._get_frame_data()

        image = Image.frombytes(pil_mode, (width, height), pixels)

        return width, height, image

    def _get_frame_data(self) -> tuple[str, int, int, bytes]:
        """Get frame data.

        The MD3 on-axis microscope delivers images either in RGB24 format or
        in Monochrome 8-bit format, depending on the zoom level.

        This function maps LIMA image mode numbers to PIL image format names,
        so that we can convert both of the images to a JPEG image.

        Returns:
            Tuple containing:
            * PIL mode (``RGB`` or ``L``)
            * width
            * height
            * pixels
        """

        _, frame = self.device.video_last_image

        (
            _,  # magic number
            _,  # version
            image_mode,
            _,  # frame number
            width,
            height,
            _,  # endianness
            header_size,
        ) = struct.unpack(">IHHqiiHH", frame[0:28])

        if image_mode == IMAGE_MODE_RGB:
            pil_mode = "RGB"
            pixels = frame[header_size:]
        elif image_mode == IMAGE_MODE_L:
            # should be image in monochrome 8-bit format
            pil_mode = "L"

            # the MD3 tango device sends some extra bytes when in the monochrome mode,
            # we need to cut them off
            end = header_size + (width * height)
            pixels = frame[header_size:end]
        else:
            message = "Unknown image mode"
            raise RuntimeError(message)

        return pil_mode, width, height, pixels

    def _get_jpg_image(self) -> Tuple[int, int, bytes]:
        """Get one frame from Tango device and encode it as JPEG."""
        try:
            width, height, image = self._get_frame()

            buffer = BytesIO()
            image.save(buffer, "JPEG")

            jpg_img = buffer.getvalue()
            return width, height, jpg_img
        except tango.CommunicationFailed:
            self.log.warning("failed to fetch video frame from MD3", exc_info=True)
            # show the user the pink 'frame is missing' image,
            # when we can't fetch latest video frame
            return MISSING_FRAME_WIDTH, MISSING_FRAME_WIDTH, self._frame_missing_image

    def get_available_stream_sizes(self) -> List[Tuple[int, int]]:
        """Return available video stream sizes.

        This method is required in order for mxcube to work with MPEG1 format.

        Returns:
            List representing available video stream sizes.
        """
        try:
            width, height = self.get_width(), self.get_height()
            video_sizes = [
                (width, height),
                (width // 2, height // 2),
                (width // 4, height // 4),
            ]
            self.log.debug("MD3 camera video_sizes=%s", video_sizes)
        except (ValueError, AttributeError):
            video_sizes = []

        return video_sizes

    def get_stream_size(self) -> Tuple[int, int, float]:
        """Returns current video stream size.

        Used when video_size control is enabled in ``ui.yaml``.

        Returns:
            Current video stream size, represented as (width, height, scale).
        """
        width, height = self._current_stream_size
        scale = float(width) / self.get_width()
        return (width, height, scale)
