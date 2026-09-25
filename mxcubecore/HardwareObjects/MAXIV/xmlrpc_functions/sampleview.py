import logging
from typing import Any, TypeAlias, TypedDict

import matplotlib.colors
import matplotlib.pyplot as plt

from mxcubecore import HardwareRepository as HWR

xmlrpc_prefix = "sampleview"


class HeatmapResult(TypedDict):
    score: float
    resolution: float
    number_of_spots: int


class ShapeResult(TypedDict):
    result: list[HeatmapResult]
    data_file: str
    cent: list[int]


# [R,G,B] values
ShapeValues: TypeAlias = list[int]

# MXCuBE DrawGridPlugin result expected type
DrawGridResult: TypeAlias = dict[str, list[Any | ShapeValues]]

log = logging.getLogger("HWR")


def set_grid_data(self, shape_id: str, shape_result: ShapeResult):  # noqa: ARG001
    """Set grid result for a shape"""

    logging.getLogger("XML-RPC").debug(
        "Setting grid data: shape_id = %s num_results = %s",
        shape_id,
        len(shape_result["result"]),
    )

    def get_grid_coords_biomax(idx: int) -> tuple[int, int]:
        """Get (x,y) coords from raw index.

        Notes:
            It assumes 0-indexed position and inverse zig-zag path!

        Example:
             9   8   3   2
            10   7   4   1
            11   6   5   0
        """
        grid = HWR.beamline.sample_view.get_shape(shape_id)
        num_rows, num_cols = grid.num_rows, grid.num_cols
        total = num_rows * num_cols
        offset = total - idx - 1

        x = offset // num_rows
        within_column = offset % num_rows

        y = within_column if (num_cols - x) % 2 != 0 else num_rows - within_column - 1

        return x, y

    def get_grid_coords_micromax(idx: int) -> tuple[int, int]:
        """Get (x,y) coords from raw index.

        Notes:
            It assumes 0-indexed position and top-down inverse zig-zag path!

        Example:
            6  5  0
            7  4  1
            8  3  2
        """
        grid = HWR.beamline.sample_view.get_shape(shape_id)
        num_rows, num_cols = grid.num_rows, grid.num_cols
        total = num_rows * num_cols
        offset = total - idx - 1

        x = offset // num_rows
        within_column = offset % num_rows

        y = within_column if (num_cols - x) % 2 == 0 else num_rows - within_column - 1

        return x, y

    def transform(result: list[HeatmapResult]) -> DrawGridResult:
        """Evaluate heatmap and prepare it to DrawGridPlugin"""
        shape = HWR.beamline.sample_view.get_shape(shape_id)
        transformed = {}
        scores = [v["score"] for v in result]
        vmin, vmax = min(scores), max(scores)
        vmax_index = scores.index(vmax)

        is_line = shape.t == "L"
        if is_line:
            # assumes start_pos < end_pos
            transformed["cent"] = (vmax_index, 0)
        else:
            cell_counting = HWR.beamline.get_default_acquisition_parameters(
                "mesh"
            ).cell_counting
            match cell_counting:
                case "top-down-inverse-zig-zag":
                    transformed["cent"] = get_grid_coords_micromax(vmax_index)
                case "inverse-zig-zag":
                    transformed["cent"] = get_grid_coords_biomax(vmax_index)
                case _:
                    log.error(
                        "Could not calculate center coordinates!",
                        "Check beamline configuration for misconfigured cell counting!",
                    )

        norm = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax)
        cmap = plt.get_cmap("Reds")

        log.info("Generating heatmap for shape '%s'", shape_id)
        for i, v in enumerate(result):
            cmap_value = cmap(norm(v["score"]))
            c1, c2, c3 = matplotlib.colors.colorConverter.to_rgb(cmap_value)
            transformed[str(i + 1)] = [0, [int(c1 * 255), int(c2 * 255), int(c3 * 255)]]

        return transformed

    result_data = shape_result["result"]
    data_file = shape_result["data_file"]

    result = transform(result_data)

    HWR.beamline.sample_view.set_grid_data(shape_id, result, data_file)
    return result
