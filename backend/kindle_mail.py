"""Email a built EPUB to a Send-to-Kindle address over plain SMTP (stdlib only).

The sender address must be on Amazon's approved list:
https://www.amazon.com/sendtokindle/email → Preferences → Approved Personal Document E-mail List.
"""
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .models import ConversionError


def configured(cfg: dict) -> bool:
    return bool(cfg.get("smtp_user") and cfg.get("smtp_pass") and cfg.get("kindle_email"))


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "", name).strip()


def send(epub: Path, cfg: dict, title: str = "") -> None:
    if not configured(cfg):
        raise ConversionError(
            "Send to Kindle isn't set up — add your email details in Settings first.")
    user = cfg["smtp_user"].strip()
    host, _, port_s = (cfg.get("smtp_host") or "").strip().partition(":")
    host = host or "smtp.gmail.com"
    try:
        port = int(port_s) if port_s else 465
    except ValueError as exc:
        raise ConversionError("SMTP port must be a number between 1 and 65535.") from exc
    if not 1 <= port <= 65535:
        raise ConversionError("SMTP port must be a number between 1 and 65535.")
    recipient = cfg["kindle_email"].strip()
    if any(re.search(r"[\x00-\x1f\x7f]", value) for value in (user, recipient, host)):
        raise ConversionError("Email addresses and SMTP host must not contain control characters.")

    name = _safe_name(title) or epub.stem
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, recipient, name
    msg.set_content("Sent by Bindery.")
    msg.add_attachment(epub.read_bytes(), maintype="application",
                       subtype="epub+zip", filename=f"{name}.epub")
    try:
        # ponytail: 465 = implicit TLS, anything else = STARTTLS; covers Gmail/Outlook/etc.
        context = ssl.create_default_context()
        connection = (smtplib.SMTP_SSL(host, port, timeout=60, context=context)
                      if port == 465 else smtplib.SMTP(host, port, timeout=60))
        with connection as server:
            if port != 465:
                server.starttls(context=context)
            server.login(user, cfg["smtp_pass"].strip())
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise ConversionError(
            "The email provider rejected the login. For Gmail you need an app password "
            "(myaccount.google.com/apppasswords), not your normal password.") from None
    except (smtplib.SMTPException, OSError) as exc:
        raise ConversionError(f"Sending failed: {exc}") from exc
