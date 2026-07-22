#
# Disable 'ambiguous unicode character' check.
# We want to use greek letters for unit cell parameters.
#
# ruff: noqa: RUF001
#

import json
import logging
from collections import defaultdict
from enum import Enum
from math import lcm, sqrt
from pathlib import Path
from typing import Any, ClassVar, OrderedDict

from pydantic import BaseModel, Field, root_validator

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.SampleView import Line
from mxcubecore.model import queue_model_objects
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
from mxcubecore.utils.units import mm_to_meter, um_to_mm

from .hve import (
    AbstractSsxQueueEntry,
    SpaceGroup,
    restore_beamline,
    wait_acquisition_done,
)

log = logging.getLogger("queue_exec")


DUTY_CYCLES: dict[int, float] = {
    547000: 100,
    577000: 70,
    607000: 35,
    627000: 18,
    642000: 9,
    662000: 4,
    681000: 0.8,
}

JUNGFRAU_MIN_FRAME_TIME = 5e-4
EIGER_MIN_FRAME_TIME = 5e-3

# A work-around value used to indicate 'no omega rotation'
# when configuring Jungfrau detector.
JUNGFRAU_NON_ZERO_OMEGA_INCREMENT = 0.000001


def _is_jungfrau() -> bool:
    """Checks if the current detector is a JUNGFRAU.

    Returns:
        True if the current detector is a JUNGFRAU, False otherwise.
    """
    # not using HWR.beamline.collect.is_jungfrau(), because collect hardware object
    # is initialized after queue_manager hardware object.
    # So we can't access collect when constructing the pydantic model.
    detector_model = HWR.beamline.detector.get_property("model")
    return detector_model == "JUNGFRAU"


def _get_min_frame_time() -> float:
    """Gets the minimum frame time based on the detector model.

    Returns:
        minimum frame time in seconds.
    """

    return JUNGFRAU_MIN_FRAME_TIME if _is_jungfrau() else EIGER_MIN_FRAME_TIME


def _duty_cycle_fraction(field_data: dict[str, Any]) -> float:
    """Get the duty cycle fraction from the field data.

    Args:
        field_data: Dictionary containing the user collection parameters.

    Returns:
        Duty cycle as a fraction (0.0 to 1.0).
    """
    return DUTY_CYCLES.get(field_data.get("duty_cycle", 100), 100) / 100.0


def _get_exposure_time(
    field_data: dict[str, Any], updated_field: str | None = None
) -> float:
    """Get the exposure time from the field data or return the minimum exposure time.

    Args:
        field_data: Dictionary containing the user collection parameters.

    Returns:
        Frame time in seconds.
    """
    # For EIGER the frame rate is at most 200Hz, so frame time is at most 5ms.
    # Thus precision of 5 decimal places is enough (10 microseconds) is enough.
    # For JUNGFRAU 2KHz frame rate is possible, so precision up to
    # 1 microsecond is preferred.

    precision = 6 if _is_jungfrau() else 5
    # When chopper is disabled, the exposure time is just the user input value.
    if updated_field == "exp_time" or not field_data.get("enable_chopper"):
        return round(field_data.get("exp_time", 0.0), precision)

    # When chopper is used we need to take into account
    # the duty cycle and possibly user-set frame time.

    duty_cycle_fraction = _duty_cycle_fraction(field_data)
    readout_time = HWR.beamline.detector.get_readout_time()
    frame_time = field_data.get("frame_time", _get_min_frame_time())
    return round((frame_time - readout_time) * duty_cycle_fraction, precision)


def _get_frame_time(field_data: dict[str, Any]) -> float:
    """Get the frame time from the field data or return the minimum frame time.

    Args:
        field_data: Dictionary containing the user collection parameters.

    Returns:
        Frame time in seconds.
    """

    duty_cycle_fraction = _duty_cycle_fraction(field_data)
    readout_time = HWR.beamline.detector.get_readout_time()
    exposure_time = field_data.get("exp_time", 0.0)
    return round((exposure_time / duty_cycle_fraction) + readout_time, 6)


def _lcm_active(field_data: dict[str, Any]) -> int:
    """Calculate the least common multiple (LCM) of the active pump parameters.

    It is used to determine the number of data_classes field.

    """
    vals: list[int] = []
    if field_data.get("enable_nanosecond_laser"):
        vals.append(int(field_data.get("nanosecond_laser_images_per_pulse", 1)))
    if field_data.get("enable_laser_diode"):
        vals.append(int(field_data.get("laser_diode_images_per_pulse", 1)))
    if field_data.get("enable_ejector"):
        vals.append(int(field_data.get("ejector_images_per_drop", 1)))
    return lcm(*vals) if vals else 1


