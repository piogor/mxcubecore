import requests
from pydantic import BaseModel

from mxcubecore.BaseHardwareObjects import HardwareObject


class NotificationSender(HardwareObject):
    """Hardware object for sending ESS Notify notifications.

    Example YAML configuration::

      class: MAXIV.NotificationSender.NotificationSender
      configuration:
        notify_url: https://notify.maxiv.lu.se/api/v2/services/.../notifications
        timeout: 10
    """

    class HOConfig(BaseModel):
        """Configuration model for NotificationSender."""

        notify_url: str
        timeout: float = 10.0

    def send_notification(self, title: str, message: str) -> None:
        """Send a notification through the configured ESS Notify endpoint."""
        data = {
            "title": title,
            "subtitle": message,
        }

        try:
            response = requests.post(
                self._config.notify_url,
                json=data,
                timeout=self._config.timeout,
            )
            response.raise_for_status()
        except requests.RequestException:
            msg = f"Failed to send notification to {self._config.notify_url}."
            self.log.exception(msg)
            raise
        self.log.info("Successfully sent notification")
