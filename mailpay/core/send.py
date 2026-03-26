"""Compose and send paid emails via SMTP."""

from __future__ import annotations

import json
import smtplib
import uuid
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from mailpay.core.models import PaymentEmail
from mailpay.core.payment import sign_payment


def compose(email: PaymentEmail) -> MIMEMultipart:
    """Build a MIME message with x402 payment headers."""
    msg = MIMEMultipart("mixed")
    msg["From"] = email.from_addr
    msg["To"] = email.to_addr
    msg["Subject"] = email.subject or f"Task: {email.task.get('task', 'request')}"
    msg["Message-ID"] = f"<{uuid.uuid4()}@{email.from_addr.split('@')[1]}>"

    if email.in_reply_to:
        msg["In-Reply-To"] = email.in_reply_to

    # Sign payment proof (bind to wallet addresses, not email addresses)
    if email.payment_amount > 0 and email.wallet_key:
        payment = sign_payment(
            amount=email.payment_amount,
            token=email.payment_token,
            network=email.payment_network,
            private_key=email.wallet_key,
            recipient=email.payee_wallet,
        )
        email.payment = payment

    # Task payload as JSON, with payment proof embedded in body
    if email.task:
        body = dict(email.task)
        if email.payment:
            body["payment"] = json.loads(email.payment.to_header())
        json_bytes = json.dumps(body, indent=2).encode("utf-8")
        task_part = MIMEApplication(json_bytes, _subtype="json")
        msg.attach(task_part)

    # Also put payment in header for fast parsing
    if email.payment:
        msg["X-Payment"] = email.payment.to_header()

    # Emit X-Payment-Required (402 equivalent)
    if email.payment_required:
        msg["X-Payment-Required"] = email.payment_required.to_header()

    # Fallback payment link in body
    if email.payment_link:
        msg["X-Payment-Link"] = email.payment_link

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
