"""Mock Bridge.xyz on-ramp client.

Simulates fiat-to-crypto conversion via the Bridge API (Stripe-owned).
Payer sends USD (card/bank), recipient gets USDC on-chain.

In production, replace with real Bridge API calls at https://api.bridge.xyz
"""

from __future__ import annotations

import json
import secrets
import sys
import time
import uuid
from dataclasses import dataclass

# The doodoo dance
_DANCE = [
    "💳  Initiating fiat on-ramp...",
    "🏦  Routing to Bridge.xyz...",
    "🔄  Converting USD → USDC...",
    "⛓️   Submitting to Solana...",
    "🧾  Confirming settlement...",
    "✅  Done.",
]


def _dance() -> None:
    """A little doodoo dance."""
    for frame in _DANCE:
        sys.stderr.write(f"\r  {frame}")
        sys.stderr.flush()
        time.sleep(0.4)
    sys.stderr.write("\n")


@dataclass
class OnRampResult:
    """Result of a fiat-to-crypto on-ramp."""
    virtual_account_id: str
    customer_id: str
    deposit_id: str
    amount_usd: str
    amount_usdc: str
    fee: str
    destination_tx_hash: str
    destination_chain: str
    destination_address: str
    status: str

    def to_proof(self) -> dict:
        """Convert to a mailpay-compatible proof object."""
        return {
            "type": "bridge",
            "deposit_id": self.deposit_id,
            "tx": self.destination_tx_hash,
            "chain": self.destination_chain,
            "amount": self.amount_usdc,
        }


def on_ramp(
    amount_usd: float,
    destination_address: str,
    destination_chain: str = "solana",
    destination_currency: str = "usdc",
    customer_id: str | None = None,
    api_key: str = "mock",
) -> OnRampResult:
    """Convert fiat USD to on-chain stablecoin via Bridge.

    In mock mode, simulates the full flow:
    1. Create virtual account
    2. Receive fiat deposit
    3. Convert to USDC
    4. Submit on-chain transfer
    5. Return settlement proof

    Args:
        amount_usd: Dollar amount to convert (e.g., 0.50)
        destination_address: On-chain wallet address
        destination_chain: "solana", "base", "arbitrum", etc.
        destination_currency: "usdc", "usdt", etc.
        customer_id: Bridge customer ID (auto-generated in mock)
        api_key: Bridge API key ("mock" for simulation)
    """
    if api_key != "mock":
        raise NotImplementedError("Real Bridge API not yet integrated. Use api_key='mock'.")

    _dance()

    cust_id = customer_id or str(uuid.uuid4())
    va_id = str(uuid.uuid4())
    deposit_id = str(uuid.uuid4())
    fee = round(amount_usd * 0.015, 6)  # ~1.5% fee
    usdc_amount = int((amount_usd - fee) * 1_000_000)  # 6 decimals
    tx_hash = secrets.token_hex(32)

    return OnRampResult(
        virtual_account_id=va_id,
        customer_id=cust_id,
        deposit_id=deposit_id,
        amount_usd=f"{amount_usd:.2f}",
        amount_usdc=str(usdc_amount),
        fee=f"{fee:.6f}",
        destination_tx_hash=tx_hash,
        destination_chain=destination_chain,
        destination_address=destination_address,
        status="payment_processed",
    )


def verify_on_ramp(deposit_id: str, api_key: str = "mock") -> dict:
    """Verify an on-ramp deposit completed.

    Calls GET /virtual_accounts/activity?deposit_id={deposit_id}

    Returns the activity event or raises if not found.
    """
    if api_key != "mock":
        raise NotImplementedError("Real Bridge API not yet integrated.")

    # Mock: always confirms
    return {
        "id": str(uuid.uuid4()),
        "type": "payment_processed",
        "deposit_id": deposit_id,
        "status": "completed",
    }


if __name__ == "__main__":
    # Demo: convert $0.50 to USDC on Solana
    result = on_ramp(
        amount_usd=0.50,
        destination_address="BLADERxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        destination_chain="solana",
    )
    print(json.dumps(result.to_proof(), indent=2))
