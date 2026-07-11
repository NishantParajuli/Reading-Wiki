"""Transactional email (verification + password reset).

If SMTP_HOST is unset the app still works — the message (and crucially the link) is
logged instead of sent, which is exactly what you want in local dev.
"""
import logging
from email.message import EmailMessage

import aiosmtplib

from novelwiki.config.settings import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    if not settings.SMTP_HOST:
        logger.warning("SMTP not configured — not sending '%s' to %s.\n%s", subject, to, text)
        return
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_STARTTLS,
        )
    except Exception as e:  # never let a mail hiccup break signup
        logger.error("Failed to send '%s' to %s: %s", subject, to, e)


async def send_verification_email(to: str, link: str) -> None:
    await send_email(
        to,
        "Verify your Tideglass account",
        f"Welcome to Tideglass!\n\nConfirm your email to unlock translation and uploads:\n{link}\n\n"
        f"If you didn't sign up, ignore this message.",
        html=f"<p>Welcome to Tideglass!</p><p><a href=\"{link}\">Verify your email</a> to unlock "
             f"translation and uploads.</p><p>If you didn't sign up, ignore this message.</p>",
    )


async def send_reset_email(to: str, link: str) -> None:
    await send_email(
        to,
        "Reset your Tideglass password",
        f"Reset your password with this link (valid for 1 hour):\n{link}\n\n"
        f"If you didn't request this, ignore this message.",
        html=f"<p><a href=\"{link}\">Reset your password</a> (valid for 1 hour).</p>"
             f"<p>If you didn't request this, ignore this message.</p>",
    )