class Scans(Enum):
    POINT = 0
    LINE = 1
    STEP = 2


def _scan_type(shape, line_step: int):
    """Figure out which type of scan we are doing.

    Depending on what shape(s) are selected and the
    value of 'line step' parameter, determine what
    type of scan user have requested.
    """
    if shape.t == "2DP":
        return Scans.POINT

    if shape.t == "L":
        if line_step == 0:
            return Scans.LINE

        # line steps parameter non-zero,
        # we are doing step scans
        return Scans.STEP

    raise AssertionError("unexpected shape selected")  # noqa: EM101


def _get_step_scan_points(line: Line, line_step: int):
    """Calculate intermediate points for a step scan."""

    def get_start_end():
        return [p.as_dict() for p in line.cp_list]

    def subtract(a: dict, b: dict) -> dict:
        """Perform vector subtraction, a - b."""
        return {name: a[name] - b[name] for name in a.keys()}  # noqa: SIM118

    def add(a: dict, b: dict) -> dict:
        """Perform vector addition, a + b."""
        return {name: a[name] + b[name] for name in a.keys()}  # noqa: SIM118

    def magnitude(vect: dict) -> float:
        """Calculate vector magnitude aka length."""
        return sqrt(sum([val**2 for val in vect.values()]))

    def mult(vect: dict, scalar: float) -> dict:
        """Multiply vector with a scalar, vect * scalar."""
        return {k: v * scalar for k, v in vect.items()}

    start, end = get_start_end()
    step = um_to_mm(float(line_step))

    step_vector = subtract(end, start)
    line_length = magnitude(step_vector)
    # normalize 'step vector'
    step_vector = mult(step_vector, 1.0 / line_length)

    for step_num in range(int(line_length / step)):
        yield add(start, mult(step_vector, step * float(step_num)))


