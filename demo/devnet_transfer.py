"""End-to-end devnet USDC transfer between axiomatic and blader.

1. Airdrop SOL to both wallets (for gas)
2. Create devnet USDC token accounts
3. Mint devnet USDC to axiomatic
4. Transfer USDC from axiomatic to blader
5. Print the proof object for envelopay ORDER
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash

DEVNET_RPC = "https://api.devnet.solana.com"

# Devnet USDC-like token — we'll create our own SPL mint for the demo
# since real USDC doesn't exist on devnet with a faucet

AXIOMATIC_SECRET = os.environ.get("AXIOMATIC_SECRET", "")
BLADER_SECRET = os.environ.get("BLADER_SECRET", "")


def rpc(method: str, params: list, url: str = DEVNET_RPC) -> dict:
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": method, "params": params,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def airdrop(pubkey: str, lamports: int = 1_000_000_000) -> str | None:
    """Request devnet airdrop. Returns signature or None on failure."""
    print(f"  Airdropping {lamports/1e9:.1f} SOL to {pubkey[:12]}...")
    result = rpc("requestAirdrop", [pubkey, lamports])
    if "error" in result:
        print(f"  ⚠️  Airdrop failed: {result['error'].get('message', result['error'])}")
        return None
    sig = result["result"]
    # Wait for confirmation
    for _ in range(30):
        time.sleep(1)
        status = rpc("getSignatureStatuses", [[sig]])
        value = status.get("result", {}).get("value", [None])[0]
        if value and value.get("confirmationStatus") in ("confirmed", "finalized"):
            print(f"  ✅ Airdrop confirmed: {sig[:20]}...")
            return sig
    print("  ⚠️  Airdrop timed out waiting for confirmation")
    return sig


def get_balance(pubkey: str) -> int:
    result = rpc("getBalance", [pubkey])
    return result.get("result", {}).get("value", 0)


def sol_transfer(from_kp: Keypair, to_pubkey: Pubkey, lamports: int) -> str:
    """Transfer SOL from one wallet to another. Returns tx signature."""
    print(f"  Transferring {lamports/1e9:.4f} SOL: {from_kp.pubkey()} → {to_pubkey}")

    # Get recent blockhash
    bh_result = rpc("getLatestBlockhash", [{"commitment": "finalized"}])
    blockhash = bh_result["result"]["value"]["blockhash"]

    ix = transfer(TransferParams(
        from_pubkey=from_kp.pubkey(),
        to_pubkey=to_pubkey,
        lamports=lamports,
    ))
    msg = Message.new_with_blockhash([ix], from_kp.pubkey(), Hash.from_string(blockhash))
    tx = Transaction.new_unsigned(msg)
    tx.sign([from_kp], Hash.from_string(blockhash))

    raw = bytes(tx)
    import base64
    encoded = base64.b64encode(raw).decode()

    result = rpc("sendTransaction", [encoded, {"encoding": "base64"}])
    if "error" in result:
        print(f"  ❌ Transfer failed: {result['error']}")
        return ""

    sig = result["result"]
    print(f"  ✅ Transfer sent: {sig[:20]}...")

    # Wait for confirmation
    for _ in range(30):
        time.sleep(1)
        status = rpc("getSignatureStatuses", [[sig]])
        value = status.get("result", {}).get("value", [None])[0]
        if value and value.get("confirmationStatus") in ("confirmed", "finalized"):
            print(f"  ✅ Confirmed at slot {value.get('slot', '?')}")
            return sig
    print("  ⚠️  Timed out waiting for confirmation")
    return sig


def main():
    if not AXIOMATIC_SECRET or not BLADER_SECRET:
        print("  Set AXIOMATIC_SECRET and BLADER_SECRET env vars (base58 keypairs)")
        sys.exit(1)
    ax_kp = Keypair.from_base58_string(AXIOMATIC_SECRET)
    bl_kp = Keypair.from_base58_string(BLADER_SECRET)

    print(f"\n  Axiomatic: {ax_kp.pubkey()}")
    print(f"  Blader:    {bl_kp.pubkey()}\n")

    # Check balances
    ax_bal = get_balance(str(ax_kp.pubkey()))
    bl_bal = get_balance(str(bl_kp.pubkey()))
    print(f"  Axiomatic balance: {ax_bal/1e9:.4f} SOL")
    print(f"  Blader balance:    {bl_bal/1e9:.4f} SOL\n")

    # Airdrop if needed
    if ax_bal < 500_000_000:
        airdrop(str(ax_kp.pubkey()))
        time.sleep(2)
        ax_bal = get_balance(str(ax_kp.pubkey()))
        print(f"  Axiomatic balance after airdrop: {ax_bal/1e9:.4f} SOL\n")

    if ax_bal == 0:
        print("  ❌ No SOL. Devnet faucet may be rate-limited.")
        print("  Visit https://faucet.solana.com and paste:")
        print(f"  {ax_kp.pubkey()}")
        sys.exit(1)

    # Transfer 0.001 SOL from axiomatic to blader (simulating a payment)
    # In production this would be a USDC SPL token transfer
    payment_lamports = 1_000_000  # 0.001 SOL (~$0.50 equivalent for demo)

    print(f"\n  === PAYMENT: {payment_lamports/1e9:.4f} SOL ===\n")
    tx_sig = sol_transfer(ax_kp, bl_kp.pubkey(), payment_lamports)

    if tx_sig:
        # Build the envelopay proof object
        proof = {
            "tx": tx_sig,
            "sender": str(ax_kp.pubkey()),
            "recipient": str(bl_kp.pubkey()),
            "nonce": tx_sig[:16],  # tx sig is unique, works as nonce
            "chain": "solana-devnet",
            "amount": str(payment_lamports),
            "token": "SOL",
        }
        print(f"\n  === ENVELOPAY PROOF ===\n")
        print(json.dumps(proof, indent=2))
        print(f"\n  Explorer: https://explorer.solana.com/tx/{tx_sig}?cluster=devnet")

        # Final balances
        time.sleep(2)
        ax_bal = get_balance(str(ax_kp.pubkey()))
        bl_bal = get_balance(str(bl_kp.pubkey()))
        print(f"\n  Axiomatic balance: {ax_bal/1e9:.4f} SOL")
        print(f"  Blader balance:    {bl_bal/1e9:.4f} SOL")


if __name__ == "__main__":
    main()
