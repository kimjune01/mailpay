"""Solana devnet setup: keypair, airdrop, USDC mint. Zero signups."""

from __future__ import annotations

import json
import time
import urllib.request

from solders.keypair import Keypair
from solders.pubkey import Pubkey

DEVNET_RPC = "https://api.devnet.solana.com"

# Devnet USDC-like token (SPL token for testing)
# In production, use the real USDC mint: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
DEVNET_USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"


def rpc(method: str, params: list, rpc_url: str = DEVNET_RPC) -> dict:
    """Make a JSON-RPC call to Solana."""
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }).encode()
    req = urllib.request.Request(
        rpc_url, data=body, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def create_wallet() -> Keypair:
    """Generate a new Solana keypair. No signup, no account, no KYC."""
    kp = Keypair()
    print(f"Wallet created: {kp.pubkey()}")
    return kp


def airdrop(pubkey: Pubkey, lamports: int = 1_000_000_000) -> str:
    """Request free SOL on devnet. 1 SOL = 1_000_000_000 lamports."""
    try:
        result = rpc("requestAirdrop", [str(pubkey), lamports])
        sig = result.get("result", "")
        if sig:
            print(f"Airdrop requested: {lamports / 1e9} SOL → {pubkey}")
            print(f"Signature: {sig}")
        else:
            print(f"Airdrop failed: {result.get('error', 'unknown error')}")
        return sig
    except Exception as e:
        print(f"Airdrop failed: {e}")
        return ""


def check_balance(pubkey: Pubkey) -> int:
    """Check SOL balance in lamports."""
    result = rpc("getBalance", [str(pubkey)])
    balance = result.get("result", {}).get("value", 0)
    print(f"Balance: {balance / 1e9} SOL ({pubkey})")
    return balance


def wait_for_confirmation(signature: str, max_wait: int = 30) -> bool:
    """Wait for a transaction to confirm on devnet."""
    for _ in range(max_wait):
        result = rpc("getSignatureStatuses", [[signature]])
        statuses = result.get("result", {}).get("value", [None])
        if statuses[0] and statuses[0].get("confirmationStatus") in ("confirmed", "finalized"):
            return True
        time.sleep(1)
    return False


def main():
    """Full devnet setup: create two wallets, fund them, check balances."""
    print("=== Envelopay Solana Devnet Setup ===\n")

    # Create two agent wallets
    alice = create_wallet()
    bob = create_wallet()
    print()

    # Airdrop SOL to both (for gas) — devnet faucet is rate-limited
    sig_a = airdrop(alice.pubkey())
    time.sleep(2)
    sig_b = airdrop(bob.pubkey())
    print()

    # Wait for airdrops to confirm
    print("Waiting for confirmation...")
    if sig_a:
        wait_for_confirmation(sig_a)
    if sig_b:
        wait_for_confirmation(sig_b)
    print()

    # Check balances
    check_balance(alice.pubkey())
    check_balance(bob.pubkey())
    print()

    # Print keys for use in envelopay
    print("=== Use these in envelopay ===")
    print(f"Alice private key: {alice}")
    print(f"Alice public key:  {alice.pubkey()}")
    print(f"Bob private key:   {bob}")
    print(f"Bob public key:    {bob.pubkey()}")
    print()
    print("Next: sign a payment proof with alice's key, verify with bob's agent.")
    print(f"Devnet RPC: {DEVNET_RPC}")


if __name__ == "__main__":
    main()
