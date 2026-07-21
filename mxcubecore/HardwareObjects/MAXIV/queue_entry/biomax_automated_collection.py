import json
import logging
from typing import ClassVar

from pydantic import (
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
from mxcubecore.model.queue_model_objects import (
    DataCollection,
    XrayCentering,
)
from mxcubecore.queue_entry.base_queue_entry import (
    BaseQueueEntry,
)
from mxcubecore.queue_entry.data_collection import DataCollectionQueueEntry

from .biomax_xray_centering import BiomaxXrayCenteringQueueEntry

log = logging.getLogger("queue_exec")


class BiomaxAutomatedCollectionParameters(BaseModel):
    exp_time: float = Field(100e-4, gt=0, lt=1, title="Exposure time (s)")
    num_images: int = Field(1000, gt=0, lt=10000000, title="Number of images")
    energy: float = Field()
    resolution: float = Field()


class BiomaxAutomatedQueueModel(DataCollection):
    pass


class BiomaxAutomatedTaskParameters(BaseModel):
    path_parameters: PathParameters
    common_parameters: CommonCollectionParamters
    collection_parameters: StandardCollectionParameters
    user_collection_parameters: BiomaxAutomatedCollectionParameters
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
                    "*",
                ],
                "ui:submitButtonOptions": {
                    "norender": "true",
                },
            },
        )


class BiomaxAutomatedCollectionQueueEntry(DataCollectionQueueEntry):
    """
    BioMAX Automated collection queue entry
    """

    QMO = BiomaxAutomatedQueueModel
    DATA_MODEL = BiomaxAutomatedTaskParameters
    NAME = "BioMAX Automated Collection"
    REQUIRES: ClassVar = ["no_shape"]

    def execute(self):
        BaseQueueEntry.execute(self)
        data_collection = self.get_data_model()

        if data_collection:
            xr_qe = BiomaxXrayCenteringQueueEntry(data_model=data_collection)
            try:
                xr_node = XrayCentering()
                parent = self.get_data_model().get_parent()
                xr_node._parent = parent  # noqa: SLF001

                q = self.get_queue_controller()
                parent_entry = q.get_entry_with_model(parent)
                xr_qe.set_data_model(xr_node)
                xr_qe.shapes = HWR.beamline.sample_view
                parent_entry.enqueue(xr_qe)
            except Exception:
                log.exception("error")

            try:
                xr_qe.pre_execute()
                xr_qe.execute()
            except Exception:
                log.exception("error")

            self.collect_dc(data_collection, self.get_view())

        if HWR.beamline.sample_view:
            HWR.beamline.sample_view.de_select_all()
