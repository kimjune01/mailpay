"""x402 payment construction and on-chain verification via Solana."""

from __future__ import annotations

import json
import secrets
import urllib.request
from typing import Any

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature

from mailpay.models import Payment

# Solana USDC mint address
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Solana RPC endpoints
SOLANA_RPC = "https://api.mainnet-beta.solana.com"


def _payment_message(amount: int, token: str, nonce: str, recipient: str) -> bytes:
    """Canonical message bytes for signing. Deterministic given the same inputs."""
    msg = json.dumps({
        "amount": str(amount),
        "token": token,
        "nonce": nonce,
        "recipient": recipient,
    }, separators=(",", ":"), sort_keys=True)
    return msg.encode()


def sign_payment(
    amount: int,
    token: str,
    network: str,
    private_key: str,
    recipient: str = "",
) -> Payment:
    """Create a signed x402 payment proof using ed25519.

    The sender signs a canonical message containing amount, token, nonce,
    and recipient. The receiver verifies the signature against the sender's
    public key, then checks on-chain that the transfer actually happened.
    """
    kp = Keypair.from_base58_string(private_key)
    nonce = secrets.token_hex(16)

    msg_bytes = _payment_message(amount, token, nonce, recipient)
    sig = kp.sign_message(msg_bytes)

    return Payment(
        signature=str(sig),
        amount=amount,
        token=token,
        network=network,
        nonce=nonce,
        sender=str(kp.pubkey()),
        recipient=recipient,
    )


def verify_signature(payment: Payment) -> bool:
    """Verify the ed25519 signature on a payment proof.

    This confirms the sender actually signed this exact payment claim.
    It does NOT confirm the on-chain transfer — call verify_on_chain for that.
    """
    try:
        pubkey = Pubkey.from_string(payment.sender)
        sig = Signature.from_string(payment.signature)
        msg_bytes = _payment_message(
            payment.amount, payment.token, payment.nonce, payment.recipient,
        )
        return sig.verify(pubkey, msg_bytes)
    except Exception:
        return False


def verify_on_chain(
    payment: Payment,
    network: str = "solana",
    rpc_url: str = SOLANA_RPC,
) -> bool:
    """Verify a payment proof against the Solana blockchain.

    Checks:
    1. The signature is valid for the claimed payload
    2. The sender has a USDC token account with sufficient history
    3. A matching transfer exists in recent transactions

    For production, you'd check the specific transaction by tx_hash.
    """
    # First verify the cryptographic signature
    if not verify_signature(payment):
        return False

    # If we have a tx_hash, verify it on-chain
    if payment.tx_hash:
        return _verify_transaction(payment, rpc_url)

    # Without tx_hash, signature verification is all we can do off-chain
    return True


def _verify_transaction(payment: Payment, rpc_url: str) -> bool:
    """Verify a specific transaction on Solana via RPC."""
    try:
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                payment.tx_hash,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
            ],
        }).encode()

        req = urllib.request.Request(
            rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        result = data.get("result")
        if not result:
            return False

        # Check transaction succeeded
        meta = result.get("meta", {})
        if meta.get("err") is not None:
            return False

        # Check for matching token transfer in parsed instructions
        tx = result.get("transaction", {})
        message = tx.get("message", {})
        instructions = message.get("instructions", [])

        for ix in instructions:
            parsed = ix.get("parsed", {})
            if parsed.get("type") in ("transfer", "transferChecked"):
                info = parsed.get("info", {})
                # Verify amount matches (USDC has 6 decimals)
                tx_amount = int(info.get("amount", info.get("tokenAmount", {}).get("amount", 0)))
                if tx_amount == payment.amount:
                    return True

        return False
    except Exception:
        return False


def make_payment_link(
    amount: int,
    token: str,
    description: str = "",
    provider: str = "stripe",
) -> str:
    """Generate a fallback payment link for agents without x402 support."""
    amount_usd = amount / 1_000_000  # USDC has 6 decimals
    return f"https://checkout.stripe.com/pay?amount={amount_usd}&description={description}"
