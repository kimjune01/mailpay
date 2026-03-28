"""Send SOL from hot wallet to a destination address."""

from __future__ import annotations

import base64
import json
import os
import urllib.request

MAINNET_RPC = "https://api.mainnet-beta.solana.com"


def _rpc(method: str, params: list) -> dict:
    """Make a Solana JSON-RPC call."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": method, "params": params,
    }).encode()
    req = urllib.request.Request(
        MAINNET_RPC, data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def send_sol(lamports: int, destination: str) -> str:
    """Send SOL from hot wallet to destination. Returns tx signature."""
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer
    from solders.transaction import Transaction
    from solders.message import Message
    from solders.hash import Hash

    private_key = os.environ.get("SOLANA_PRIVATE_KEY", "")
    if not private_key:
        raise RuntimeError("SOLANA_PRIVATE_KEY not set")
    if lamports <= 0:
        raise ValueError("lamports must be positive")

    kp = Keypair.from_base58_string(private_key)
    to = Pubkey.from_string(destination)

    bh_result = _rpc("getLatestBlockhash", [{"commitment": "finalized"}])
    blockhash = bh_result["result"]["value"]["blockhash"]

    ix = transfer(TransferParams(
        from_pubkey=kp.pubkey(),
        to_pubkey=to,
        lamports=lamports,
    ))
    msg = Message.new_with_blockhash([ix], kp.pubkey(), Hash.from_string(blockhash))
    tx = Transaction.new_unsigned(msg)
    tx.sign([kp], Hash.from_string(blockhash))

    encoded = base64.b64encode(bytes(tx)).decode()
    result = _rpc("sendTransaction", [encoded, {"encoding": "base64"}])

    if "error" in result:
        raise RuntimeError(f"Transaction failed: {result['error']}")

    return result["result"]
