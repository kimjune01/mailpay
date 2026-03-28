"""Solana transaction verification for the Cambio exchange."""

from __future__ import annotations

import re

from exchange.settle import _rpc

# Base58 alphabet used by Solana
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")


def is_valid_base58(address: str) -> bool:
    """Check if a string contains only valid base58 characters."""
    return bool(_BASE58_RE.match(address))


def verify_solana_tx(tx_hash: str) -> dict | None:
    """Verify a transaction exists on-chain. Returns the RPC result or None."""
    result = _rpc("getTransaction", [
        tx_hash,
        {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
    ])
    if not result.get("result"):
        return None
    return result
