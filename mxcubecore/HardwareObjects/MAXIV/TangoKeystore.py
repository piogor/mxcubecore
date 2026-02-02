import logging
from typing import Any, Callable

from tango_keystore import TangoKeystore as Keystore

from mxcubecore.BaseHardwareObjects import HardwareObject

log = logging.getLogger("HWR")


class TangoKeystore(HardwareObject):
    """HWO to query tangodb free properties under specified namespace"""

    def __repr__(self):
        return f"{self.namespace}: {self.get()}"

    def init(self):
        super().init()
        self.namespace = self.get_property("namespace", None)
        self._db = self.get_property("db", None)
        try:
            self.keystore = Keystore(db=self._db, namespace=self.namespace)
        except Exception as ex:
            msg = "[KEYSTORE] Error connecting to Tango database."
            log.exception(msg)
            raise RuntimeError(msg) from ex
        self._keys = set(self.get_property("keys", []))
        self._keys = self._sanitize_keys(self._keys)

    def _sanitize_keys(self, keys: set[str]) -> set[str]:
        sanitized = set()
        for key in keys:
            if not self.keystore.exists(key):
                similar_keys = self.keystore.did_you_mean(key)
                if not len(similar_keys):
                    msg = f"Key {key} not found in tango free properties"
                    log.error(msg)
                    raise RuntimeError(msg)
                sanitized.add(similar_keys[0])
            else:
                sanitized.add(key)

        return sanitized

    def get(
        self, selector_fn: Callable[[set[str]], set[str]] = lambda s: s
    ) -> dict[str, Any]:
        """Get values for registered keys"""
        keys = selector_fn(self._keys)
        keys = self._sanitize_keys(keys)
        results = {}
        for key in keys:
            values = self.keystore.get_all(key)
            results.update(values)
        return results
