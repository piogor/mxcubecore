import concurrent.futures
import logging
import sys
import time

from tango import DeviceProxy

POLL_PERIOD = 1
# it is recommended: cpu + 4
EXECUTOR_MAX_WORKERS = 6
MAX_TRIAL = 5

log = logging.getLogger("HWR")


class SnapshotManager(object):
    def __init__(self):
        self._output = []
        self._snapman = DeviceProxy("ARCHIVING/SNAP/SNAPMANAGER-01")
        self._snapex = DeviceProxy("ARCHIVING/SNAP/SNAPEXTRACTOR-01")
        self._error = False

    def get_snapshot(self, snap_list):
        snapshot = []
        for snap_id in snap_list:
            tmp_snap = self._snapex.getsnap(snap_id)
            for motor in tmp_snap[0::3]:
                values = self._snapex.getsnapvalue([f"{snap_id}", motor])
                snapshot.append(
                    {"motor_name": motor, "read": values[0], "write": values[1]}
                )
        return snapshot

    def get_snapshot_comment(self, snap_list):
        report = ""
        for snap_id in snap_list:
            comment = self._snapman.getsnapshotcomment(snap_id)
            msg = f"Snapshot {snap_id}, comment {comment}"
            log.info(msg)
            report += f"{msg}\n"

    def compare_current_to_snapshot(self, snapshot):
        report = ""
        for motor in snapshot:
            log.info(f"{motor['motor_name']}, {motor['read']}")
            current_value = self.get_device_value(motor["motor_name"])
            if motor["read"] != "NULL":
                read_value = float(motor["read"])
            else:
                msg = "Device name {motor['motor_name']}, read value is NULL, skip it"
                report += f"{msg}\n"
                continue
            difference = read_value - current_value
            msg = (
                f"Device name {motor['motor_name']}, "
                f"value to set {read_value:.4f}, "
                f"current value {current_value:.4f}, "
                f"difference is {difference:.4f}"
            )
            log.info(msg)
            report += f"{msg}\n"
        return report

    def is_snapshot_loaded(self, snapshot, tolerance=1e-3):
        """
        check if a snapshot is loaded
        """
        for motor in snapshot:
            log.info(f"{motor['motor_name']}, {motor['read']}")
            current_value = self.get_device_value(motor["motor_name"])
            if motor["read"] != "NULL":
                read_value = float(motor["read"])
            else:
                log.info(
                    f"Device name {motor['motor_name']}, read value is NULL, skip it"
                )
                continue
            if abs(read_value - current_value) > tolerance:
                difference = read_value - current_value
                log.info(
                    f"Device name {motor['motor_name']}, "
                    f"value to set {read_value:.4f}, "
                    f"current value {current_value:.4f}, "
                    f"difference is {difference:.4f}, "
                    f"too large comparing to the tolerance {tolerance}"
                )
                return False
            difference = read_value - current_value
            msg = (
                f"Device name {motor['motor_name']}, "
                f"value to set {read_value:.4f}, "
                f"current value {current_value:.4f}, "
                f"difference is {difference:.4f}"
            )
            log.info(msg)
        return True

    def load_snapshot(
        self,
        snap_list,
        manual_list,  # noqa: ARG002 (not used, but keep it for future use?)
        simulation=False,  # noqa: FBT002
        tolerance=1e-3,
    ):
        snapshot = self.get_snapshot(snap_list)
        # Make two motor lists.
        # - Snapshot_auto are set async.
        # - The ones in the manual list are set one by one separately.
        # to do
        snapshot_auto = snapshot
        snapshot_manual = []
        if simulation:
            log.info("Running in simulation mode:")
            self.compare_current_to_snapshot(snapshot)
            return

        self.set_devices(snapshot_auto, tolerance=tolerance)
        self.set_devices_async(snapshot_manual, tolerance=tolerance)

    def is_device_ready(self, dev):
        return dev.StatusReady

    def wait_device_ready(self, dev, timeout=300):
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_device_ready(dev):
                return True
            time.sleep(POLL_PERIOD)
        msg = f"Timeout while waiting for {dev} to be Ready after {timeout} seconds"
        raise TimeoutError(msg)

    def get_device_value(self, motor):
        dev_name, attr_name = motor.rsplit("/", 1)
        dev = DeviceProxy(dev_name)
        return getattr(dev, attr_name)

    def set_device(  # noqa: C901 (too complex)
        self,
        motor,
        set_value,
        tolerance=1e-3,
        wait=True,  # noqa: FBT002,ARG002 (not used, but keep it for future use?)
    ):
        if isinstance(set_value, str):
            if set_value == "NULL":
                log.info(f"skip setting {motor}, value is NULL")
                return
            set_value = float(set_value)
        log.info(f"Setting {motor} to {set_value}")
        dev_name, attr_name = motor.rsplit("/", 1)
        dev = DeviceProxy(dev_name)
        attr_value = getattr(dev, attr_name)

        if abs(attr_value - set_value) < tolerance:
            log.info(
                f"Original {attr_name} for {dev_name} is {attr_value}, close to \
                    the set value {set_value}, skipping setting the device"
            )
            sys.exit()

        flag = ""
        try:
            ori_power_state = dev.poweron or None
            if not ori_power_state:
                dev.poweron = 1
                time.sleep(1)
            for i in range(MAX_TRIAL):
                setattr(dev, attr_name, set_value)
                self.wait_device_ready(dev)
                attr_value = getattr(dev, attr_name)
                if abs(attr_value - set_value) < tolerance:
                    log.info(f"{dev_name} has reached the set svalue {set_value}")
                    flag = "normal end"
                    break

                log.info(
                    f"{dev_name} is {attr_value}, has not reached the set svalue \
                        {set_value}, {i + 1} trial"
                )
        except Exception:
            log.exception(f"Error while setting device {motor} to {set_value}")
            flag = "Error"
        finally:
            if not ori_power_state:
                if self.is_device_ready(dev):
                    dev.poweron = 0
                else:
                    flag += (
                        f"Warning, {dev_name} is still running, "
                        "cannot turn off the power."
                    )
            attr_value = getattr(dev, attr_name)
            if abs(attr_value - set_value) > tolerance:
                flag = "Warning, not reaching the set value"
            log.info(
                f"{flag} - The final {attr_name} for {dev_name} is {attr_value}, \
                   while the set value is {set_value}"
            )

    def set_devices_async(self, motor_list, tolerance=1e-3):
        if len(motor_list) < 1:
            log.info("The async list is empty, nothing to set")
            return
        task = "set devices Asynchronously"  # noqa: F841, to check with @jin
        try:
            for motor in motor_list:
                log.info(f"Setting {motor['motor_name']} to {motor['read']}")
                self.set_device(
                    motor["motor_name"], motor["read"], tolerance=tolerance, wait=True
                )
        except Exception:
            log.exception("Error while setting devices Asynchronously")

    def set_devices(self, motor_list, tolerance=1e-3, wait=True):  # noqa: FBT002 (Boolean default positional argument)
        """Set all attributes as defined in the snapmanlist synchronously"""
        if len(motor_list) < 1:
            log.info("The sync list is empty, nothing to set")
            return
        task = "set devices synchronously"  # noqa: F841, to check with @jin

        try:
            # start the thread pool
            with concurrent.futures.ThreadPoolExecutor(
                EXECUTOR_MAX_WORKERS
            ) as executor:
                futures = [
                    executor.submit(
                        self.set_device,
                        motor["motor_name"],
                        motor["read"],
                        tolerance=tolerance,
                    )
                    for motor in motor_list
                ]
                if wait:
                    concurrent.futures.wait(futures)
                # log.info("Checking devices") # noqa: ERA001

        except Exception:
            log.exception("Error while setting devices Synchronously")
