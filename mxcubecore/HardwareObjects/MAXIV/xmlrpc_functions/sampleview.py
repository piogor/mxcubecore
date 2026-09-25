import logging
from typing import Any, TypeAlias, TypedDict

import matplotlib.cm
import matplotlib.colors

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


def set_grid_data(self, shape_id: str, shape_result: ShapeResult):  # noqa: ARG001
    """Set grid result for a shape"""

    logging.getLogger("XML-RPC").debug(
        "Setting grid data: shape_id = %s num_results = %s",
        shape_id,
        len(shape_result["result"]),
    )

    def transform(result: list[HeatmapResult]) -> DrawGridResult:
        """Evaluate heatmap and prepare it to DrawGridPlugin"""
        transformed = {}
        scores = [v["score"] for v in result]
        vmin, vmax = min(scores), max(scores)

        norm = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax)
        cmap = matplotlib.cm.get_cmap("Reds")

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
