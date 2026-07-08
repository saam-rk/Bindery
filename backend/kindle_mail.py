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
    return re.sub(r'[\\/:*?"<>|]', "", name).strip()


def send(epub: Path, cfg: dict, title: str = "") -> None:
    if not configured(cfg):
        raise ConversionError(
            "Send to Kindle isn't set up — add your email details in Settings first.")
    user = cfg["smtp_user"].strip()
    host, _, port_s = (cfg.get("smtp_host") or "").strip().partition(":")
    host = host or "smtp.gmail.com"
    port = int(port_s) if port_s.isdigit() else 465

    name = _safe_name(title) or epub.stem
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, cfg["kindle_email"].strip(), name
    msg.set_content("Sent by Bindery.")
    msg.add_attachment(epub.read_bytes(), maintype="application",
                       subtype="epub+zip", filename=f"{name}.epub")
    try:
        # ponytail: 465 = implicit TLS, anything else = STARTTLS; covers Gmail/Outlook/etc.
        cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with cls(host, port, timeout=60) as server:
            if port != 465:
                server.starttls(context=ssl.create_default_context())
            server.login(user, cfg["smtp_pass"].strip())
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise ConversionError(
            "The email provider rejected the login. For Gmail you need an app password "
            "(myaccount.google.com/apppasswords), not your normal password.") from None
    except (smtplib.SMTPException, OSError) as exc:
        raise ConversionError(f"Sending failed: {exc}") from exc
