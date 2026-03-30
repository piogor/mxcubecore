#!/usr/bin/python

import argparse
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests

NOTIFY_URL = "https://notify.maxiv.lu.se/api/v2/services/5864993d-58a6-4b0e-923b-0da5164141e5/notifications"
logger = logging.getLogger(__name__)


class sendEmail:  # noqa: N801
    def __init__(self, receivers=None, sender=None):
        self.receivers = receivers
        if sender is None:
            self.sender = "micromax-service@maxiv.lu.se"
        else:
            self.sender = sender
        self.subject = None

    def set_receivers(self, receivers=None):
        self.receivers = receivers

    def set_sender(self, sender=None):
        self.sender = sender

    def send_notification(self, title, msg):
        data = {
            "title": title,
            "subtitle": msg,
        }
        try:
            requests.post(NOTIFY_URL, json=data, timeout=10)
        except requests.RequestException:
            logger.exception("Error while sending notification")

    def send_email(self, content=None, subject=None, attachments=None):
        if self.receivers is None:
            raise Exception(  # noqa: TRY002
                "Cannot send email, please provide receiver email(s)!!"  # noqa: EM101
            )
        msg = EmailMessage()
        msg.set_content(content)
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.receivers
        # self.send_notification(title=subject, msg=content)  # noqa: ERA001

        if attachments is not None and attachments != "":
            for attach in attachments:
                attach_path = Path(attach)
                with attach_path.open("rb") as attach_file:
                    attach_content = attach_file.read()
                    attach_extension = attach_path.suffix
                    msg.add_attachment(
                        attach_content,
                        maintype="application",
                        subtype=attach_extension,
                        filename=attach_path.name,
                    )

        # receivers = ['kitscontrols@maxiv.lu.se']  # noqa: ERA001
        try:
            smtp_obj = smtplib.SMTP("smtp.maxiv.lu.se", 25)
            smtp_obj.sendmail(self.sender, self.receivers, msg.as_string())
            logger.info("Successfully sent email")
        except (OSError, smtplib.SMTPException):
            raise Exception("Error: unable to send email")  # noqa: B904, EM101, TRY002


def parse_args():
    """
    parse user input and return arguments
    """
    parser = argparse.ArgumentParser(description="send email automatically")

    parser.add_argument(
        "-f", "--email_file", help="email file", type=str, default=None, required=True
    )
    return parser.parse_args()


def parse_email_file(email_file):
    email = {}
    tag = None
    content = ""
    with Path(email_file).open("r") as fp:
        line = fp.readline()
        while line and line[0] == "#":
            line = line.strip("\n")
            if tag is not None:
                email[tag] = content
            tag = line[1:]
            content = ""
            line = fp.readline()
            while line and line[0] != "#":
                if tag != "content":
                    line = line.strip("\n")
                content += line
                line = fp.readline()
    if tag is not None:
        email[tag] = content
    return email
