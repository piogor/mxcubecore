import logging
from pathlib import Path

from mxcubecore import HardwareRepository as HWR
from mxcubecore.model import queue_model_objects
from mxcubecore.queue_entry.base_queue_entry import BaseQueueEntry
from mxcubecore.utils.units import mm_to_meter

log = logging.getLogger("queue_exec")

# A work-around value used to indicate 'no omega rotation'
# when configuring Jungfrau detector.
JUNGFRAU_NON_ZERO_OMEGA_INCREMENT = 0.000001


def restore_beamline():
    collect = HWR.beamline.collect

    #
    # close fast shutter
    #
    try:
        collect.close_fast_shutter()
    except Exception:
        log.exception("Error while closing fast shutter.")

    #
    # close detector cover
    #
    try:
        collect.close_detector_cover()
    except Exception:
        log.exception("Error while closing detector cover.")


class AbstractSsxQueueEntry(BaseQueueEntry):
    """
    Contains common code utilized by 'Injector' tasks.

    Extended by 'SSX Injector' and 'SSX Time Resolved Injector' queue entries.
    """

    def pre_execute(self):
        super().pre_execute()

        #
        # this is probably wrong approach, but let's use it for now
        #
        # make sure the 'run number' of the task is increased each time
        # we launch a new data collection run
        #
        path_template = self._data_model.acquisitions[0].path_template
        queue_model = HWR.beamline.queue_model
        path_template.run_number = queue_model.get_next_run_number(path_template)

    def prepare_data_collection(self, num_images, num_triggers):
        """
        Prepare beamline for a SSX data collection, i.e.:

        - move detector
        - configure detector
        - set MD3 into correct phase/mode
        - open detector cover
        - open fast shutter
        """

        def get_params():
            td = self._data_model._task_data  # noqa: SLF001
            dc_dict = self._data_model.as_dict()
            uc_params = td.user_collection_parameters
            col_params = td.collection_parameters

            return (
                uc_params.exp_time,
                uc_params.cellA,
                uc_params.cellB,
                uc_params.cellC,
                uc_params.cellAlpha,
                uc_params.cellBeta,
                uc_params.cellGamma,
                col_params.energy,
                col_params.resolution,
                dc_dict["path"],
                td.path_parameters.prefix,
                dc_dict["run_number"],
                col_params.shape,
            )

        def get_hwobjs():
            beamline = HWR.beamline
            return (
                beamline.detector,
                beamline.collect,
                beamline.diffractometer,
                beamline.sample_view,
            )

        #
        # fetch task parameters from model object
        #
        (
            exp_time,
            cell_a,
            cell_b,
            cell_c,
            cell_alpha,
            cell_beta,
            cell_gamma,
            energy,
            resolution,
            root_dir,
            path_prefix,
            run_number,
            shape_id,
        ) = get_params()

        detector, collect, diffractometer, sample_view = get_hwobjs()

        # If a point is selected, we want to move to it before performing collection.
        shape = sample_view.get_shape(shape_id)

        if shape and shape.t == "2DP":
            log.info("Running SSX Injector task for point: %s", shape.name)
            motor_positions = shape.get_centred_position().as_dict()
            diffractometer.move_motors(motor_positions)

        #
        # open safety shutter
        #
        collect.open_safety_shutter()

        #
        # move detector for selected resolution
        #
        collect.set_resolution(resolution)

        #
        # configure and arm detector
        #
        beam_center_x, beam_center_y = collect.get_beam_centre()
        det_cfg = detector.col_config
        det_cfg["NbImages"] = num_images
        det_cfg["OmegaStart"] = 0.0
        det_cfg["OmegaIncrement"] = 0.0
        det_cfg["BeamCenterX"] = beam_center_x
        det_cfg["BeamCenterY"] = beam_center_y
        det_cfg["DetectorDistance"] = mm_to_meter(collect.get_detector_distance())
        det_cfg["NbTriggers"] = num_triggers
        det_cfg["CountTime"] = exp_time
        det_cfg["FilenamePattern"] = str(Path(root_dir, f"{path_prefix}_{run_number}"))
        if collect.is_jungfrau():
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

        detector.prepare_acquisition(det_cfg)
        detector.wait_config_done()
        detector.start_acquisition()

        #
        # create CrystFEL input files
        #
        dc_params = queue_model_objects.to_collect_dict(
            self._data_model,
            self._data_model.get_sample_node(),
        )
        collect.current_dc_parameters = dc_params[0]

        # SSX mode must be enabled in collect when generating CrystFEL files
        old_ssx_mode = collect.ssx_mode
        collect.ssx_mode = True

        collect.create_file_directories()
        collect.generate_crystfel_input_files(det_cfg)

        # restore old SSX mode state
        collect.ssx_mode = old_ssx_mode

        #
        # change MD3 phase to data collection mode,
        # this moves in beam stop
        #
        diffractometer.set_phase("DataCollection")

        #
        # open detector cover and fast shutter
        #
        collect.open_detector_cover()
        collect.open_fast_shutter()

    def stop(self):
        super().stop()
        log.info("Aborting acquisition.")
        HWR.beamline.detector.stop_acquisition()
