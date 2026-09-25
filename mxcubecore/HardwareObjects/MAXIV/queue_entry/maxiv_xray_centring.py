import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Annotated, Any, ClassVar

import gevent
from pydantic import AfterValidator, BaseModel, Field

import mxcubecore.model.queue_model_objects as qmo
from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.SampleView import Line
from mxcubecore.model.common import (
    CommonCollectionParamters,
    LegacyParameters,
    PathParameters,
    StandardCollectionParameters,
)
from mxcubecore.model.queue_model_enumerables import EXPERIMENT_TYPE_STR
from mxcubecore.model.queue_model_objects import DataCollection, PathTemplate
from mxcubecore.queue_entry.base_queue_entry import (
    BaseQueueEntry,
    QueueAbortedException,
    QueueExecutionException,
    QueueSkipEntryException,
    TaskPrerequisite,
)

log = logging.getLogger("queue_exec")
hwr_log = logging.getLogger("HWR")
user_log = logging.getLogger("user_level_log")


OMEGA_INCREMENT = 0.000001
LINE_LENGTH = 30


def get_num_images() -> int:
    shape = HWR.beamline.sample_view.get_selected_shapes()[0]
    return shape.num_cols * shape.num_rows


def round_to_first_non_zero(n: float):
    if n == 0 or abs(n) >= 1:
        return round(n)

    decimals = -math.floor(math.log10(abs(n)))
    return round(n, decimals)


def get_min_exp_time() -> tuple[float, float]:
    r"""Calculates min exposure time.

    from AlignmentX and AlignmentY speeds (mm/s) and original
    beam size (mm) we get:

    .. math::
        v = ds/dt => dt = ds / v

    """
    shape = HWR.beamline.sample_view.get_selected_shapes()[0]
    vx, vy, _ = HWR.beamline.diffractometer.get_alignment_table_speed_limits()
    return round_to_first_non_zero(shape.beam_width / vx), round_to_first_non_zero(
        shape.beam_width / vy
    )


def is_enough_time(value: float):
    _, min_time = get_min_exp_time()
    if value < min_time:
        msg = f"Exposure time must be at least {min_time}. {value} is not enough!"
        user_log.critical(msg)
        raise ValueError(msg)
    return value


class XRayCentringUserCollectionParameters(BaseModel):
    num_images: Annotated[
        int,
        Field(
            ...,
            title="Total number of images",
            gt=0,
        ),
    ]
    exp_time: Annotated[
        float,
        Field(
            ...,
            gt=0,
            title="Exposure time",
            description="Total time the sample is exposed per detector image. "
            "Excludes time without x-rays and readout time.",
            json_schema_extra={"unit": "s"},
        ),
        AfterValidator(is_enough_time),
    ]
    osc_range: Annotated[
        float,
        Field(
            default=0.1,
            gt=0,
            title="Oscillation range",
            description="The oscillation range per image of the first mesh scan",
        ),
    ]
    resolution: Annotated[
        float,
        Field(
            ...,
            gt=0,
            title="Resolution",
            json_schema_extra={"unit": "Å"},
        ),
    ]
    energy: Annotated[
        float,
        Field(
            ...,
            gt=0,
            title="Energy",
            json_schema_extra={"unit": "KeV"},
        ),
    ]
    transmission: Annotated[
        float,
        Field(
            ...,
            gt=0,
            title="Transmission",
            json_schema_extra={"unit": "%"},
        ),
    ]


class XrayCentringQueueModel(DataCollection): ...


class XrayCentringTaskParameters(BaseModel):
    path_parameters: PathParameters
    common_parameters: CommonCollectionParamters
    collection_parameters: StandardCollectionParameters
    user_collection_parameters: XRayCentringUserCollectionParameters
    legacy_parameters: LegacyParameters

    @staticmethod
    def update_dependent_fields(field_data: dict[str, Any]) -> dict[str, Any]:
        defaults = HWR.beamline.get_default_acquisition_parameters()
        patch: dict[str, Any] = {"_extras": {}}
        _, min_exp_time = get_min_exp_time()
        exp_time = field_data.get("exp_time")
        if exp_time == defaults.exp_time:
            patch["exp_time"] = min_exp_time
        patch["num_images"] = get_num_images()
        return patch

    @staticmethod
    def ui_schema():
        return json.dumps({})


