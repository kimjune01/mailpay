"""Poll IMAP for paid emails, parse envelopay headers, verify DKIM."""

from __future__ import annotations

import email
import imaplib
import json
from email.message import Message
from typing import Iterator

from envelopay.core.models import Payment, PaymentEmail, PaymentRequired
from envelopay.core.payment import verify_on_chain


def parse_email(raw: bytes) -> PaymentEmail:
    """Parse a raw email into a PaymentEmail with envelopay headers."""
    msg = email.message_from_bytes(raw)

    pe = PaymentEmail(
        from_addr=msg.get("From", ""),
        to_addr=msg.get("To", ""),
        subject=msg.get("Subject", ""),
        message_id=msg.get("Message-ID", ""),
        in_reply_to=msg.get("In-Reply-To", ""),
    )

    # Extract task from JSON MIME part (may contain embedded payment)
    pe.task, pe.body_text = _extract_parts(msg)

    # Extract payment: prefer body-embedded, fall back to header
    if "payment" in pe.task:
        payment_data = pe.task.pop("payment")
        pe.payment = Payment.from_header(json.dumps(payment_data))
    else:
        x_payment = msg.get("X-Payment")
        if x_payment:
            pe.payment = Payment.from_header(x_payment)

    # Parse payment-required header (402 equivalent)
    x_required = msg.get("X-Payment-Required")
    if x_required:
        pe.payment_required = PaymentRequired.from_header(x_required)

    # Parse payment response
    x_response = msg.get("X-Payment-Response")
    if x_response:
        pe.payment_response = json.loads(x_response)

    # Fallback payment link
    x_link = msg.get("X-Payment-Link")
    if x_link:
        pe.payment_link = x_link

    # DKIM verification (requires dkimpy)
    pe.dkim_verified = _verify_dkim(raw)

    return pe


def _extract_parts(msg: Message) -> tuple[dict, str]:
    """Extract JSON task and plaintext body from MIME parts."""
    task = {}
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "application/json":
                payload = part.get_payload(decode=True)
                if payload:
                    task = json.loads(payload)
            elif ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
    else:
        ct = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            if ct == "application/json":
                task = json.loads(payload)
            else:
                body = payload.decode("utf-8", errors="replace")
    return task, body


def _verify_dkim(raw: bytes) -> bool:
    """Verify DKIM signature. Requires dkimpy."""
    try:
        import dkim
        return dkim.verify(raw)
    except ImportError:
        # dkimpy not installed — skip verification
        return False
    except Exception:
        return False


def verify_payment(payment: Payment | None, network: str = "solana") -> bool:
    """Verify an envelopay payment proof against the blockchain."""
    if payment is None:
        return False
    return verify_on_chain(payment, network=network)


def receive(
    imap_host: str,
    imap_port: int = 993,
    imap_user: str = "",
    imap_pass: str = "",
    folder: str = "INBOX",
    mark_read: bool = True,
) -> Iterator[PaymentEmail]:
    """Poll IMAP for unread emails, yield parsed PaymentEmails."""
    with imaplib.IMAP4_SSL(imap_host, imap_port) as conn:
        conn.login(imap_user, imap_pass)
        conn.select(folder)

        _, msg_ids = conn.search(None, "UNSEEN")
        for msg_id in msg_ids[0].split():
            if not msg_id:
                continue
            _, data = conn.fetch(msg_id, "(RFC822)")
            if data and data[0] and isinstance(data[0], tuple):
                raw = data[0][1]
                if isinstance(raw, bytes):
                    yield parse_email(raw)
                    if mark_read:
                        conn.store(msg_id, "+FLAGS", "\\Seen")
