"""
app/emailer.py
===============
Sends the signup verification code. Uses plain SMTP from the standard
library. With no SMTP_HOST configured it prints the code to the server
console instead, so local development works without a mail account.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

log = logging.getLogger("uvicorn.error")


def send_otp_email(to_address: str, code: str, minutes: int, purpose: str = "signup") -> None:
    """Raises RuntimeError if the mail server can't be reached or refuses."""
    if not SMTP_HOST:
        log.warning("DEV MODE (no SMTP_HOST set) - verification code for %s is %s", to_address, code)
        return

    message = EmailMessage()
    message["Subject"] = "Your Kowshi Builders verification code"
    message["From"] = SMTP_FROM
    message["To"] = to_address
    message.set_content(
        f"Your verification code is {code}.\n\n"
        f"It expires in {minutes} minutes. If you didn't try to {'sign in to' if purpose == 'login' else 'sign up for'} "
        "Kowshi Builders, you can ignore this email."
    )
    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
            server.starttls(context=ssl.create_default_context())
        with server:
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        log.error("Sending OTP email failed: %s", error)
        raise RuntimeError("We couldn't send the verification email. Please try again.") from error
