"""
ISARA sample changer hardware object.

Implements the abstract interface of the AbstractSampleChanger for the CATS
and ISARA sample changer model.

Derived from Alexandre Gobbo's implementation for the EMBL SC3 sample changer.
Derived from Michael Hellmig's implementation for the BESSY CATS sample changer
Derived from Jie Nan and Bixente Rey's implementation for the MAXIV ISARA sample changer

Known sites using ISARA
    MAXIV -
       BIOMAX. (ISARA) 29puck (UNIPUCK) * 16 = 464 samples
       MICROMAX. (ISARA2) 29puck (UNIPUCK) * 16 = 464 samples
    BESSY
"""

import time
from typing import Callable

import gevent
from tango import (
    DeviceProxy,
    DevState,
)

from mxcubecore.CommandContainer import CommandObject
from mxcubecore.HardwareObjects.abstract.AbstractSampleChanger import (
    Container,
    SampleChanger,
    SampleChangerState,
)
from mxcubecore.HardwareObjects.abstract.sample_changer.Container import Basket, Pin
from mxcubecore.HardwareObjects.abstract.sample_changer.Sample import Sample
from mxcubecore.utils.tango import TangoAttributeReadError, add_attribute_channel

__author__ = "Mikel Eguiraun"
__credits__ = ["The MXCuBE collaboration"]


FailedCallback = Callable[[int, str], None]


ATTRIBUTE_POLLING = 300

# number of pucks in the dewar
NUMBER_OF_PUCKS = 29
# number of samples per puck
NUMBER_OF_SAMPLES = 16


