"""x402 payment construction and on-chain verification via Solana."""

from __future__ import annotations

import json
import secrets
import urllib.request
from typing import Any

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature

from mailpay.core.models import Payment

# Solana USDC mint address
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Solana RPC endpoints
SOLANA_RPC = "https://api.mainnet-beta.solana.com"


def _payment_message(
    amount: int, token: str, nonce: str, recipient: str,
) -> bytes:
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
    and recipient wallet. The receiver verifies the signature against the
    sender's public key, then checks on-chain that the transfer happened.
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

    Requires both a valid signature AND a tx_hash referencing a real
    on-chain settlement. Without tx_hash, the proof is a claim, not
    a settlement — and we reject it.
    """
    if not verify_signature(payment):
        return False

    if not payment.tx_hash:
        return False

    return _verify_transaction(payment, rpc_url)


def _verify_transaction(payment: Payment, rpc_url: str) -> bool:
    """Verify a specific transaction on Solana via RPC.

    Checks:
    1. Transaction exists and succeeded
    2. Contains a token transfer matching amount, mint, sender, and recipient
    """
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

        # Transaction must have succeeded
        meta = result.get("meta", {})
        if meta.get("err") is not None:
            return False

        # Check parsed instructions for matching token transfer
        tx = result.get("transaction", {})
        message = tx.get("message", {})
        instructions = message.get("instructions", [])

        for ix in instructions:
            parsed = ix.get("parsed", {})
            if parsed.get("type") not in ("transfer", "transferChecked"):
                continue

            info = parsed.get("info", {})

            # Verify amount
            tx_amount = int(
                info.get("amount",
                         info.get("tokenAmount", {}).get("amount", 0))
            )
            if tx_amount != payment.amount:
                continue

            # Verify mint (for transferChecked)
            if "mint" in info and info["mint"] != payment.token:
                continue

            # Verify sender (authority or source owner)
            tx_authority = info.get("authority", info.get("source", ""))
            if payment.sender and tx_authority != payment.sender:
                continue

            # Verify recipient (destination)
            tx_destination = info.get("destination", "")
            if payment.recipient and tx_destination != payment.recipient:
                continue

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
