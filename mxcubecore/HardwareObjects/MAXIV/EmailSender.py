import smtplib
from email.message import EmailMessage
from pathlib import Path

from pydantic import BaseModel

from mxcubecore.BaseHardwareObjects import HardwareObject


class EmailSender(HardwareObject):
    """Hardware object for sending email through an SMTP server.

    Example:
        YAML configuration:

            class: MAXIV.EmailSender.EmailSender
            configuration:
              mail_server_address: smtp.maxiv.lu.se
              mail_server_port: 25
              sender: micromax-service@maxiv.lu.se
    """

    class HOConfig(BaseModel):
        """Configuration values for the email sender."""

        mail_server_address: str
        mail_server_port: int
        sender: str

    def __init__(self, name: str):
        """Initialize the email sender hardware object.

        Args:
            name: Hardware object name.
        """
        super().__init__(name)
        self.mail_server_address = None
        self.mail_server_port = None
        self.sender = None

    def init(self):
        """Initialize the hardware object after configuration is loaded."""

        super().init()

    def _add_attachments(
        self, msg: EmailMessage, attachments: list | str | Path | None
    ):
        """Add file attachments to an email message.

        Args:
            msg: Email message to update.
            attachments: Single file path or list of file paths to attach.
        """
        if not attachments:
            return

        if isinstance(attachments, (str, Path)):
            attachments = [attachments]

        for attachment in attachments:
            attachment_path = Path(attachment)
            with attachment_path.open("rb") as attachment_file:
                content = attachment_file.read()
            subtype = attachment_path.suffix.lstrip(".") or "octet-stream"
            msg.add_attachment(
                content,
                maintype="application",
                subtype=subtype,
                filename=attachment_path.name,
            )

    def validate_receivers(self, receivers: str) -> bool:
        """Validate the format of the receivers string.

        Args:
            receivers: Comma-separated string of email addresses to validate.

        Returns:
            True if the receivers string has a valid email-like format,
            otherwise False.
        """
        if not receivers:
            return False

        for receiver in receivers.split(","):
            if "@" not in receiver or "." not in receiver:
                return False
        return True

    def send_email(self, receivers: str, subject: str, content: str, attachments=None):
        """Send an email to the specified receivers.

        Args:
            receivers: Comma-separated string of email addresses.
            subject: Email subject.
            content: Email body.
            attachments: Single file path or list of file paths to attach.

        Raises:
            ValueError: If the receivers string is invalid.
            OSError: If the SMTP connection fails.
            smtplib.SMTPException: If the SMTP server rejects the message.
        """
        if not self.validate_receivers(receivers):
            msg = f"Invalid receivers format: '{receivers}'."
            msg += " Expected a comma-separated list of email addresses."
            raise ValueError(msg)

        msg = EmailMessage()
        msg.set_content(content or "")
        msg["Subject"] = subject or ""
        msg["From"] = self._config.sender
        msg["To"] = receivers
        self._add_attachments(msg, attachments)
        recipients = [address.addr_spec for address in msg["To"].addresses]

        try:
            with smtplib.SMTP(
                self._config.mail_server_address,
                self._config.mail_server_port,
            ) as smtp:
                smtp.sendmail(self._config.sender, recipients, msg.as_string())

        except (OSError, smtplib.SMTPException):
            self.log.exception("Error while sending email")
            raise

        self.log.info("Successfully sent email")
