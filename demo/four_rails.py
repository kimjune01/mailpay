"""Demo: four payment rails, one protocol.

Shows all four paths through envelopay:
1. Crypto → crypto (axiomatic pays blader on-chain)
2. Card → crypto (ciphero pays via Stripe, Bridge on-ramps to USDC)
3. Crypto → card (axiomatic pays USDC, Bridge off-ramps to ciphero's bank)
4. Card → card (ciphero pays blader via Stripe, no crypto)
5. Bounce (bad proof, blader rejects)

Each path: ORDER email → verify proof → FULFILL email (or reject).
"""

from __future__ import annotations

import json
import secrets
import sys
import time

# ---------------------------------------------------------------------------
# Mock infrastructure — replace with real calls in production
# ---------------------------------------------------------------------------


def _banner(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}\n")


def _step(msg: str) -> None:
    sys.stderr.write(f"  → {msg}\n")
    sys.stderr.flush()
    time.sleep(0.3)


def mock_solana_transfer(payer: str, payee: str, amount: int) -> dict:
    """Simulate a Solana USDC transfer. Returns proof dict."""
    _step(f"Transferring {amount/1_000_000:.2f} USDC: {payer[:8]}… → {payee[:8]}…")
    _step("Confirming on Solana…")
    return {
        "tx": secrets.token_hex(32),
        "sender": payer,
        "recipient": payee,
        "nonce": secrets.token_hex(8),
        "block": 285714200 + secrets.randbelow(1000),
    }


def mock_bridge_on_ramp(amount_usd: float, dest_address: str) -> dict:
    """Simulate Bridge.xyz card → crypto on-ramp."""
    _step(f"💳 Charging ${amount_usd:.2f} via Stripe…")
    _step("🔄 Bridge.xyz converting USD → USDC…")
    _step(f"⛓️  Depositing to {dest_address[:8]}…")
    fee = round(amount_usd * 0.015, 4)
    usdc = int((amount_usd - fee) * 1_000_000)
    return {
        "type": "bridge",
        "deposit_id": secrets.token_hex(8),
        "tx": secrets.token_hex(32),
        "chain": "solana",
        "amount": str(usdc),
        "fee": f"${fee:.4f}",
    }


def mock_bridge_off_ramp(amount_usdc: int, bank_account: str) -> dict:
    """Simulate Bridge.xyz crypto → card/bank off-ramp."""
    usd = amount_usdc / 1_000_000
    fee = round(usd * 0.01, 4)
    _step(f"⛓️  Receiving {usd:.2f} USDC…")
    _step(f"🏦 Bridge.xyz converting USDC → USD…")
    _step(f"💳 Depositing ${usd - fee:.2f} to bank {bank_account[:8]}…")
    return {
        "type": "bridge_offramp",
        "payout_id": secrets.token_hex(8),
        "amount_usd": f"{usd - fee:.2f}",
        "fee": f"${fee:.4f}",
    }


def mock_stripe_charge(amount_usd: float, card: str = "visa_4242") -> dict:
    """Simulate a Stripe charge. Returns charge ID."""
    _step(f"💳 Charging ${amount_usd:.2f} on {card}…")
    return {
        "type": "stripe",
        "charge_id": f"ch_{secrets.token_hex(12)}",
        "amount": f"{amount_usd:.2f}",
    }


def mock_verify_solana(tx_hash: str, expected_amount: int) -> bool:
    """Simulate on-chain verification. Returns True if tx is real."""
    _step(f"Verifying tx {tx_hash[:12]}… on Solana…")
    if tx_hash == "BOGUS":
        _step("❌ Transaction not found!")
        return False
    _step("✅ Verified")
    return True


def mock_verify_stripe(charge_id: str) -> bool:
    """Simulate Stripe charge verification."""
    _step(f"Verifying charge {charge_id[:16]}…")
    _step("✅ Verified")
    return True


def mock_send_email(from_addr: str, to_addr: str, state: str, payload: dict) -> str:
    """Simulate sending an envelopay email. Returns Message-ID."""
    msg_id = f"<{secrets.token_hex(4)}@agentmail.to>"
    print(f"  📧 {from_addr} → {to_addr}")
    print(f"     X-Envelopay-Type: {state}")
    print(f"     Message-ID: {msg_id}")
    print(f"     {json.dumps(payload, indent=6)}")
    return msg_id


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------

AXIOMATIC = "axiomatic@agentmail.to"
BLADER = "blader@agentmail.to"
CIPHERO = "ciphero@agentmail.to"

AX_WALLET = "AXIOMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
BL_WALLET = "BLADERxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
CI_BANK = "****4567"


def demo_crypto_to_crypto():
    _banner("1. CRYPTO → CRYPTO: axiomatic pays blader on-chain")

    # Pay
    proof = mock_solana_transfer(AX_WALLET, BL_WALLET, 500_000)

    # ORDER
    req_id = mock_send_email(AXIOMATIC, BLADER, "ORDER", {
        "task": {"description": "Review PR #417"},
        "amount": "500000", "token": "USDC", "chain": "solana",
        "proof": proof,
    })

    # Verify + FULFILL
    assert mock_verify_solana(proof["tx"], 500_000)
    mock_send_email(BLADER, AXIOMATIC, "FULFILL", {
        "result": {"summary": "Approved with 2 comments"},
        "settlement": {"tx": proof["tx"], "verified": True, "block": proof["block"]},
    })
    print("\n  ✅ Done. Two emails. Sub-cent fees.\n")


