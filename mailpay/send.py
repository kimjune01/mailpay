"""Compose and send paid emails via SMTP."""

from __future__ import annotations

import json
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from mailpay.models import PaymentEmail
from mailpay.payment import sign_payment


def compose(email: PaymentEmail) -> MIMEMultipart:
    """Build a MIME message with x402 payment headers."""
    msg = MIMEMultipart("mixed")
    msg["From"] = email.from_addr
    msg["To"] = email.to_addr
    msg["Subject"] = email.subject or f"Task: {email.task.get('task', 'request')}"
    msg["Message-ID"] = f"<{uuid.uuid4()}@{email.from_addr.split('@')[1]}>"

    if email.in_reply_to:
        msg["In-Reply-To"] = email.in_reply_to

    # Sign and attach payment proof
    if email.payment_amount > 0 and email.wallet_key:
        payment = sign_payment(
            amount=email.payment_amount,
            token=email.payment_token,
            network=email.payment_network,
            private_key=email.wallet_key,
        )
        msg["X-Payment"] = payment.to_header()
        email.payment = payment

    # Fallback payment link in body
    if email.payment_link:
        msg["X-Payment-Link"] = email.payment_link

    # Task payload as JSON
    if email.task:
        task_part = MIMEText(json.dumps(email.task, indent=2), "plain")
        task_part.replace_header("Content-Type", "application/json")
        msg.attach(task_part)

    # Human-readable description
    if email.body_text:
        text_part = MIMEText(email.body_text, "plain")
        msg.attach(text_part)
    elif email.payment_link and not email.task:
        text_part = MIMEText(
            f"Payment required to process this request.\n"
            f"Pay here: {email.payment_link}\n",
            "plain",
        )
        msg.attach(text_part)

    return msg


def send(
    email: PaymentEmail,
    smtp_host: str = "localhost",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_pass: str = "",
    use_tls: bool = True,
) -> str:
    """Send a paid email via SMTP. Returns the Message-ID."""
    msg = compose(email)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if use_tls:
            server.starttls()
        if smtp_user:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    return msg["Message-ID"]
