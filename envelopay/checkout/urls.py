"""Generate mailto: URLs and QR-ready links for email payments."""

from __future__ import annotations

import json
from urllib.parse import quote, urlencode


def mailto_url(
    to_addr: str,
    task: dict | None = None,
    subject: str = "",
    payment_amount: int = 0,
    payment_token: str = "",
    payment_network: str = "solana",
    body_text: str = "",
) -> str:
    """Build a mailto: URL that pre-composes a paid email.

    Scanning a QR code of this URL opens the user's mail client
    with recipient, subject, and body pre-filled. The sending agent
    signs the envelopay header before dispatch.

    Returns a RFC 6068 mailto: URL.
    """
    params: dict[str, str] = {}

    if subject:
        params["subject"] = subject
    elif task:
        params["subject"] = f"Task: {task.get('task', 'request')}"

    body_parts: list[str] = []
    if task:
        body_parts.append(json.dumps(task, separators=(",", ":")))
    if body_text:
        body_parts.append(body_text)
    if payment_amount > 0:
        amount_display = payment_amount / 1_000_000  # USDC 6 decimals
        body_parts.append(
            f"[Payment: {amount_display} USDC on {payment_network}]"
        )
    if body_parts:
        params["body"] = "\n\n".join(body_parts)

    query = urlencode(params, quote_via=quote)
    return f"mailto:{quote(to_addr)}?{query}" if query else f"mailto:{quote(to_addr)}"


def checkout_link(
    to_addr: str,
    items: list[dict],
    payment_amount: int,
    payment_token: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    payment_network: str = "solana",
    order_id: str = "",
) -> str:
    """Generate a one-click checkout mailto: link.

    The link encodes an order as a JSON task. Clicking it opens
    the mail client; the agent signs payment and sends.
    """
    task = {
        "task": "purchase",
        "items": items,
        "amount": payment_amount,
        "token": payment_token,
        "network": payment_network,
    }
    if order_id:
        task["order_id"] = order_id

    return mailto_url(
        to_addr=to_addr,
        task=task,
        subject=f"Order {order_id}" if order_id else "Purchase",
        payment_amount=payment_amount,
        payment_token=payment_token,
        payment_network=payment_network,
    )


def qr_data(
    to_addr: str,
    task: dict | None = None,
    payment_amount: int = 0,
    payment_token: str = "",
    payment_network: str = "solana",
) -> str:
    """Return a string suitable for encoding as a QR code.

    This is just the mailto: URL. Feed it to any QR library:
        import segno
        segno.make(qr_data(...)).save("pay.png")
    """
    return mailto_url(
        to_addr=to_addr,
        task=task,
        payment_amount=payment_amount,
        payment_token=payment_token,
        payment_network=payment_network,
    )
