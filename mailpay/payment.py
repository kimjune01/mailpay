"""x402 payment construction and on-chain verification."""

from __future__ import annotations

import hashlib
import json
import secrets
import urllib.request
from typing import Any

from mailpay.models import Payment


def sign_payment(
    amount: int,
    token: str,
    network: str,
    private_key: str,
) -> Payment:
    """Create a signed x402 payment proof.

    In production this signs an EIP-712 typed data structure with the wallet key.
    This implementation uses a hash-based placeholder for demonstration.
    Replace with eth_account.messages.encode_defunct + Account.sign_message for real use.
    """
    nonce = secrets.token_hex(16)
    payload = json.dumps({
        "amount": str(amount),
        "token": token,
        "nonce": nonce,
    }, separators=(",", ":"))

    # Placeholder signature (replace with real EIP-712 signing)
    sig_input = f"{private_key}:{payload}".encode()
    signature = "0x" + hashlib.sha256(sig_input).hexdigest()

    return Payment(
        signature=signature,
        amount=amount,
        token=token,
        network=network,
        nonce=nonce,
    )


def verify_on_chain(payment: Payment, network: str = "base") -> bool:
    """Verify a payment proof against the blockchain.

    In production this checks the Base L2 (or other network) for:
    1. The signature is valid for the claimed payload
    2. The transfer actually occurred (token balance changed)
    3. The nonce hasn't been replayed

    This implementation uses a placeholder that checks signature format.
    Replace with web3.py or viem calls for real use.
    """
    if not payment.signature.startswith("0x"):
        return False
    if payment.amount <= 0:
        return False
    if not payment.token:
        return False
    # In production: verify EIP-712 signature, check on-chain transfer
    return True


def make_payment_link(
    amount: int,
    token: str,
    description: str = "",
    provider: str = "stripe",
) -> str:
    """Generate a fallback payment link for agents without x402 support.

    In production this calls the Stripe/Square/Adyen API to create a checkout session.
    Returns a URL the receiving agent can include in the email body.
    """
    # Placeholder — in production, call stripe.checkout.sessions.create()
    amount_usd = amount / 1_000_000  # USDC has 6 decimals
    return f"https://checkout.stripe.com/pay?amount={amount_usd}&description={description}"