class MaxivXrayCentringQueueEntry(BaseQueueEntry):
    """MAXIV XRayCentring queue entry."""

    QMO = XrayCentringQueueModel
    DATA_MODEL = XrayCentringTaskParameters
    NAME = "MAXIV XRAY Centring"
    REQUIRES: ClassVar[list[TaskPrerequisite]] = [TaskPrerequisite.GRID]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_queue = False

    def _get_path_template(self) -> PathTemplate:
        return self.get_data_model().get_path_template()

    def _get_task_params(self) -> XrayCentringTaskParameters:
        return self.get_data_model().task_data

    def _get_shape_id(self) -> str:
        return self.get_data_model().shape

    def _merge_and_dump_task_params(self):
        task_params = self._get_task_params()
        return {
            **task_params.collection_parameters.model_dump(),
            **task_params.user_collection_parameters.model_dump(),
            **task_params.common_parameters.model_dump(),
            **task_params.path_parameters.model_dump(),
            **task_params.legacy_parameters.model_dump(),
        }

    def _create_line(self) -> Line:
        sv = HWR.beamline.sample_view
        beam = HWR.beamline.beam

        bx, by = beam.get_beam_position_on_screen()
        _ = sv.get_centred_point_from_coord(bx, by, return_by_names=True)  # necessary?
        mesh_id = self._get_shape_id()
        mesh_shape = sv.get_shape(mesh_id)
        beam_width = mesh_shape.beam_width
        distance = (LINE_LENGTH / 2 - 0.5) * beam_width

        sv.move_cent_vertical_relative(distance)
        start_pos = sv.get_positions()
        x1, y1 = sv.motor_positions_to_screen(start_pos)
        p1 = sv.add_shape_from_mpos([start_pos], (x1, y1), "P")

        sv.move_cent_vertical_relative(-distance * 2)
        end_pos = sv.get_positions()
        x2, y2 = sv.motor_positions_to_screen(end_pos)
        p2 = sv.add_shape_from_mpos([end_pos], (x2, y2), "P")

        refs = [p1.id, p2.id]

        return sv.add_shape_from_refs(refs, "L")

    def _rotate_90(self):
        dm = HWR.beamline.diffractometer
        dm.omega_motor_hwobj.set_value_relative(90, timeout=10)
        dm.wait_ready(5)

    def _set_mesh_collect_params(self):
        collect = HWR.beamline.collect
        sv = HWR.beamline.sample_view
        dc = self.get_data_model()

        acq = dc.acquisitions[0]
        acq.acquisition_parameters.set_from_dict(self._merge_and_dump_task_params())
        acq.acquisition_parameters.in_queue = self.in_queue
        mesh = sv.get_shape(dc.shape)
        acq.acquisition_parameters.mesh_range = (mesh.width, mesh.height)
        acq.acquisition_parameters.mesh_steps = mesh.get_num_lines()
        acq.acquisition_parameters.centred_position = mesh.get_centred_position()

        cpos = acq.acquisition_parameters.centred_position
        collect.aborted_by_user = None

        param_list = qmo.to_collect_dict(dc, dc.get_sample_node(), cpos)
        collect.current_dc_parameters = param_list[0]
        collect.current_dc_parameters["experiment_type"] = EXPERIMENT_TYPE_STR.MESH

    def _set_line_collect_params(self):
        collect = HWR.beamline.collect
        dc = self.get_data_model()

        # avoid path collision (still doesn't work)
        path_template = self._get_path_template()
        path_template.base_prefix += "_line"

        acq = dc.acquisitions[0]

        acq.acquisition_parameters.set_from_dict(self._merge_and_dump_task_params())
        acq.acquisition_parameters.osc_start = (
            HWR.beamline.diffractometer.omega_motor_hwobj.get_value()
        )
        acq.acquisition_parameters.osc_range = OMEGA_INCREMENT
        acq.acquisition_parameters.num_images = LINE_LENGTH
        acq.acquisition_parameters.exp_time = get_min_exp_time()[0]
        acq.acquisition_parameters.in_queue = self.in_queue

        line = self._create_line()

        acq.acquisition_parameters.centred_position = line.get_centred_position()
        cpos = acq.acquisition_parameters.centred_position
        collect.aborted_by_user = None

        param_list = qmo.to_collect_dict(dc, dc.get_sample_node(), cpos)
        collect.current_dc_parameters = param_list[0]
        collect.current_dc_parameters["shape"] = line.id
        collect.current_dc_parameters["experiment_type"] = EXPERIMENT_TYPE_STR.LINE_SCAN

    def _run_mesh_scan(self):
        user_log.info("running mesh scan")

        dm = HWR.beamline.diffractometer
        sv = HWR.beamline.sample_view
        collect = HWR.beamline.collect
        detector = HWR.beamline.detector

        mesh_id = self._get_shape_id()
        mesh_shape = sv.get_shape(mesh_id).as_dict()

        osc_params = collect.current_dc_parameters["oscillation_sequence"][0]
        osc_start = osc_params["start"]
        osc_range = osc_params["range"]
        nframes_per_trigger = mesh_shape.get("num_rows")
        osc_end = osc_start + osc_range * nframes_per_trigger

        range_x = mesh_shape.get("num_cols") * mesh_shape.get("cell_width") / 1000.0
        range_y = mesh_shape.get("num_rows") * mesh_shape.get("cell_height") / 1000.0

        total_exposure_time = detector.get_acquisition_time() + 0.003

        dm.raster_scan(
            osc_start,
            osc_end,
            total_exposure_time,
            range_x,  # horizontal_range in mm,
            range_y,  # vertical_range in mm,
            mesh_shape["steps_x"],
            mesh_shape["steps_y"],
            invert_direction=1,
            wait=True,
        )

        user_log.info("finished scan, waiting for heatmap results")
        try:
            if collect.wait_for_xray_center_result(mesh_id):
                return
        except Exception as e:
            msg = "timeout"
            raise QueueAbortedException(msg, self) from e

        msg = "Center not found "
        raise QueueAbortedException(msg, self)

    def _run_line_scan(self):
        user_log.info("running 2D line scan")

        dm = HWR.beamline.diffractometer
        sv = HWR.beamline.sample_view
        beam = HWR.beamline.beam
        collect = HWR.beamline.collect
        detector = HWR.beamline.detector

        bx, by = beam.get_beam_position_on_screen()
        _ = sv.get_centred_point_from_coord(bx, by, return_by_names=True)

        mesh_id = self._get_shape_id()
        mesh_shape = sv.get_shape(mesh_id).as_dict()

        line_id = collect.current_dc_parameters["shape"]
        line = sv.get_shape(line_id)

        total_exposure_time = detector.get_acquisition_time() + 0.003  # just use 0.1 ?
        current_omega = dm.omega_motor_hwobj.get_value()
        start_cpos, end_cpos = line.cp_list
        osc_params = collect.current_dc_parameters["oscillation_sequence"][0]

        dm.osc_scan_4d(
            current_omega,
            current_omega + osc_params["range"],
            total_exposure_time,
            {
                "1": start_cpos.as_dict(),
                "2": end_cpos.as_dict(),
            },
        )

        user_log.info("finished scan, waiting for heatmap results")
        try:
            if collect.wait_for_xray_center_result(line.id):
                sv.add_shape_from_mpos([sv.get_positions()], (bx, by), "P")
                mesh_omega = mesh_shape.get("motor_positions").get("omega", 0)
                dm.omega_motor_hwobj.set_value(mesh_omega)
                return
        except Exception as e:
            msg = "timeout"
            raise QueueAbortedException(msg, self) from e

        msg = "Center not found "
        raise QueueAbortedException(msg, self)

    def _run_scan(self):
        user_log.info("Collection: Preparing to collect")
        collect = HWR.beamline.collect
        dm = HWR.beamline.diffractometer
        detector = HWR.beamline.detector

        dc_params = collect.current_dc_parameters

        dc_params["collection_start_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        dc_params["synchrotronMode"] = collect.get_machine_fill_mode()

        user_log.info("Collection: Storing data collection in LIMS")
        collect.store_data_collection_in_lims()

        user_log.info(
            "Collection: Creating directories for raw images and processing files"
        )
        collect.create_file_directories()

        user_log.info("Collection: Getting sample info from parameters")
        collect.get_sample_info()

        if all(item is None for item in dc_params["motors"].values()):
            current_diffractometer_position = dm.get_value()
            for motor in dc_params["motors"]:
                dc_params["motors"][motor] = current_diffractometer_position[motor]

        collect.take_crystal_snapshots()
        snapshots_files = []

        for key, value in dc_params.items():
            if key.startswith("xtalSnapshotFullPath"):
                snapshots_files.append(value)

        archive_directory = dc_params["fileinfo"]["archive_directory"]
        if not Path(archive_directory).exists():
            try:
                collect.create_directories(archive_directory)
            except os.error:
                hwr_log.exception("Collection: Error creating archive directory")

        collect.close_fast_shutter()
        collect.close_detector_cover()
        collect.open_safety_shutter()

        collect.prepare_acquisition()

        collect.open_detector_cover()

        gevent.sleep(5)
        try:
            detector.wait_config_done()
            detector.start_acquisition()
            detector.wait_ready()
        except Exception as ex:
            hwr_log.error("[COLLECT] Detector Error: %s" % ex)
            msg = "[COLLECT] Detector error while arming."
            raise RuntimeError(msg) from ex

        match dc_params["experiment_type"]:
            case EXPERIMENT_TYPE_STR.LINE_SCAN:
                self._run_line_scan()
            case EXPERIMENT_TYPE_STR.MESH:
                self._run_mesh_scan()

        detector.stop_acquisition()
        collect.close_detector_cover()
        collect.emit_collection_finished()

    def _collect(self):
        """Run mesh scan, rotate 90 degrees, and then run line scan."""
        user_log.info("Starting Xray Centring")
        self._set_mesh_collect_params()
        try:
            self._run_scan()
        except Exception as e:
            log.exception("failed to collect mesh")
            raise QueueAbortedException(e, self) from e

        user_log.info("rotating 90 deg")
        self._rotate_90()
        user_log.info("finished rotation, starting line scan")

        self._set_line_collect_params()
        try:
            self._run_scan()
        except Exception as e:
            log.exception("failed to collect line")
            raise QueueAbortedException(e, self) from e
        user_log.info("Finished Xray Centring")

    def stop(self):
        log.info("Calling stop on: %s", str(self))
        HWR.beamline.collect.stop_collect()  # this might raise greenlet.GreenletExit
        user_log.info("Collection stopped")
        msg = "Queue stopped"
        raise QueueAbortedException(msg, self)

    def handle_exception(self, ex):
        """Handle exception before stopping qe
        Called by the QueueManager when an exception is raised during qe execution
        only catches QueueAborted and unknown Exception, not Greenlet
        """
        HWR.beamline.collect.stop_collect()  # ????
        HWR.beamline.collect.emit_collection_failed()
        if isinstance(ex, QueueAbortedException):
            log.error("Call from 'handle_exception'")
        log.exception("")

    def pre_execute(self):
        return super().pre_execute()

    def execute(self):
        try:
            self._collect()
        except (QueueAbortedException, QueueSkipEntryException):
            msg = "Queue aborted/skipped"
            log.exception(msg)
            user_log.error(msg)
            raise
        except Exception as ex:
            msg = "Something went wrong."
            log.exception(msg)
            user_log.error(msg)
            raise QueueExecutionException(str(ex), self) from ex
        else:
            HWR.beamline.collect.emit_collection_finished()
        finally:
            user_log.info("Collection clean up")
            HWR.beamline.sample_view.de_select_all()
            HWR.beamline.collect.data_collection_cleanup()