class ISARA(SampleChanger):
    """

    Actual implementation of the ISARA Sample Changer,

    """

    __TYPE__ = "ISARA"

    def __init__(self, *args, **kwargs):
        super(ISARA, self).__init__(self.__TYPE__, False, *args, **kwargs)

    def init(self):
        #
        # DO NOT CALL SampleChanger.init()
        #  If SampleChanger.init() is called reception of signals at connection time is not done.
        #
        #  In the case of Isara we do not use an update_timer... update is done by signals from Tango channels
        #

        self.cats_loaded_lid = None
        self.cats_loaded_num = None

        # Default values
        self.cats_powered = False
        self.cats_running = False
        self.cats_state = DevState.UNKNOWN
        self.cats_lids_closed = False

        self.tangoname = DeviceProxy(self.get_property("tangoname"))

        try:
            self._create_attr_channels()
        except TangoAttributeReadError as ex:
            #
            # If we can't connect to some of the attributes, then the tango device
            # is in unusable state.
            #
            # This happens for example if sample changer is turned off and is
            # unreachable over network.
            #
            # Set our state to 'Fault' and abort initialization.
            #
            self.log.warning(
                f"could not connect to '{ex.attribute_name}' tango attribute"
            )
            self._set_state(SampleChangerState.Fault)
            return

        self._create_tango_commands()

        #
        # determine Cats geometry and prepare objects
        #
        self._init_sc_contents()

        #
        # connect channel signals to update info
        #

        self.use_update_timer = False  # do not use update_timer for Cats

        self._chnState.connect_signal("update", self.cats_state_changed)
        self._chnPathRunning.connect_signal("update", self.cats_pathrunning_changed)
        self._chnPowered.connect_signal("update", self.cats_powered_changed)
        self._chnPathSafe.connect_signal("update", self.cats_pathsafe_changed)
        self._chnPuckLoadedSample.connect_signal("update", self.cats_loaded_lid_changed)
        self._chnNumLoadedSample.connect_signal("update", self.cats_loaded_num_changed)

        # load the initial values of attributes and calculate initial state of the sample changer
        self._do_update_state()
        self._update_state()

        # connect presence channels
        self._chnBasketPresence.connect_signal("update", self.cats_baskets_changed)

        self.update_info()

    def _create_attr_channels(self):
        """Create channels"""
        self._chnState = add_attribute_channel(
            self, self.tangoname, "State", ATTRIBUTE_POLLING
        )
        self._chnPowered = add_attribute_channel(
            self, self.tangoname, "Powered", ATTRIBUTE_POLLING
        )
        self._chnPathRunning = add_attribute_channel(
            self, self.tangoname, "PathRunning", ATTRIBUTE_POLLING
        )
        self._chnPathSafe = add_attribute_channel(
            self, self.tangoname, "PathSafe", ATTRIBUTE_POLLING
        )
        self._chnNumLoadedSample = add_attribute_channel(
            self, self.tangoname, "SampleNumberOnDiff", ATTRIBUTE_POLLING
        )
        self._chnPuckLoadedSample = add_attribute_channel(
            self, self.tangoname, "PuckNumberOnDiff", ATTRIBUTE_POLLING
        )
        self._chnSampleIsDetected = add_attribute_channel(
            self, self.tangoname, "SampleDetectedOnGonio", ATTRIBUTE_POLLING
        )
        self._chnBasketPresence = add_attribute_channel(
            self, self.tangoname, "CassettePresence", ATTRIBUTE_POLLING
        )

    def _create_tango_commands(self):
        """Create tango command objects."""

        self._cmdLoad = self._add_tango_command(
            "Put", failed_callback=self._on_command_fail
        )
        self._cmdUnload = self._add_tango_command(
            "Get", failed_callback=self._on_command_fail
        )
        self._cmdChainedLoad = self._add_tango_command(
            "GetPut", failed_callback=self._on_command_fail
        )
        self._cmdAbort = self._add_tango_command(
            "abort", failed_callback=self._on_command_fail
        )
        self._cmdPowerOn = self._add_tango_command(
            "PowerOn", failed_callback=self._on_command_fail
        )
        self._cmdScanSample = self._add_tango_command(
            "Barcode", failed_callback=self._on_command_fail
        )

    def _add_tango_command(
        self,
        command_name: str,
        tango_command_name: str | None = None,
        failed_callback: FailedCallback | None = None,
    ) -> CommandObject:
        """Add command object for a Tango command.

        Args:
            command_name: Name of the command to be created.
            tango_command_name: Name of the Tango command to be used as source.
                If this is ``None`` the ``command_name`` is used instead.
            failed_callback: Option callback to invoke if running command fails.

        Returns:
            The newly created command.
        """
        command = self.add_command(
            {
                "type": "tango",
                "name": command_name,
                "tangoname": self.tangoname,
            },
            tango_command_name if tango_command_name else command_name,
        )

        if failed_callback is not None:
            self.connect(command, "commandFailed", failed_callback)

        return command

    def connect_notify(self, signal):
        if signal == SampleChanger.INFO_CHANGED_EVENT:
            self._update_cats_contents()

    def _init_sc_contents(self):
        """
        Initializes the sample changer content with default values.

        :returns: None
        :rtype: None
        """
        self.log.info("initializing contents")

        self.basket_presence = [None] * NUMBER_OF_PUCKS

        for n in range(1, NUMBER_OF_PUCKS + 1):
            self._add_component(Basket(self, n, NUMBER_OF_SAMPLES))

        self._do_update_cats_contents()
        self.log.info("initializing contents done")

    def get_sample_properties(self):
        """
        Get the sample's holder length

        :returns: sample length [mm]
        :rtype: double
        """
        return (Pin.__HOLDER_LENGTH_PROPERTY__,)

    def get_basket_list(self):
        basket_list = []
        for basket in self.get_components():
            if isinstance(basket, Basket):
                basket_list.append(basket)
        return basket_list

    def is_powered(self):
        return self._chnPowered.get_value()

    def is_path_running(self):
        return self._chnPathRunning.get_value()

    # ########################           TASKS           #########################

    def _directly_update_selected_component(self, basket_no, sample_no):
        basket = None
        sample = None

        if basket_no is not None and basket_no > 0 and basket_no <= NUMBER_OF_PUCKS:
            basket = self.get_component_by_address(Basket.get_basket_address(basket_no))
            if (
                sample_no is not None
                and sample_no > 0
                and sample_no <= basket.get_number_of_samples()
            ):
                sample = self.get_component_by_address(
                    Pin.get_sample_address(basket_no, sample_no)
                )

        self._set_selected_component(basket)
        self._set_selected_sample(sample)

    def _do_select(self, component):
        """
        Selects a new component (basket or sample).
        Uses method >_directly_update_selected_component< to actually search and select the corrected positions.

        :returns: None
        :rtype: None
        """
        self.log.info(
            "selecting component %s / type=%s" % (str(component), type(component))
        )

        if isinstance(component, Sample):
            selected_basket_no = component.get_basket_no()
            selected_sample_no = component.get_index() + 1
        elif isinstance(component, Container) and (
            component.get_type() == Basket.__TYPE__
        ):
            selected_basket_no = component.get_index() + 1
            selected_sample_no = None
        elif isinstance(component, tuple) and len(component) == 2:
            selected_basket_no = component[0]
            selected_sample_no = component[1]
        self._directly_update_selected_component(selected_basket_no, selected_sample_no)

    def _do_scan(self, component, recursive):
        """
        Scans the barcode of a single sample, puck or recursively even the complete sample changer.

        :returns: None
        :rtype: None
        """
        selected_basket = self.get_selected_component()

        if isinstance(component, Sample):
            # scan a single sample
            if (selected_basket is None) or (
                selected_basket != component.get_container()
            ):
                self._do_select(component)

            selected = self.get_selected_sample()

            lid, sample = self.basketsample_to_lidsample(
                selected.get_basket_no(), selected.get_vial_no()
            )
            argin = ["2", str(lid), str(sample), "0", "0"]
            self._execute_server_task(self._cmdScanSample, argin)
        elif isinstance(component, Container) and (
            component.get_type() == Basket.__TYPE__
        ):
            # component is a basket
            basket = component
            if recursive:
                pass
            else:
                if (selected_basket is None) or (selected_basket != basket):
                    self._do_select(basket)

                selected = self.get_selected_sample()

                for sample_index in range(basket.get_number_of_samples()):
                    basket = selected.get_basket_no()
                    num = sample_index + 1
                    lid, sample = self.basketsample_to_lidsample(basket, num)
                    argin = ["2", str(lid), str(sample), "0", "0"]
                    self._execute_server_task(self._cmdScanSample, argin)

    def load(self, sample=None, wait=True):
        """
        Load a sample.
            overwrite original load() from AbstractSampleChanger to allow finer decision
            on command to use (with or without barcode / or allow for wash in some cases)
            Implement that logic in _do_load()
            Add initial verification about the Powered:
            (NOTE) In fact should be already as the power is considered in the state handling
        """
        if not self._chnPowered.get_value():
            raise Exception(
                "CATS power is not enabled. Please switch on arm power before transferring samples."
            )

        self._update_state()  # remove software flags like Loading.
        self.log.debug("load cmd .state is:  %s " % (self.state))

        sample = self._resolve_component(sample)
        self.assert_not_charging()

        return self._execute_task(
            SampleChangerState.Loading,
            wait,
            self._do_load,
            sample,
        )

    def _do_load(self, sample=None, shifts=None):
        """
        Loads a sample on the diffractometer. Performs a simple put operation if the diffractometer is empty, and
        a sample exchange (unmount of old + mount of new sample) if a sample is already mounted on the diffractometer.
        """

        if not self._chnPowered.get_value():
            self._cmdPowerOn()
            gevent.sleep(2)
            if not self._chnPowered.get_value():
                raise Exception(
                    "ISARA power cannot be enabled. Please check arm power before transferring samples."
                )

        selected = self.get_selected_sample()
        if sample is not None:
            if sample != selected:
                self._do_select(sample)
                selected = self.get_selected_sample()
        else:
            if selected is not None:
                sample = selected
            else:
                raise Exception("No sample selected")

        basketno = selected.get_basket_no()
        sampleno = selected.get_vial_no()

        lid, sample = self.basketsample_to_lidsample(basketno, sampleno)

        # prepare argin values
        argin = [
            str(lid),
            str(sample),
        ]
        self.log.debug("doLoad argin:  %s / %s:%s" % (argin, basketno, sampleno))

        if self.has_loaded_sample():
            if selected == self.get_loaded_sample():
                raise Exception(
                    "The sample "
                    + str(self.get_loaded_sample().get_address())
                    + " is already loaded"
                )
            else:
                self.log.warning("chained load sample, sending to cats:  %s" % argin)
                return self._execute_server_task(self._cmdChainedLoad, argin)
        else:
            if self.cats_sample_on_diffr() == 1:
                self.log.warning(
                    "trying to load sample, but sample detected on diffr. aborting"
                )
                self._update_state()  # remove software flags like Loading.
            elif self.cats_sample_on_diffr() == -1:
                self.log.warning(
                    "trying to load sample, but there is a conflict on loaded sample info. aborting"
                )
                self._update_state()  # remove software flags like Loading.
            else:
                self.log.warning("load sample, sending to cats:  %s" % argin)
                return self._execute_server_task(self._cmdLoad, argin)

        return False

    def _do_unload(self, sample_slot=None, shifts=None):
        """
        Unloads a sample from the diffractometer.

        :returns: None
        :rtype: None
        """
        if not self._chnPowered.get_value():
            raise Exception(
                "ISARA power is not enabled. Please switch on arm power before transferring samples."
            )

        if not self.has_loaded_sample() or not self._chnSampleIsDetected.get_value():
            self.log.warning(
                "Trying do unload sample, but it does not seem to be any on diffr"
            )

        if sample_slot is not None:
            self._do_select(sample_slot)

        loaded_lid = self._chnPuckLoadedSample.get_value()

        if loaded_lid == -1:
            self.log.warning("unload sample, no sample mounted detected")
            return

        self.log.warning("unload sample")
        self._execute_server_task(self._cmdUnload)

    def _on_task_failed(self, task, exception):
        if task in [SampleChangerState.Loading, SampleChangerState.Unloading]:
            self.log.warning("load/unload operation failed :  %s" % exception)
            self.emit("taskFailed", str(exception))

    # ###############################################################################

    def _do_abort(self):
        """
        Aborts a running trajectory on the sample changer.

        :returns: None
        :rtype: None
        """
        self._cmdAbort()
        self._update_state()  # remove software flags like Loading.. reflects current hardware state

    # ########################           CATS EVENTS           #########################

    def cats_state_changed(self, value):
        if self.cats_state != value:
            # hack for transient states
            trials = 0

            while value in [DevState.ALARM, DevState.ON]:
                time.sleep(0.1)
                trials += 1
                self.log.warning(
                    "SAMPLE CHANGER could be in transient state. trying again"
                )
                value = self._chnState.get_value()
                if trials > 4:
                    break

        self.cats_state = value
        self._update_state()

    def cats_pathrunning_changed(self, value):
        self.cats_running = value
        self._update_state()
        self.emit("runningStateChanged", (value,))

    def cats_powered_changed(self, value):
        self.cats_powered = value
        self._update_state()
        self.emit("powerStateChanged", (value,))

    def cats_pathsafe_changed(self, value):
        self.cats_pathsafe = value
        self._update_state()
        time.sleep(1.0)
        self.emit("path_safeChanged", (value,))
        self.emit("isCollisionSafe", (value,))

    def cats_baskets_changed(self, value):
        self.log.warning("Baskets changed. %s" % value)
        for idx, val in enumerate(value):
            self.basket_presence[idx] = val
        self._update_cats_contents()
        self._update_loaded_sample()

    def cats_loaded_lid_changed(self, value):
        cats_loaded_lid = value
        cats_loaded_num = self._chnNumLoadedSample.get_value()
        self._update_loaded_sample(cats_loaded_num, cats_loaded_lid)

    def cats_loaded_num_changed(self, value):
        cats_loaded_lid = self._chnPuckLoadedSample.get_value()
        cats_loaded_num = value
        self._update_loaded_sample(cats_loaded_num, cats_loaded_lid)

    def cats_sample_on_diffr(self):
        detected = self._chnSampleIsDetected.get_value()
        on_diffr = -1 not in [self.cats_loaded_lid, self.cats_loaded_num]

        if detected and on_diffr:
            return 1
        elif detected or on_diffr:  # conflicting info
            return -1
        else:
            return 0

    # ########################           PRIVATE           #########################

    def _execute_server_task(self, method, *args, **kwargs):
        """
        Executes a task on the CATS Tango device server

        :returns: None
        :rtype: None
        """
        self._wait_device_ready(3.0)
        try:
            task_id = method(*args)
        except Exception:
            self.log.exception("exception while executing server task")
            task_id = None

        waitsafe = kwargs.get("waitsafe", False)
        self.log.debug(
            "executing method %s / task_id %s / waiting only for safe status is %s"
            % (str(method), task_id, waitsafe)
        )

        ret = None
        if task_id is None:  # Reset
            while self._is_device_busy():
                gevent.sleep(0.1)
            return False
        else:
            # introduced wait because it takes some time before the attribute PathRunning is set
            # after launching a transfer
            time.sleep(6.0)
            while True:
                if waitsafe:
                    if self.path_safe():
                        self.log.debug(
                            "server execution polling finished as path is safe"
                        )
                        break
                else:
                    if not self.path_running():
                        self.log.debug(
                            "server execution polling finished as path is not running"
                        )
                        break
                gevent.sleep(0.1)
            ret = True
        return ret

    def path_safe(self):
        return str(self._chnPathSafe.get_value()).lower() == "true"

    def path_running(self):
        return str(self._chnPathRunning.get_value()).lower() == "true"

    def _do_update_state(self):
        """
        Updates the state of the hardware object

        :returns: None
        :rtype: None
        """
        self.cats_running = self._chnPathRunning.get_value()
        self.cats_powered = self._chnPowered.get_value()
        self.cats_state = self._chnState.get_value()

    def _update_state(self):
        has_loaded = self.has_loaded_sample()
        on_diff = self._chnSampleIsDetected.get_value()

        state = self._decide_state(
            self.cats_state,
            self.cats_powered,
            has_loaded,
            on_diff,
        )

        status = SampleChangerState.tostring(state)
        self._set_state(state, status)

    def _read_state(self):
        """
        Read the state of the Tango DS and translate the state to the SampleChangerState Enum

        :returns: Sample changer state
        :rtype: AbstractSampleChanger.SampleChangerState
        """
        _state = self._chnState.get_value()
        _powered = self._chnPowered.get_value()
        _has_loaded = self.has_loaded_sample()
        _on_diff = self._chnSampleIsDetected.get_value()

        # hack for transient states
        trials = 0
        while _state in [DevState.ALARM, DevState.ON]:
            time.sleep(0.1)
            trials += 1
            self.log.warning("SAMPLE CHANGER could be in transient state. trying again")
            _state = self._chnState.get_value()
            if trials > 2:
                break

        state = self._decide_state(_state, _powered, _has_loaded, _on_diff)

        return state

    def _decide_state(self, dev_state, powered, has_loaded, on_diff):
        if dev_state == DevState.ALARM:
            _state = SampleChangerState.Alarm
        elif dev_state == DevState.FAULT:
            _state = SampleChangerState.Fault
        elif not powered:
            _state = SampleChangerState.Disabled
        elif dev_state == DevState.RUNNING:
            if self.state not in [
                SampleChangerState.Loading,
                SampleChangerState.Unloading,
            ]:
                _state = SampleChangerState.Moving
            else:
                _state = self.state
        elif dev_state == DevState.UNKNOWN:
            _state = SampleChangerState.Unknown
        elif has_loaded ^ on_diff:
            # go to Unknown state if a sample is detected on the gonio but not registered in the internal database
            # or registered but not on the gonio anymore
            self.log.warning(
                "SAMPLE CHANGER Unknown 2 (hasLoaded: %s / detected: %s)"
                % (self.has_loaded_sample(), self._chnSampleIsDetected.get_value())
            )
            _state = SampleChangerState.Unknown
        elif dev_state == DevState.ON:
            _state = SampleChangerState.Ready
        else:
            _state = SampleChangerState.Unknown

        return _state

    def _is_device_busy(self, state=None):
        """
        Checks whether Sample changer HO is busy.

        :returns: True if the sample changer is busy
        :rtype: Bool
        """
        if state is None:
            state = self._read_state()

        return state not in (
            SampleChangerState.Ready,
            SampleChangerState.Loaded,
            SampleChangerState.Alarm,
            SampleChangerState.Disabled,
            SampleChangerState.Fault,
            SampleChangerState.StandBy,
        )

    def _is_device_ready(self):
        """
        Checks whether Sample changer HO is ready.

        :returns: True if the sample changer is ready
        :rtype: Bool
        """
        state = self._read_state()
        return state in (SampleChangerState.Ready, SampleChangerState.Charging)

    def _wait_device_ready(self, timeout=None):
        """
        Waits until the samle changer HO is ready.

        :returns: None
        :rtype: None
        """
        with gevent.Timeout(timeout, Exception("Timeout waiting for device ready")):
            while not self._is_device_ready():
                gevent.sleep(0.01)

    def lidsample_to_basketsample(self, lid, num):
        return lid, num

    def basketsample_to_lidsample(self, basket, num):
        return basket, num

    def _update_loaded_sample(self, sample_num=None, lid=None):
        if None in [sample_num, lid]:
            loadedSampleNum = self._chnNumLoadedSample.get_value()
            loadedSamplePuck = self._chnPuckLoadedSample.get_value()
        else:
            loadedSampleNum = sample_num
            loadedSamplePuck = lid

        self.cats_loaded_lid = loadedSamplePuck
        self.cats_loaded_num = loadedSampleNum

        self.log.info(
            "Updating loaded sample %s:%s" % (loadedSamplePuck, loadedSampleNum)
        )

        if -1 not in [loadedSamplePuck, loadedSampleNum]:
            basket, sample = self.lidsample_to_basketsample(
                loadedSamplePuck, loadedSampleNum
            )
            new_sample = self.get_component_by_address(
                Pin.get_sample_address(basket, sample)
            )
        else:
            basket, sample = None, None
            new_sample = None

        old_sample = self.get_loaded_sample()

        self.log.debug(
            "ISARA: Sample has changed. Dealing with it - new_sample = %s / old_sample = %s"
            % (new_sample, old_sample)
        )

        if old_sample != new_sample:
            # remove 'loaded' flag from old sample but keep all other information

            if old_sample is not None:
                # there was a sample on the gonio
                loaded = False
                has_been_loaded = True
                old_sample._set_loaded(loaded, has_been_loaded)

            if new_sample is not None:
                loaded = True
                has_been_loaded = True
                new_sample._set_loaded(loaded, has_been_loaded)

            if (
                (old_sample is None)
                or (new_sample is None)
                or (old_sample.get_address() != new_loaded.get_address())
            ):
                self._trigger_loaded_sample_changed_event(new_sample)
                self._trigger_info_changed_event()

    def _do_update_cats_contents(self):
        """
        Updates the sample changer content. The state of the puck positions are
        read from the respective channels in the CATS Tango DS.
        The CATS sample sample does not have an detection of each individual sample, so all
        samples are flagged as 'Present' if the respective puck is mounted.

        :returns: None
        :rtype: None
        """
        _cassette_presence = self._chnBasketPresence.get_value()
        for basket_index in range(NUMBER_OF_PUCKS):
            is_present = _cassette_presence[basket_index]
            self.basket_presence[basket_index] = is_present
        self._update_cats_contents()

    def _update_cats_contents(self):
        self.log.warning("Updating contents %s" % str(self.basket_presence))
        for basket_index in range(NUMBER_OF_PUCKS):
            # get saved presence information from object's internal bookkeeping
            basket = self.get_components()[basket_index]
            is_present = self.basket_presence[basket_index]

            if is_present is None:
                continue

            # check if the basket presence has changed
            if is_present ^ basket.is_present():
                # a mounting action was detected ...
                if is_present:
                    # basket was mounted
                    present = True
                    scanned = False
                    datamatrix = None
                    basket._set_info(present, datamatrix, scanned)
                else:
                    # basket was removed
                    present = False
                    scanned = False
                    datamatrix = None
                    basket._set_info(present, datamatrix, scanned)

                # set the information for all dependent samples
                for sample_index in range(basket.get_number_of_samples()):
                    sample = self.get_component_by_address(
                        Pin.get_sample_address((basket_index + 1), (sample_index + 1))
                    )
                    present = sample.get_container().is_present()
                    if present:
                        datamatrix = "          "
                    else:
                        datamatrix = None
                    scanned = False
                    sample._set_info(present, datamatrix, scanned)

                    # forget about any loaded state in newly mounted or removed basket)
                    loaded = _has_been_loaded = False
                    sample._set_loaded(loaded, _has_been_loaded)

        self._trigger_contents_updated_event()
        self._update_loaded_sample()
        self._trigger_info_changed_event()

    def _on_command_fail(self, _code: int, command_name: str):
        """This command trigers showing error panel in case an ISARA command fails

        Args:
            _code: Always -1
            command_name: Name of the command that failed
        """
        self.user_log.critical("Failed executing ISARA command %s" % command_name)