class Hve2DScanUserCollectionParameters(BaseModel):
    # ============ACQUISTION GROUP============
    num_images: int = Field(default=1, title="Total number of images", ge=1)
    exp_time: float = Field(
        ...,
        gt=0,
        unit="s",
        title="Exposure time",
        description="Total time the sample is exposed per detector image. "
        "Excludes time without x-rays and readout time.",
    )
    resolution: float = Field(
        ...,
        gt=0,
        unit="Å",
    )
    energy: float = Field(
        ...,
        gt=0,
        description="Energy in KeV",
        unit="KeV",
    )
    transmission: float = Field(
        ...,
        gt=0,
        unit="%",
    )
    duty_cycle: float = Field(
        default=next(iter(DUTY_CYCLES)),
        title="Duty Cycle",
        description="Percentage of Frame Time, in which the sample is fully exposed.",
        unit="%",
        oneOf=[
            {
                "const": position,
                "title": f"{percentage}%",
            }
            for position, percentage in DUTY_CYCLES.items()
        ],
    )

    frame_time: float = Field(
        default=_get_min_frame_time(),
        ge=_get_min_frame_time(),
        unit="s",
        title="Frame Time",
    )  # calculated

    line_step: int = Field(
        default=0,
        ge=0,
        unit="μm",
        title="Line Step",
        description="Step size between points where data is collected when "
        "interpolating between two points.",
    )

    enable_chopper: bool = Field(
        default=False,
        title="Enable chopper",
        description="Enable the chopper for this collection",
    )

    # ============PUMP============

    data_classes: int = Field(
        1,
        title="Data classes",
        description=(
            "Total number of distinct time points accounting for all pump events"
        ),
    )

    enable_nanosecond_laser: bool = Field(
        default=False,
        title="Enable nanosecond laser",
        description="Enable the nanosecond laser for this collection",
    )

    enable_laser_diode: bool = Field(
        default=False,
        title="Enable laser diode",
        description="Enable the laser diode for this collection",
    )

    enable_ejector: bool = Field(
        default=False,
        title="Enable ejector",
        description="Enable the ejector for this collection",
    )

    nanosecond_laser_images_per_pulse: int = Field(
        1,  # 1 is a default value, for the lowest common multiple calculations
        ge=1,
        title="Images per pulse",
        description="Number of images to be taken per pulse of the nanosecond laser.",
    )

    laser_diode_images_per_pulse: int = Field(
        1,
        ge=1,
        title="Images per pulse",
        description="Number of images to be taken per pulse of the laser diode.",
    )

    ejector_images_per_drop: int = Field(
        1,
        ge=1,
        title="Images per drop",
        description="Number of images to be taken per drop of the ejector.",
    )

    first_image_after_trigger: int = Field(
        1,
        title="First image after trigger",
        description="Delays the laser trigger to occur immediately"
        "before the image number given."
        "Also changes which data classes correspond to 'Dark' and 'Light' images.",
    )

    # ============PROCESSING GROUP============

    space_group: SpaceGroup = Field(next(iter(SpaceGroup)), title="Space group")
    cellA: float = Field(0, title="Cell A", unit="μm", ge=0)  # noqa: N815
    cellB: float = Field(0, title="Cell B", unit="μm", ge=0)  # noqa: N815
    cellC: float = Field(0, title="Cell C", unit="μm", ge=0)  # noqa: N815
    cellAlpha: float = Field(0, title="Cell α", unit="°", ge=0, le=360.0)  # noqa: N815
    cellBeta: float = Field(0, title="Cell β", unit="°", ge=0, le=360.0)  # noqa: N815
    cellGamma: float = Field(0, title="Cell γ", unit="°", ge=0, le=360.0)  # noqa: N815

    @root_validator
    def _validate_first_image_after_trigger(
        cls,  # noqa: N805 - false positive; it's a classmethod.
        values: dict[str, Any],
    ) -> dict[str, Any]:
        data_classes = values.get("data_classes")
        first_image_after_trigger = values.get("first_image_after_trigger")
        if data_classes is None or first_image_after_trigger is None:
            error_msg = "data_classes and first_image_after_trigger must be set"
            logging.getLogger("user_level_log").error(error_msg)
            raise ValueError(error_msg)
        if not (-data_classes <= first_image_after_trigger <= data_classes):
            error_msg = f"""
            first image after trigger must be in range [-data_classes, data_classes],
            got {first_image_after_trigger} with data_classes={data_classes}
            """

            logging.getLogger("user_level_log").error(error_msg)
            raise ValueError(error_msg)
        return values

    class Config:
        @staticmethod
        def schema_extra(schema: dict[str, Any]) -> None:
            properties = schema["properties"]
            schema["allOf"] = [
                {
                    "if": {"properties": {"enable_chopper": {"const": True}}},
                    # The schema is popped, to include it only when relevant.
                    # Otherwise we'd need to write the field definition inside
                    # a string, instead of using pydantic Field.
                    "then": {
                        "properties": {
                            "duty_cycle": properties.pop("duty_cycle"),
                            "frame_time": properties.pop("frame_time"),
                        }
                    },
                },
                {
                    "if": {"properties": {"enable_nanosecond_laser": {"const": True}}},
                    "then": {
                        "properties": {
                            "nanosecond_laser_images_per_pulse": properties.pop(
                                "nanosecond_laser_images_per_pulse"
                            ),
                            "first_image_after_trigger": properties.pop(
                                "first_image_after_trigger"
                            ),
                        }
                    },
                },
                {
                    "if": {"properties": {"enable_laser_diode": {"const": True}}},
                    "then": {
                        "properties": {
                            "laser_diode_images_per_pulse": properties.pop(
                                "laser_diode_images_per_pulse"
                            )
                        }
                    },
                },
                {
                    "if": {"properties": {"enable_ejector": {"const": True}}},
                    "then": {
                        "properties": {
                            "ejector_images_per_drop": properties.pop(
                                "ejector_images_per_drop"
                            )
                        }
                    },
                },
            ]


class Hve2DScanQueueModel(DataCollection):
    pass


