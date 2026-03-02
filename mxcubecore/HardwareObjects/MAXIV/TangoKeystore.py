import logging
from typing import Any

from tango_keystore import TangoKeystore as Keystore

from mxcubecore.BaseHardwareObjects import HardwareObject

log = logging.getLogger("HWR")


class TangoKeystore(HardwareObject):
    """HWO to query tangodb free properties under specified namespace"""

    def __repr__(self):
        return f"{self.namespace}: {self.registered_keys}"

    def init(self):
        super().init()
        self.namespace = self.get_property("namespace", None)
        self._db = self.get_property("db", None)
        try:
            self._keystore = Keystore(db=self._db, namespace=self.namespace)
        except Exception as ex:
            msg = "[KEYSTORE] Error connecting to Tango database."
            log.exception(msg)
            raise RuntimeError(msg) from ex

        self._keys = self.get_property("keys", [])
        for key in self._keys:
            self._ensure_exists(key)

    @property
    def registered_keys(self) -> list[str]:
        """Get registered keys"""
        return self._keys

    def _is_registered(self, key: str) -> bool:
        """Check if a key is registered"""
        return key in self.registered_keys

    def _ensure_registered(self, key: str) -> None:
        """Ensure that a key is registered"""
        if not self._is_registered(key):
            msg = f"[KEYSTORE] Requested key '{key}' is not listed in registered keys."
            log.error(msg)
            raise RuntimeError(msg)

    def _ensure_exists(self, key: str) -> None:
        """Ensure that a key exists."""
        if not self._keystore.exists(key):
            oops_keys = self._keystore.did_you_mean(key)
            msg = f"[KEYSTORE] Key '{key}' does not exist; \
                did you mean one of these: {oops_keys}?"
            log.error(msg)
            raise RuntimeError(msg)

    def get(self, key: str) -> Any:
        """Get value for a registered key."""
        self._ensure_registered(key)
        self._ensure_exists(key)
        return self._keystore.get(key)

    def get_int(self, key: str) -> int:
        """Return value for a registered key as an int.

        This helps coders understand the data type of the value."""
        self._ensure_registered(key)
        self._ensure_exists(key)
        return self._keystore.getd(key)

    def get_float(self, key: str) -> float:
        """Return value for a registered key as a float.

        This helps coders understand the data type of the value.
        """
        self._ensure_registered(key)
        self._ensure_exists(key)
        return self._keystore.getf(key)

    def is_true(self, key: str) -> bool:
        """Return True if the value for a registered key is true."""
        self._ensure_registered(key)
        self._ensure_exists(key)
        return self._keystore.is_true(key)

    def is_false(self, key: str) -> bool:
        """Return True if the value for a registered key is false."""
        self._ensure_registered(key)
        self._ensure_exists(key)
        return self._keystore.is_false(key)

    # the following aliases make code a lot more comprehensible
    is_active = is_true
    is_enabled = is_true
    is_on = is_true
    is_yes = is_true
    is_inactive = is_false
    is_disabled = is_false
    is_off = is_false
    is_no = is_false
