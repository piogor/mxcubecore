#
# Disable 'ambiguous unicode character' check.
# We want to use greek letters for unit cell parameters.
#
# ruff: noqa: RUF001
#

import json
import logging
from typing import ClassVar

from pydantic.v1 import (
    BaseModel,
    Field,
)

from mxcubecore import HardwareRepository as HWR
from mxcubecore.model.common import (
    CommonCollectionParamters,
    LegacyParameters,
    PathParameters,
    StandardCollectionParameters,
)
from mxcubecore.model.queue_model_objects import DataCollection
from mxcubecore.queue_entry.base_queue_entry import (
    QueueExecutionException,
    TaskPrerequisite,
)

from .base import (
    AbstractSsxQueueEntry,
    restore_beamline,
    wait_acquisition_done,
)

log = logging.getLogger("queue_exec")


class InjectorUserCollectionParameters(BaseModel):
    exp_time: float = Field(100e-4, gt=0, lt=1, title="Exposure time (s)")
    num_images: int = Field(1000, gt=0, lt=10000000, title="Number of images")
    energy: float = Field()
    resolution: float = Field()
    space_group: str = Field()
    cellA: float = Field(0, title="Cell A")  # noqa: N815
    cellB: float = Field(0, title="Cell B")  # noqa: N815
    cellC: float = Field(0, title="Cell C")  # noqa: N815
    cellAlpha: float = Field(0, title="Cell α")  # noqa: N815
    cellBeta: float = Field(0, title="Cell β")  # noqa: N815
    cellGamma: float = Field(0, title="Cell γ")  # noqa: N815


class SsxInjectorQueueModel(DataCollection):
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
                    "num_images",
                    "exp_time",
                    "resolution",
                    "energy",
                    "space_group",
                    "cellA",
                    "cellAlpha",
                    "cellB",
                    "cellBeta",
                    "cellC",
                    "cellGamma",
                    "*",
                ],
                "ui:submitButtonOptions": {
                    "norender": "true",
                },
            },
        )


class SsxInjectorQueueEntry(AbstractSsxQueueEntry):
    QMO = SsxInjectorQueueModel
    DATA_MODEL = InjectorTaskParameters
    NAME = "SSX Injector Collection"
    REQUIRES: ClassVar[list[TaskPrerequisite]] = [
        TaskPrerequisite.POINT,
        TaskPrerequisite.LINE,
        TaskPrerequisite.CHIP,
        TaskPrerequisite.MESH,
        TaskPrerequisite.NO_SHAPE_2D,
    ]

    def _do_data_collection(self):
        params = self._data_model._task_data.user_collection_parameters  # noqa: SLF001

        self.prepare_data_collection(
            params.num_images,
            num_triggers=1,
            software_trigger=True,
        )

        detector = HWR.beamline.detector
        log.info("Sending software trigger to detector.")
        detector.trigger()
        shape_id = self._data_model._task_data.collection_parameters.shape  # noqa: SLF001
        shape = HWR.beamline.sample_view.get_shape(shape_id)
        if shape and shape.t == "L":
            self.interpolate_positions(shape)

        wait_acquisition_done()

    def execute(self):
        try:
            super().execute()
            self._do_data_collection()
        except Exception as ex:
            raise QueueExecutionException(str(ex), self) from ex
        finally:
            restore_beamline()