class Hve2DScanParameters(BaseModel):
    path_parameters: PathParameters
    common_parameters: CommonCollectionParamters
    collection_parameters: StandardCollectionParameters
    user_collection_parameters: Hve2DScanUserCollectionParameters
    legacy_parameters: LegacyParameters

    @staticmethod
    def update_dependent_fields(  # noqa: PLR0912, C901
        field_data: dict[str, Any], updated_field_name: str | None
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {"_extras": {}}
        chopper_enabled = field_data.get("enable_chopper", False)

        if updated_field_name is None:
            # This happens after filling the form with default / remembered values
            patch["frame_time"] = _get_frame_time(field_data)
            patch["data_classes"] = _lcm_active(field_data)

        elif updated_field_name == "exp_time":
            patch["frame_time"] = _get_frame_time(field_data)

        elif updated_field_name == "frame_time":
            patch["exp_time"] = _get_exposure_time(field_data, updated_field_name)
        elif updated_field_name == "duty_cycle":
            # We want to keep the same exposure time
            # as long as resulting frame time is valid.
            # In the scenario the resulting frame time is not valid,
            # we will patch the frame time to the minimum value
            frame_time_candidate = _get_frame_time(field_data)
            if frame_time_candidate >= _get_min_frame_time():
                patch["frame_time"] = frame_time_candidate
            else:
                patch["frame_time"] = _get_min_frame_time()
                patch["exp_time"] = _get_exposure_time(field_data, updated_field_name)
        elif updated_field_name in (
            "nanosecond_laser_images_per_pulse",
            "laser_diode_images_per_pulse",
            "ejector_images_per_drop",
        ):
            patch["data_classes"] = _lcm_active(field_data)

        patch["_extras"]["warnings"] = defaultdict(list)

        if not chopper_enabled:
            patch.pop("frame_time", None)

        new_values = {**field_data, **patch}
        if not chopper_enabled and _is_jungfrau():
            # Should be either 1/1000 or 1/2000 seconds.
            device_frame_time = HWR.beamline.detector.get_frame_time_us()
            readout_us = HWR.beamline.detector.get_readout_time() * 1e6
            integration_time_us = (new_values["exp_time"] * 1e6) + readout_us
            if device_frame_time < integration_time_us:
                patch["_extras"]["warnings"]["exp_time"].append(
                    "Integration time is longer than frame time."
                )
            elif device_frame_time > integration_time_us:
                patch["_extras"]["warnings"]["exp_time"].append(
                    "Integration time is less than frame time. Detector may idle."
                )
        if updated_field_name == "enable_chopper" and chopper_enabled:
            frame_time_candidate = _get_frame_time(new_values)
            if frame_time_candidate < _get_min_frame_time():
                patch["frame_time"] = _get_min_frame_time()
                patch["exp_time"] = _get_exposure_time(new_values, updated_field_name)

        return patch

    @staticmethod
    def get_estimated_time(field_data: dict[str, Any]) -> int:
        """
        Estimate the time required for the data collection based on the number of images
        and the frame time.

        Args:
            field_data: Dictionary containing the user collection parameters.

        Returns:
            Estimated time in seconds.
        """
        num_images = field_data.get("num_images", 0)
        frame_time = field_data.get("frame_time", _get_min_frame_time())
        log.info(
            "Estimating time for %d images with frame time %.3f seconds. got: %d",
            num_images,
            frame_time,
            int(num_images * frame_time),
        )
        return int(num_images * frame_time)

    @staticmethod
    def ui_schema() -> str:
        def ui_options(
            group: str,
            *,
            col: int = 6,
            row_id: str | None = None,
            readonly: bool = False,
        ) -> dict[str, Any]:
            """Creates RJSF uiSchema for a field.

            Args:
                group: group name.
                col: column number.
                row_id: row identifier.
                readonly: whether the field is read-only.

            Returns:
                RJSF uiSchema for a field.
            """
            block = {"group": group, "col": col}
            if row_id is not None:
                block["row_id"] = row_id
            settings = {"ui:options": block}
            if readonly:
                settings["ui:disabled"] = True
            return settings

        # To have the same order, as defined below, OrderedDict is used.
        ui = OrderedDict({"ui:submitButtonOptions": {"norender": "true"}})

        # ------------------------- Acquisition ---------------------------
        ui |= {
            "num_images": ui_options("Acquisition"),
            "exp_time": ui_options("Acquisition"),
            "resolution": ui_options("Acquisition"),
            "energy": ui_options("Acquisition", readonly=True),
            "transmission": ui_options("Acquisition", readonly=True),
            "line_step": ui_options("Acquisition"),
            "frame_time": ui_options("Acquisition"),
            "enable_chopper": ui_options(
                "Acquisition", row_id="acquisition_row_2", readonly=True
            ),
            "duty_cycle": ui_options("Acquisition", row_id="acquisition_row_2"),
        }
        # ----------------------------- Pump ------------------------------
        ui |= {
            "data_classes": ui_options(
                "Pump", row_id="pump_row_0", readonly=True, col=4
            ),
            "enable_nanosecond_laser": ui_options("Pump", row_id="pump_row_1", col=4),
            "nanosecond_laser_images_per_pulse": ui_options(
                "Pump", row_id="pump_row_1", col=4
            ),
            "first_image_after_trigger": ui_options("Pump", row_id="pump_row_1", col=4),
            "enable_laser_diode": ui_options(
                "Pump", row_id="pump_row_2", col=4, readonly=True
            ),
            "laser_diode_images_per_pulse": ui_options(
                "Pump", row_id="pump_row_2", col=4
            ),
            "enable_ejector": ui_options(
                "Pump", row_id="pump_row_3", col=4, readonly=True
            ),
            "ejector_images_per_drop": ui_options("Pump", row_id="pump_row_3", col=4),
        }
        # --------------------------- Processing --------------------------
        ui |= {
            "cellA": ui_options("Processing", row_id="processing_row_0"),
            "cellAlpha": ui_options("Processing", row_id="processing_row_0"),
            "cellB": ui_options("Processing", row_id="processing_row_1"),
            "cellBeta": ui_options("Processing", row_id="processing_row_1"),
            "cellC": ui_options("Processing", row_id="processing_row_2"),
            "cellGamma": ui_options("Processing", row_id="processing_row_2"),
            "space_group": ui_options("Processing", row_id="processing_row_3"),
        }
        ui["duty_cycle"].update(
            {
                "ui:widget": "select",
            }
        )

        ui["ui:order"] = list(ui.keys())

        return json.dumps(ui)


class Hve2DScanQueueEntry(AbstractSsxQueueEntry):
    QMO = Hve2DScanQueueModel
    DATA_MODEL = Hve2DScanParameters
    NAME = "Add 2D Scan"
    REQUIRES: ClassVar[list[TaskPrerequisite]] = [
        TaskPrerequisite.LINE,
        TaskPrerequisite.POINT,
    ]

    def _get_md3_exp_time(self):
        """Give the 'exposure time' argument for MD3 scan commands."""
        uc_params = self._data_model._task_data.user_collection_parameters  # noqa: SLF001

        return uc_params.exp_time * uc_params.num_images

    def _get_user_collection_params(self):
        uc_params = self._data_model._task_data.user_collection_parameters  # noqa: SLF001
        return (
            uc_params.num_images,
            uc_params.exp_time,
            uc_params.cellA,
            uc_params.cellB,
            uc_params.cellC,
            uc_params.cellAlpha,
            uc_params.cellBeta,
            uc_params.cellGamma,
        )

    def _get_filename_params(self):
        td = self._data_model._task_data  # noqa: SLF001
        dc_dict = self._data_model.as_dict()

        return (
            dc_dict["path"],
            td.path_parameters.prefix,
            dc_dict["run_number"],
        )

    def _get_shape_id(self):
        return self._data_model._task_data.collection_parameters.shape  # noqa: SLF001

    def _get_shape(self):
        return HWR.beamline.sample_view.get_shape(self._get_shape_id())

    def _prepare_detector(self, step_num: None | int = None):
        """Prepare detector for data collection.

        Args:
            step_num: optional step number, used by line-step scans
                      used to add step-suffix to data file paths

        - configure detector
        - arm detector
        """

        def get_filename_pattern() -> str:
            (
                root_dir,
                path_prefix,
                run_number,
            ) = self._get_filename_params()

            pattern = str(Path(root_dir, f"{path_prefix}_{run_number}"))
            if step_num is not None:
                # append step number suffix
                pattern = f"{pattern}_{step_num:03d}"

            return pattern

        (
            num_images,
            exp_time,
            cell_a,
            cell_b,
            cell_c,
            cell_alpha,
            cell_beta,
            cell_gamma,
        ) = self._get_user_collection_params()

        beamline = HWR.beamline
        beam_center_x, beam_center_y = beamline.collect.get_beam_centre()

        det_cfg = beamline.detector.col_config
        det_cfg["NbImages"] = 1
        det_cfg["OmegaStart"] = 0.0
        det_cfg["OmegaIncrement"] = 0.0
        det_cfg["BeamCenterX"] = beam_center_x
        det_cfg["BeamCenterY"] = beam_center_y
        det_cfg["DetectorDistance"] = mm_to_meter(
            beamline.collect.get_detector_distance()
        )
        det_cfg["NbTriggers"] = num_images
        det_cfg["CountTime"] = exp_time
        det_cfg["FilenamePattern"] = get_filename_pattern()
        if beamline.collect.is_jungfrau():
            # Jungfrau consider 0 omega increment an invalid setting,
            # and will refuse to arm. Set omega increment to a work-around value.
            det_cfg["OmegaIncrement"] = JUNGFRAU_NON_ZERO_OMEGA_INCREMENT
            # unit cell parameters are Jungfrau specific,
            # Eiger does not support them
            det_cfg["UnitCellA"] = cell_a
            det_cfg["UnitCellB"] = cell_b
            det_cfg["UnitCellC"] = cell_c
            det_cfg["UnitCellAlpha"] = cell_alpha
            det_cfg["UnitCellBeta"] = cell_beta
            det_cfg["UnitCellGamma"] = cell_gamma
        else:
            # Eiger's trigger mode must be explicitly configured each time
            det_cfg["TriggerMode"] = "exts"

        # apply configuration
        detector = beamline.detector
        dozor_dict = detector.prepare_acquisition(det_cfg)
        detector.wait_config_done()

        # arm detector
        detector.start_acquisition()

        return det_cfg, dozor_dict

    def _create_crystfel_files(self, det_cfg, dozor_dict):
        """Create CrystFEL input files."""

        collect = HWR.beamline.collect

        dc_params = queue_model_objects.to_collect_dict(
            self._data_model,
            self._data_model.get_sample_node(),
        )
        collect.current_dc_parameters = dc_params[0]

        collect.create_file_directories()
        collect.generate_crystfel_input_files(det_cfg)

        # set-up header appendix for this collection
        collect.setup_header_appendix(self._get_shape_id(), dozor_dict)

    def _prepare_scan(self, step_num=None):
        det_cfg, dozor_dict = self._prepare_detector(step_num)
        self._create_crystfel_files(det_cfg, dozor_dict)

    def _goto_position(self, motor_positions: dict):
        # remove phi (Omega) position, as we don't want to change Omega angle
        motor_positions = {k: v for k, v in motor_positions.items() if k != "omega"}
        HWR.beamline.diffractometer.set_value_motors(motor_positions)

    def _goto_selected_2d_point(self):
        shape = HWR.beamline.sample_view.get_shape(self._get_shape_id())
        self._goto_position(shape.get_centred_position().as_dict())

    def _run_point_scan(self):
        log.info("running a single 2D-point scan")

        self._prepare_scan()
        self._goto_selected_2d_point()

        # run the data collection scan
        current_omega = HWR.beamline.diffractometer.omega_motor_hwobj.get_value()
        HWR.beamline.diffractometer.do_oscillation_scan(
            current_omega,
            current_omega + 0.00000001,
            self._get_md3_exp_time(),
        )

        wait_acquisition_done()

    def _run_line_scan(self, line: Line):
        log.info("running 2D line scan")

        self._prepare_scan()

        # run the data collection scan
        current_omega = HWR.beamline.diffractometer.omega_motor_hwobj.get_value()
        start_cpos, end_cpos = line.cp_list

        HWR.beamline.diffractometer.osc_scan_4d(
            current_omega,
            current_omega + 0.00000001,
            self._get_md3_exp_time(),
            {
                "1": start_cpos.as_dict(),
                "2": end_cpos.as_dict(),
            },
        )

        wait_acquisition_done()

    def _run_step_scan(self, shape, line_step: int):
        log.info("running 2D step scan")

        for step_num, point in enumerate(_get_step_scan_points(shape, line_step)):
            self._prepare_scan(step_num)
            self._goto_position(point)

            # run the data collection scan
            current_omega = HWR.beamline.diffractometer.omega_motor_hwobj.get_value()
            HWR.beamline.diffractometer.do_oscillation_scan(
                current_omega,
                current_omega + 0.00000001,
                self._get_md3_exp_time(),
            )

            wait_acquisition_done()

    def _do_data_collection(self):
        """Perform the data collection."""
        params = self._data_model._task_data.user_collection_parameters  # noqa: SLF001

        # does generic preparations, common for all scan types
        self.prepare_data_collection()

        shape = self._get_shape()
        match _scan_type(shape, params.line_step):
            case Scans.POINT:
                self._run_point_scan()
            case Scans.LINE:
                self._run_line_scan(shape)
            case Scans.STEP:
                self._run_step_scan(shape, params.line_step)

    def execute(self):
        """Execute the queue entry.

        Mandatory method for all Queue Entries.
        """
        try:
            super().execute()
            self._do_data_collection()
        except Exception as ex:
            raise QueueExecutionException(str(ex), self) from ex
        finally:
            restore_beamline()