def demo_card_to_crypto():
    _banner("2. CARD → CRYPTO: ciphero pays via Stripe, Bridge on-ramps")

    # On-ramp
    ramp = mock_bridge_on_ramp(0.50, BL_WALLET)

    # ORDER
    mock_send_email(CIPHERO, BLADER, "ORDER", {
        "task": {"description": "Translate README to Japanese"},
        "amount": ramp["amount"], "token": "USDC", "chain": "solana",
        "proof": ramp,
        "fallback": "https://pay.stripe.com/c/cs_live_abc123",
    })

    # Verify + FULFILL
    assert mock_verify_solana(ramp["tx"], int(ramp["amount"]))
    mock_send_email(BLADER, CIPHERO, "FULFILL", {
        "result": {"summary": "Translation complete", "artifact": "README.ja.md"},
        "settlement": {"tx": ramp["tx"], "verified": True, "block": 285714500},
    })
    print(f"\n  ✅ Done. Card charged, USDC delivered. Bridge fee: {ramp['fee']}\n")


def demo_crypto_to_card():
    _banner("3. CRYPTO → CARD: axiomatic pays USDC, ciphero off-ramps to bank")

    # Pay on-chain
    proof = mock_solana_transfer(AX_WALLET, "BRIDGE_ESCROW_ADDR", 500_000)

    # ORDER
    mock_send_email(AXIOMATIC, CIPHERO, "ORDER", {
        "task": {"description": "Proofread blog post"},
        "amount": "500000", "token": "USDC", "chain": "solana",
        "proof": proof,
    })

    # Verify
    assert mock_verify_solana(proof["tx"], 500_000)

    # Ciphero does the work, then off-ramps
    offramp = mock_bridge_off_ramp(500_000, CI_BANK)

    mock_send_email(CIPHERO, AXIOMATIC, "FULFILL", {
        "result": {"summary": "Proofread complete, 3 typos fixed"},
        "settlement": {"tx": proof["tx"], "verified": True, "block": proof["block"], "offramp": offramp},
    })
    print(f"\n  ✅ Done. Crypto in, fiat out. Ciphero got ${offramp['amount_usd']} to bank.\n")


def demo_card_to_card():
    _banner("4. CARD → CARD: ciphero pays blader via Stripe, no crypto")

    # Charge
    charge = mock_stripe_charge(0.50)

    # ORDER
    mock_send_email(CIPHERO, BLADER, "ORDER", {
        "task": {"description": "Fix CSS bug in footer"},
        "amount": "0.50", "token": "USD", "chain": "stripe",
        "proof": charge,
        "fallback": "https://cash.app/$ciphero",
    })

    # Verify + FULFILL
    assert mock_verify_stripe(charge["charge_id"])
    mock_send_email(BLADER, CIPHERO, "FULFILL", {
        "result": {"summary": "Fixed. padding-bottom was 0, now 16px."},
        "settlement": charge,
    })
    print("\n  ✅ Done. No crypto. No wallet. Same protocol.\n")


def demo_invoice():
    _banner("5. INVOICE: ciphero asks blader for a price first")

    # Ciphero sends a task without payment
    _step("Ciphero sends task with no payment attached…")
    mock_send_email(CIPHERO, BLADER, "ORDER", {
        "task": {"description": "Audit Solana program for vulnerabilities"},
    })

    # Blader replies with PAYMENT-REQUIRED
    _step("Blader doesn't work for free…")
    mock_send_email(BLADER, CIPHERO, "PAYMENT-REQUIRED", {
        "amount": "2000000",
        "token": "USDC",
        "chain": "solana",
        "fallback": "https://pay.stripe.com/c/cs_live_audit789",
    })

    # Ciphero pays and resends
    proof = mock_solana_transfer(
        "CIPHEROxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        BL_WALLET, 2_000_000,
    )
    mock_send_email(CIPHERO, BLADER, "ORDER", {
        "task": {"description": "Audit Solana program for vulnerabilities"},
        "amount": "2000000", "token": "USDC", "chain": "solana",
        "proof": proof,
    })

    # Verify + FULFILL
    assert mock_verify_solana(proof["tx"], 2_000_000)
    mock_send_email(BLADER, CIPHERO, "FULFILL", {
        "result": {"summary": "No critical vulnerabilities. 2 low-severity findings."},
        "settlement": {"tx": proof["tx"], "verified": True, "block": proof["block"]},
    })
    print("\n  ✅ Done. Four emails: ask, quote, pay, deliver.\n")


def demo_bounce():
    _banner("6. BOUNCE: bad proof, blader rejects")

    # ORDER with bogus tx
    mock_send_email(AXIOMATIC, BLADER, "ORDER", {
        "task": {"description": "Review PR #418"},
        "amount": "500000", "token": "USDC", "chain": "solana",
        "proof": {"tx": "BOGUS"},
    })

    # Verify fails
    verified = mock_verify_solana("BOGUS", 500_000)
    assert not verified

    print("\n  ❌ Bounce. Proof invalid. No FULFILL sent.")
    print("     Axiomatic's email sits unanswered.")
    print("     Trust topology unchanged. No refund needed.\n")


if __name__ == "__main__":
    demo_crypto_to_crypto()
    demo_card_to_crypto()
    demo_crypto_to_card()
    demo_card_to_card()
    demo_invoice()
    demo_bounce()

    print("=" * 60)
    print("  Six scenarios. One protocol.")
    print("  Friction is at the rail, not the envelope.")
    print("=" * 60)
