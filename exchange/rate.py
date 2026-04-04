"""Fetch live SOL/USD rate and apply spread."""

from __future__ import annotations

import json
import urllib.request

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"


FALLBACK_RATE = 80.71  # USD per SOL, updated 2026-03-31


def get_sol_usd_rate() -> float:
    """Fetch current SOL/USD price from CoinGecko. Returns USD per SOL."""
    try:
        req = urllib.request.Request(
            COINGECKO_URL,
            headers={"Accept": "application/json", "User-Agent": "cambio/0.1"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return float(data["solana"]["usd"])
    except Exception:
        return FALLBACK_RATE


def apply_spread(rate: float, spread: float = 0.30) -> float:
    """Apply spread to a rate. Buyer gets fewer SOL per dollar.

    Returns the spread-adjusted rate (USD per SOL from the buyer's perspective).
    A 30% spread means the buyer pays 30% more USD per SOL than market.
    """
    return rate * (1 + spread)


def usd_cents_to_lamports(cents: int, spread_rate: float) -> int:
    """Convert USD cents to lamports at the given spread rate.

    spread_rate is USD per SOL (already includes spread).
    """
    usd = cents / 100.0
    sol = usd / spread_rate
    return int(sol * 1_000_000_000)
