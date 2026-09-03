import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
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

    def _add_attachments(
        self, msg: EmailMessage, attachments: list[str] | str | Path | None
    ):
        """Add file attachments to the email message.

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

    def validate_receivers(self, receivers: str) -> None:
        """Validate the format of the receivers string.

        Args:
            receivers: Comma-separated string of email addresses to validate.

        Raises:
            ValueError: If the receivers string is invalid.
        """
        msg = "Expected a comma-separated list of email addresses."
        if not receivers:
            msg = f"No email receivers specified. {msg}"
            raise ValueError(msg)
        for receiver in receivers.split(","):
            _, addr = parseaddr(receiver.strip())
            if not addr:
                msg = f"Invalid email address: '{receiver.strip()}'. {msg}"
                raise ValueError(msg)

    def send_email(
        self,
        receivers: str,
        subject: str,
        content: str,
        attachments: list[str] | str | Path | None = None,
    ):
        """Send an email to the specified receivers.

        Args:
            receivers: Comma-separated string of email addresses.
            subject: Email subject.
            content: Email body.
            attachments: Single file path or list of file paths to attach.

        Raises:
            OSError: If the SMTP connection fails.
            smtplib.SMTPException: If the SMTP server rejects the message.
        """
        self.validate_receivers(receivers)
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
                smtp.send_message(
                    msg, from_addr=self._config.sender, to_addrs=recipients
                )

        except (OSError, smtplib.SMTPException):
            self.log.exception("Error while sending email")
            raise

        self.log.info("Successfully sent email")
