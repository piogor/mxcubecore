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

    def __init__(self, name: str) -> None:
        """Initialize the hardware object with default notification settings."""

        super().__init__(name)
        self.notify_url: str | None = None
        self.timeout: float = 10.0

    def init(self) -> None:
        """Load runtime configuration values from the hardware object config."""

        super().init()

        self.notify_url = self._config.notify_url
        self.timeout = float(self._config.timeout)

    def send_notification(self, title: str, message: str) -> bool:
        """Send a notification through the configured ESS Notify endpoint."""

        data: dict[str, str] = {
            "title": title,
            "subtitle": message,
        }

        try:
            response = requests.post(
                self.notify_url,
                json=data,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException:
            self.log.exception("Error while sending notification")
            return False

        self.log.info("Successfully sent notification")
        return True
