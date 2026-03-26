"""Data models for mailpay."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Payment:
    """An x402 payment proof attached to an email."""
    signature: str
    amount: int
    token: str
    network: str
    nonce: str = ""
    tx_hash: str = ""
    sender: str = ""
    recipient: str = ""

    def to_header(self) -> str:
        payload = {
            "signature": self.signature,
            "payload": {
                "amount": str(self.amount),
                "token": self.token,
                "network": self.network,
                "nonce": self.nonce,
                "sender": self.sender,
                "recipient": self.recipient,
                "tx_hash": self.tx_hash,
            },
        }
        return json.dumps(payload, separators=(",", ":"))

    @classmethod
    def from_header(cls, raw: str) -> Payment:
        data = json.loads(raw)
        payload = data.get("payload", {})
        return cls(
            signature=data.get("signature", ""),
            amount=int(payload.get("amount", 0)),
            token=payload.get("token", ""),
            network=payload.get("network", "solana"),
            nonce=payload.get("nonce", ""),
            sender=payload.get("sender", ""),
            recipient=payload.get("recipient", ""),
            tx_hash=payload.get("tx_hash", ""),
        )


@dataclass
class PaymentRequired:
    """An x402 payment-required response (the 402 equivalent)."""
    scheme: str = "exact"
    network: str = "solana"
    max_amount: int = 0
    token: str = ""
    resource: str = ""
    description: str = ""

    def to_header(self) -> str:
        return json.dumps({
            "scheme": self.scheme,
            "network": self.network,
            "maxAmountRequired": str(self.max_amount),
            "token": self.token,
            "resource": self.resource,
            "description": self.description,
        }, separators=(",", ":"))

    @classmethod
    def from_header(cls, raw: str) -> PaymentRequired:
        data = json.loads(raw)
        return cls(
            scheme=data.get("scheme", "exact"),
            network=data.get("network", "base"),
            max_amount=int(data.get("maxAmountRequired", 0)),
            token=data.get("token", ""),
            resource=data.get("resource", ""),
            description=data.get("description", ""),
        )


@dataclass
class PaymentEmail:
    """An email with an x402 payment header."""
    from_addr: str
    to_addr: str
    task: dict[str, Any] = field(default_factory=dict)
    body_text: str = ""
    subject: str = ""
    in_reply_to: str = ""

    # Payment (native path)
    payment: Payment | None = None
    payment_amount: int = 0
    payment_token: str = ""
    payment_network: str = "solana"
    wallet_key: str = ""
    payer_wallet: str = ""
    payee_wallet: str = ""

    # Fallback (compatibility path)
    payment_link: str = ""

    # Parsed from received email
    message_id: str = ""
    dkim_verified: bool = False
    payment_required: PaymentRequired | None = None
    payment_response: dict[str, Any] = field(default_factory=dict)

    @property
    def has_payment(self) -> bool:
        return self.payment is not None

    @property
    def has_payment_link(self) -> bool:
        return bool(self.payment_link)
