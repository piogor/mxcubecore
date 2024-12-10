#
# Disable 'ambiguous unicode character' check.
# We want to use greek letters for unit cell parameters.
#
# ruff: noqa: RUF001
#

import json
import logging
from typing import ClassVar

import gevent
from pydantic.v1 import (
    BaseModel,
    Field,
)

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.MAXIV.MicroMAX import ekspla
from mxcubecore.model.common import (
    CommonCollectionParamters,
    LegacyParameters,
    PathParameters,
    StandardCollectionParameters,
)
from mxcubecore.model.queue_model_objects import DataCollection
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from .base import (
    AbstractSsxQueueEntry,
    restore_beamline,
    wait_acquisition_done,
)

log = logging.getLogger("queue_exec")


def sec_to_ms(sec) -> float:
    """
    convert seconds to milliseconds (ms)
    """
    return sec * 1_000.0


class InjectorUserCollectionParameters(BaseModel):
    exp_time: float = Field(100e-6, gt=0, lt=1, title="Exposure time (s)")
    images_per_trigger: int = Field(20, gt=0, lt=10000000, title="Images per trigger")
    total_images: int = Field(10000, gt=0, lt=10000000, title="Total number of images")
    energy: float = Field()
    resolution: float = Field()
    space_group: str = Field()
    cellA: float = Field(0, title="Cell A")  # noqa: N815
    cellB: float = Field(0, title="Cell B")  # noqa: N815
    cellC: float = Field(0, title="Cell C")  # noqa: N815
    cellAlpha: float = Field(0, title="Cell α")  # noqa: N815
    cellBeta: float = Field(0, title="Cell β")  # noqa: N815
    cellGamma: float = Field(0, title="Cell γ")  # noqa: N815


class SsxTrInjectorQueueModel(DataCollection):
    pass


class InjectorTaskParameters(BaseModel):
    path_parameters: PathParameters
    common_parameters: CommonCollectionParamters
    collection_parameters: StandardCollectionParameters
    user_collection_parameters: InjectorUserCollectionParameters
    legacy_parameters: LegacyParameters

    @staticmethod
    def update_dependent_fields(field_data):
        return field_data

    @staticmethod
    def ui_schema():
        return json.dumps(
            {
                "ui:order": [
                    "images_per_trigger",
                    "total_images",
                    "exp_time",
                    "resolution",
                    "energy",
                    "space_group",
                    "cellAlpha",
                    "cellA",
                    "cellBeta",
                    "cellB",
                    "cellGamma",
                    "cellC",
                    "*",
                ],
                "ui:submitButtonOptions": {
                    "norender": "true",
                },
                "num_images": {"ui:readonly": "true"},
            },
        )


def _get_total_images(total_images: int, images_per_trigger: int) -> int:
    """
    massage total_image to be evenly divisible by images_per_trigger
    """
    reminder = total_images % images_per_trigger
    if reminder != 0:
        total_images += images_per_trigger - reminder

    return total_images


class SsxTrInjectorQueueEntry(AbstractSsxQueueEntry):
    QMO = SsxTrInjectorQueueModel
    DATA_MODEL = InjectorTaskParameters
    NAME = "SSX Injector Time Resolved"
    REQUIRES: ClassVar = ["point", "line", "no_shape", "chip", "mesh"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ekspla_laser = ekspla.Ekspla()

    def _do_data_collection(self):
        params = self._data_model._task_data.user_collection_parameters  # noqa: SLF001
        total_images = _get_total_images(params.total_images, params.images_per_trigger)

        num_images = params.images_per_trigger
        num_triggers = total_images // params.images_per_trigger

        self.prepare_data_collection(num_images, num_triggers)

        #
        # start acquisition
        #
        self.ekspla_laser.run()

        shape_id = self._data_model._task_data.collection_parameters.shape  # noqa: SLF001
        shape = HWR.beamline.sample_view.get_shape(shape_id)
        if shape and shape.t == "L":
            self.interpolate_positions(shape)

        #
        # wait for acquisition to end
        #
        wait_acquisition_done()

        #
        # stop generating trigger signals
        #
        self.ekspla_laser.stop()

    def execute(self):
        try:
            super().execute()
            self._do_data_collection()
        except Exception as ex:
            raise QueueExecutionException(str(ex), self) from ex
        finally:
            restore_beamline()

    def stop(self):
        # stop generating trigger signals
        self.ekspla_laser.stop()

        # give detector chance to finish last train of triggers
        gevent.sleep(1.0)

        # this will ask detector to stop acquisition
        super().stop()
