import logging
from enum import Enum

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.model.crystal_symmetry import XTAL_SPACEGROUPS
from mxcubecore.queue_entry.base_queue_entry import BaseQueueEntry

log = logging.getLogger("queue_exec")

_space_group_enum_members = {
    # Some space groups have names that are not valid enum member names,
    # thus their names are stripped for the member names, as these are irrelevant.
    f"SG_{idx}": space_group
    for (idx, space_group) in enumerate(XTAL_SPACEGROUPS)
    if space_group  # skips the empty space group
}

SpaceGroup = Enum("SpaceGroup", _space_group_enum_members, type=str)


# This is a hack to remove the default description from the SpaceGroup enum.
@classmethod
def _remove_enum_description(_cls, field_schema: dict) -> None:
    """
    Pydantic v1 calls this whenever it generates JSON Schema for an Enum type.
    We simply pop off the default "An enumeration." description.
    """
    field_schema.pop("description", None)


SpaceGroup.__modify_schema__ = _remove_enum_description


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


def wait_acquisition_done():
    """Wait unit detector reports that data acquisition have stopped."""
    detector = HWR.beamline.detector

    log.info("Waiting for acquisition to finish.")

    #
    # deal with different behaviour of Jungfrau vs Eiger hardware objects
    #
    if HWR.beamline.collect.is_jungfrau():
        #
        # We are using Jungfrau detector. Jungfrau goes to 'ready' state
        # when acquisition is done.
        #
        detector.wait_ready()
    else:
        #
        # We are using EIGER detector. EIGER goes to 'idle' state
        # when acquisition is done.
        #
        # We can't use the wait_idle() method here. wait_idle() times out after
        # hard-coded amount of time. For SSX tasks, we need wait indefinitely,
        # until the user manually stops the task.
        #
        # Thus do a custom loop here instead.
        #
        while not detector.is_idle():
            gevent.sleep(0.25)

    log.info("Acquisition is finished.")


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

    def prepare_data_collection(self):
        """
        Prepare beamline for a SSX data collection, i.e.:

        - move detector
        - configure detector
        - set MD3 into correct phase/mode
        - open detector cover
        """

        def get_resolution():
            td = self._data_model._task_data  # noqa: SLF001
            return td.collection_parameters.resolution

        def get_hwobjs():
            beamline = HWR.beamline
            return (
                beamline.detector,
                beamline.collect,
                beamline.diffractometer,
                beamline.sample_view,
            )

        detector, collect, diffractometer, sample_view = get_hwobjs()

        #
        # make sure MD3 'direct beam' mode is disabled
        #
        diffractometer.set_direct_beam_enabled(False)

        #
        # open safety shutter
        #
        collect.open_safety_shutter()

        #
        # move detector for selected resolution
        #
        collect.set_resolution(get_resolution())

        #
        # change MD3 phase to data collection mode,
        # this moves in beam stop
        #
        diffractometer.set_phase("DataCollection")
        diffractometer.check_beamstop_is_at_beam_position()

        #
        # open detector cover
        #
        collect.open_detector_cover()

        #
        # Work around a MD3Up bug.
        #
        # Currently, running 4D-scan command on MD3 at MicroMAX
        # somehow screws up it's fast shutter state. The symptom is
        # that it's not possible to open fast shutter again after a
        # 4D-scan command is finished.
        #
        # Running 'abort' command restores the fast shutter state, thus
        # works around the issue.
        #
        HWR.beamline.diffractometer.abort()

    def stop(self):
        log.info("Aborting acquisition.")

        # We want to close the fast shutter as fast as possible on abort.
        collect = HWR.beamline.collect
        collect.close_fast_shutter()

        super().stop()
        detector = HWR.beamline.detector

        # Now we can cancel acquisition - it's ok to have some dark images.
        detector.cancel_acquisition()
        collect.close_detector_cover()
